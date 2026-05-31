"""Core reconciliation engine.

Brings together the parser, diff engine, schema comparator, and integrity
checker, then layers declared intent (from a Jira ticket and a code diff) on top
to assign each change a decision. Every threshold consulted comes from
``contract.thresholds`` -- there are no magic numbers in this module.

Decision precedence (highest first): BLOCK > ESCALATE > SUGGEST > AUTO_APPLY.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from schema.contract_models import SchemaContract
from schema.contract_loader import get_section
from parser.generic_parser import parse_file
from parser.diff_engine import diff_sections
from parser.schema_comparator import SchemaChange, compare_schemas
from parser.integrity_checker import IntegrityViolation, check_integrity


BLOCK = "BLOCK"
ESCALATE = "ESCALATE"
SUGGEST = "SUGGEST"
AUTO_APPLY = "AUTO_APPLY"


@dataclass
class AgentFinding:
    """A single decision-bearing finding (row-level or schema-level)."""

    finding_id: str
    section: str
    row_id: str | None
    change_type: str  # ADDED | REMOVED | MODIFIED | COLUMN_ADDED | COLUMN_REMOVED
    in_jira_ticket: bool
    in_code_diff: bool
    fk_valid: bool
    companion_rows_present: bool
    blast_radius: int
    decision: str
    reason: str
    base_value: object = None
    new_value: object = None


@dataclass
class ReconciliationReport:
    """The full output of a reconciliation run."""

    deployment_id: str
    contract_name: str
    contract_version: str
    findings: list[AgentFinding] = field(default_factory=list)
    integrity_violations: list[IntegrityViolation] = field(default_factory=list)
    schema_changes: list[SchemaChange] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


class Reconciler:
    """Produces a :class:`ReconciliationReport` from two config versions + intent."""

    def reconcile(
        self,
        base_text: str,
        new_text: str,
        intent,
        declared_changes,
        contract: SchemaContract,
    ) -> ReconciliationReport:
        base_sections = parse_file(base_text, contract)
        new_sections = parse_file(new_text, contract)

        row_findings = diff_sections(base_sections, new_sections, contract)
        schema_changes = compare_schemas(base_sections, new_sections, contract)
        integrity_violations = check_integrity(new_sections, contract)

        fk_violations = {
            (v.section, v.row_id)
            for v in integrity_violations
            if v.violation_type == "FK_VIOLATION"
        }
        companion_violations = {
            (v.section, v.row_id)
            for v in integrity_violations
            if v.violation_type == "COMPANION_VIOLATION"
        }

        thresholds = contract.thresholds
        findings: list[AgentFinding] = []
        counter = 0

        # ---- Row-level findings -------------------------------------------
        for finding in row_findings:
            if finding.change_type == "IDENTICAL":
                continue

            counter += 1
            section = finding.section
            row_id = finding.row_id
            change_type = finding.change_type

            in_ticket = _in_ticket(section, row_id, change_type, intent)
            in_diff = _in_diff(section, row_id, change_type, declared_changes)

            if change_type == "REMOVED":
                fk_valid = True
                companion_present = True
                subject_row = finding.base_row
                dataset = base_sections
            else:
                fk_valid = (section, row_id) not in fk_violations
                companion_present = (section, row_id) not in companion_violations
                subject_row = finding.new_row
                dataset = new_sections

            blast_radius = _blast_radius(section, subject_row, dataset, contract)

            agent_finding = AgentFinding(
                finding_id=f"F{counter:03d}-{section}-{change_type}-{row_id}",
                section=section,
                row_id=row_id,
                change_type=change_type,
                in_jira_ticket=in_ticket,
                in_code_diff=in_diff,
                fk_valid=fk_valid,
                companion_rows_present=companion_present,
                blast_radius=blast_radius,
                decision="",
                reason="",
                base_value=finding.base_row,
                new_value=finding.new_row,
            )
            agent_finding.decision, agent_finding.reason = _decide_row(
                agent_finding, thresholds
            )
            findings.append(agent_finding)

        # ---- Schema-level findings ----------------------------------------
        for change in schema_changes:
            if change.change_type not in ("COLUMN_ADDED", "COLUMN_REMOVED"):
                continue

            counter += 1
            section = change.section
            if change.change_type == "COLUMN_ADDED":
                dataset = new_sections
            else:
                dataset = base_sections
            blast_radius = len(dataset.get(section, []))

            decision, reason = _decide_schema(change, contract)
            findings.append(
                AgentFinding(
                    finding_id=f"F{counter:03d}-{section}-{change.change_type}-{change.column_name}",
                    section=section,
                    row_id=None,
                    change_type=change.change_type,
                    in_jira_ticket=False,
                    in_code_diff=False,
                    fk_valid=True,
                    companion_rows_present=True,
                    blast_radius=blast_radius,
                    decision=decision,
                    reason=reason,
                    base_value=change.column_name
                    if change.change_type == "COLUMN_REMOVED"
                    else None,
                    new_value=change.column_name
                    if change.change_type == "COLUMN_ADDED"
                    else None,
                )
            )

        report = ReconciliationReport(
            deployment_id=_new_deployment_id(),
            contract_name=contract.contract_name,
            contract_version=contract.version,
            findings=findings,
            integrity_violations=integrity_violations,
            schema_changes=schema_changes,
            summary=_build_summary(findings, integrity_violations, schema_changes),
        )
        return report


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------


def _decide_row(f: AgentFinding, t) -> tuple[str, str]:
    """Apply the contract-driven decision rules to a row-level finding."""

    ct = f.change_type
    declared = f.in_jira_ticket or f.in_code_diff

    # --- BLOCK ---------------------------------------------------------------
    if ct == "REMOVED" and not f.in_jira_ticket and not f.in_code_diff:
        return BLOCK, "Undeclared removal: row deleted with no ticket or diff evidence"
    if f.fk_valid is False:
        return BLOCK, "Foreign key reference is invalid"
    if (
        ct == "MODIFIED"
        and not declared
        and f.blast_radius > t.block_undeclared_modify_blast_radius
    ):
        return (
            BLOCK,
            f"Undeclared modification with blast radius {f.blast_radius} "
            f"exceeds block threshold {t.block_undeclared_modify_blast_radius}",
        )

    # --- ESCALATE ------------------------------------------------------------
    if not f.in_jira_ticket and not f.in_code_diff:
        return ESCALATE, "Change is not declared in the ticket or the diff"
    if f.companion_rows_present is False:
        return ESCALATE, "Required companion rows are missing"

    # --- SUGGEST -------------------------------------------------------------
    if declared and f.blast_radius > t.suggest_min_blast_radius:
        return (
            SUGGEST,
            f"Declared change with blast radius {f.blast_radius} above "
            f"suggest threshold {t.suggest_min_blast_radius}",
        )

    # --- AUTO_APPLY (downgrades to SUGGEST when auto-apply is disabled) ------
    qualifies_auto = (
        f.in_jira_ticket
        and f.in_code_diff
        and f.fk_valid
        and f.companion_rows_present
        and f.blast_radius <= t.auto_apply_max_blast_radius
    )
    if qualifies_auto:
        if t.allow_auto_apply:
            return (
                AUTO_APPLY,
                "Declared in ticket and diff, FK valid, companions present, "
                "blast radius within auto-apply limit",
            )
        return SUGGEST, "Qualifies for auto-apply but auto-apply is disabled by contract"

    return ESCALATE, "Change does not meet auto-apply criteria; manual review required"


def _decide_schema(change: SchemaChange, contract: SchemaContract) -> tuple[str, str]:
    """Schema changes never AUTO_APPLY -- the floor is SUGGEST."""

    if change.change_type == "COLUMN_REMOVED":
        if _section_referenced_by_fk(change.section, contract):
            return (
                BLOCK,
                f"Column '{change.column_name}' removed from section "
                f"'{change.section}' which is referenced by a foreign key",
            )
        return (
            ESCALATE,
            f"Column '{change.column_name}' removed from section "
            f"'{change.section}' (no FK dependencies)",
        )
    if change.change_type == "COLUMN_ADDED":
        return (
            SUGGEST,
            f"Column '{change.column_name}' added to section '{change.section}'",
        )
    return SUGGEST, "Schema change requires review"


# ---------------------------------------------------------------------------
# Intent / diff matching
# ---------------------------------------------------------------------------


_CHANGE_TO_INTENT = {
    "ADDED": "declared_additions",
    "REMOVED": "declared_removals",
    "MODIFIED": "declared_modifications",
}

_CHANGE_TO_OPERATIONS = {
    "ADDED": {"ADD"},
    "REMOVED": {"REMOVE"},
    "MODIFIED": {"ADD", "REMOVE"},
}


def _in_ticket(section: str, row_id, change_type: str, intent) -> bool:
    if intent is None:
        return False
    attr = _CHANGE_TO_INTENT.get(change_type)
    if attr is None:
        return False
    for item in getattr(intent, attr, []) or []:
        if item.get("section") != section:
            continue
        hint = str(item.get("row_hint", ""))
        if row_id is None or hint == "" or str(row_id) in hint:
            return True
    return False


def _in_diff(section: str, row_id, change_type: str, declared_changes) -> bool:
    if not declared_changes:
        return False
    operations = _CHANGE_TO_OPERATIONS.get(change_type, set())
    for change in declared_changes:
        if change.section != section or change.operation not in operations:
            continue
        hint = str(getattr(change, "row_hint", "") or "")
        if row_id is None or hint == "" or str(row_id) in hint:
            return True
    return False


# ---------------------------------------------------------------------------
# Contract-driven helpers
# ---------------------------------------------------------------------------


def _blast_radius(section: str, subject_row, dataset, contract: SchemaContract) -> int:
    """Count rows in OTHER sections referencing this row via contract FK rules."""

    if subject_row is None:
        return 0
    total = 0
    for other in contract.sections:
        for fk in other.foreign_keys:
            if fk.references_section != section:
                continue
            referenced_value = subject_row.get(fk.references_column)
            if referenced_value in (None, ""):
                continue
            for row in dataset.get(other.name, []):
                if row.get(fk.column) == referenced_value:
                    total += 1
    return total


def _section_referenced_by_fk(section: str, contract: SchemaContract) -> bool:
    for other in contract.sections:
        for fk in other.foreign_keys:
            if fk.references_section == section:
                return True
    return False


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def _new_deployment_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"deploy-{stamp}-{uuid4().hex[:8]}"


def _build_summary(findings, integrity_violations, schema_changes) -> dict:
    decisions = {BLOCK: 0, ESCALATE: 0, SUGGEST: 0, AUTO_APPLY: 0}
    for finding in findings:
        decisions[finding.decision] = decisions.get(finding.decision, 0) + 1
    return {
        "total_findings": len(findings),
        "decisions": decisions,
        "integrity_violations": len(integrity_violations),
        "schema_changes": len(schema_changes),
    }
