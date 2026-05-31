"""Deterministic post-merge validation — not AI-judged.

Re-parses the generated merged file and runs the same integrity, schema, and
diff checks used for fresh deployments. Every change must trace to an approved
operation in the original plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from parser.diff_engine import diff_sections
from parser.generic_parser import parse_file
from parser.integrity_checker import IntegrityViolation, check_integrity
from parser.schema_comparator import SchemaChange, compare_schemas
from schema.contract_models import SchemaContract

from .merge_planner import MergePlan

Verdict = Literal["ACCEPTED", "REJECTED"]


@dataclass
class UnexpectedMutation:
    section: str
    row_id: str | None
    change_type: str
    message: str
    changed_fields: list[str] = field(default_factory=list)


@dataclass
class OrphanRow:
    section: str
    row_id: str | None
    message: str


@dataclass
class RereviewReport:
    passed: bool
    integrity_violations: list[IntegrityViolation] = field(default_factory=list)
    unexpected_mutations: list[UnexpectedMutation] = field(default_factory=list)
    orphan_rows: list[OrphanRow] = field(default_factory=list)
    verdict: Verdict = "REJECTED"
    rejection_reasons: list[str] = field(default_factory=list)


def rereview_merged(
    merged_text: str,
    old_text: str,
    contract: SchemaContract,
    original_plan: MergePlan,
) -> RereviewReport:
    """Validate ``merged_text`` against ``old_text`` and ``original_plan``."""

    merged = parse_file(merged_text, contract)
    old = parse_file(old_text, contract)

    integrity_violations = check_integrity(merged, contract)
    schema_changes = compare_schemas(old, merged, contract)
    findings = diff_sections(old, merged, contract)

    approved_rows = _approved_add_rows(original_plan)
    approved_columns = _approved_add_columns(original_plan)

    unexpected_mutations: list[UnexpectedMutation] = []
    orphan_rows: list[OrphanRow] = []

    unexpected_mutations.extend(
        _schema_violations(schema_changes, approved_columns)
    )

    for finding in findings:
        if finding.change_type == "REMOVED":
            orphan_rows.append(
                OrphanRow(
                    section=finding.section,
                    row_id=finding.row_id,
                    message=(
                        f"Row '{finding.row_id}' in section '{finding.section}' "
                        f"was removed without an approved operation"
                    ),
                )
            )
            continue

        if finding.change_type == "MODIFIED":
            unexpected_mutations.append(
                UnexpectedMutation(
                    section=finding.section,
                    row_id=finding.row_id,
                    change_type="MODIFIED",
                    message=(
                        f"Row '{finding.row_id}' in section '{finding.section}' "
                        f"was altered without an approved operation"
                    ),
                    changed_fields=list(finding.changed_fields),
                )
            )
            continue

        if finding.change_type == "ADDED":
            key = (finding.section, finding.row_id)
            if key not in approved_rows:
                unexpected_mutations.append(
                    UnexpectedMutation(
                        section=finding.section,
                        row_id=finding.row_id,
                        change_type="ADDED",
                        message=(
                            f"Row '{finding.row_id}' in section '{finding.section}' "
                            f"was added but has no matching approved ADD_ROW "
                            f"operation"
                        ),
                    )
                )

    rejection_reasons = _build_rejection_reasons(
        integrity_violations, unexpected_mutations, orphan_rows
    )
    passed = (
        not integrity_violations
        and not unexpected_mutations
        and not orphan_rows
    )

    return RereviewReport(
        passed=passed,
        integrity_violations=integrity_violations,
        unexpected_mutations=unexpected_mutations,
        orphan_rows=orphan_rows,
        verdict="ACCEPTED" if passed else "REJECTED",
        rejection_reasons=rejection_reasons,
    )


def _approved_add_rows(plan: MergePlan) -> set[tuple[str, str | None]]:
    return {
        (op.section, op.target_id)
        for op in plan.operations
        if op.op_type == "ADD_ROW" and op.target_id not in (None, "")
    }


def _approved_add_columns(plan: MergePlan) -> set[tuple[str, str]]:
    approved: set[tuple[str, str]] = set()
    for op in plan.operations:
        if op.op_type != "ADD_COLUMN":
            continue
        for column_name in op.values:
            approved.add((op.section, column_name))
    return approved


def _schema_violations(
    schema_changes: list[SchemaChange],
    approved_columns: set[tuple[str, str]],
) -> list[UnexpectedMutation]:
    violations: list[UnexpectedMutation] = []

    for change in schema_changes:
        if change.change_type == "UNDECLARED_COLUMN":
            violations.append(
                UnexpectedMutation(
                    section=change.section,
                    row_id=None,
                    change_type="UNDECLARED_COLUMN",
                    message=(
                        f"Undeclared column '{change.column_name}' appeared in "
                        f"section '{change.section}'"
                    ),
                )
            )
            continue

        if change.change_type == "COLUMN_ADDED":
            key = (change.section, change.column_name)
            if key not in approved_columns:
                violations.append(
                    UnexpectedMutation(
                        section=change.section,
                        row_id=None,
                        change_type="COLUMN_ADDED",
                        message=(
                            f"Column '{change.column_name}' was added to section "
                            f"'{change.section}' without an approved ADD_COLUMN "
                            f"operation"
                        ),
                    )
                )
            continue

        if change.change_type == "COLUMN_REMOVED":
            violations.append(
                UnexpectedMutation(
                    section=change.section,
                    row_id=None,
                    change_type="COLUMN_REMOVED",
                    message=(
                        f"Column '{change.column_name}' was removed from section "
                        f"'{change.section}' without an approved operation"
                    ),
                )
            )

    return violations


def _build_rejection_reasons(
    integrity_violations: list[IntegrityViolation],
    unexpected_mutations: list[UnexpectedMutation],
    orphan_rows: list[OrphanRow],
) -> list[str]:
    reasons: list[str] = []

    for violation in integrity_violations:
        reasons.append(f"Integrity: {violation.message}")

    for mutation in unexpected_mutations:
        detail = mutation.message
        if mutation.changed_fields:
            detail += f" (fields: {', '.join(mutation.changed_fields)})"
        reasons.append(f"Unexpected mutation: {detail}")

    for orphan in orphan_rows:
        reasons.append(f"Orphan row: {orphan.message}")

    return reasons
