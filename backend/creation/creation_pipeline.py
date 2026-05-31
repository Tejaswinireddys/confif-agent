"""End-to-end creation pipeline: gap analysis through deterministic re-review."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from parser.generic_parser import parse_file
from schema.contract_models import SchemaContract

from .gap_analyzer import GapReport, analyze_gaps
from .input_collector import apply_human_inputs
from .merge_applier import ChangelogEntry, apply_plan, serialize_merged
from .merge_planner import MergePlan, build_plan
from .plan_validator import PlanIssue, validate_plan
from .rereview import RereviewReport, rereview_merged

DEFAULT_CREATION_SNAPSHOT_ROOT = (
    Path(__file__).resolve().parent.parent / "snapshots" / "creation"
)

SessionState = Literal["AWAITING_HUMAN_INPUT", "AWAITING_APPROVAL", "BLOCKED"]
ResultVerdict = Literal["ACCEPTED", "REJECTED", "AWAITING_HUMAN_INPUT", "BLOCKED"]


@dataclass
class CreationSession:
    session_id: str
    state: SessionState
    contract: SchemaContract
    old_text: str
    new_text: str
    gap_report: GapReport
    plan: MergePlan
    plan_issues: list[PlanIssue] = field(default_factory=list)
    jira_intent: object | None = None
    diff_changes: object | None = None


@dataclass
class CreationResult:
    verdict: ResultVerdict
    session_id: str
    plan: MergePlan
    rereview: RereviewReport | None = None
    merged_text: str | None = None
    changelog: list[ChangelogEntry] = field(default_factory=list)
    snapshot_path: Path | None = None
    rejection_reasons: list[str] = field(default_factory=list)


def run_creation(
    old_text: str,
    new_text: str,
    contract: SchemaContract,
    jira_intent: object | None = None,
    diff_changes: object | None = None,
) -> CreationSession:
    """Analyze gaps and build a validated merge plan."""

    old = parse_file(old_text, contract)
    new = parse_file(new_text, contract)

    gap_report = analyze_gaps(old, new, contract)
    plan = build_plan(gap_report, old, new, contract)
    plan_issues = validate_plan(plan, contract)

    if plan.blocked:
        state: SessionState = "BLOCKED"
    elif plan.human_inputs_needed:
        state = "AWAITING_HUMAN_INPUT"
    else:
        state = "AWAITING_APPROVAL"

    return CreationSession(
        session_id=plan.plan_id,
        state=state,
        contract=contract,
        old_text=old_text,
        new_text=new_text,
        gap_report=gap_report,
        plan=plan,
        plan_issues=plan_issues,
        jira_intent=jira_intent,
        diff_changes=diff_changes,
    )


def finalize_creation(
    session: CreationSession,
    human_inputs: dict[str, dict[str, str]] | None = None,
    approvals: set[str] | None = None,
    snapshot_root: str | Path = DEFAULT_CREATION_SNAPSHOT_ROOT,
) -> CreationResult:
    """Apply human inputs, merge, and run deterministic re-review."""

    if session.state == "BLOCKED":
        return CreationResult(
            verdict="BLOCKED",
            session_id=session.session_id,
            plan=session.plan,
            rejection_reasons=[
                item.reason for item in session.plan.blocked
            ],
        )

    plan = session.plan

    if session.state == "AWAITING_HUMAN_INPUT":
        if not human_inputs:
            return CreationResult(
                verdict="AWAITING_HUMAN_INPUT",
                session_id=session.session_id,
                plan=plan,
                rejection_reasons=[
                    (
                        f"Human input required for {item.section} "
                        f"'{item.row_id}' column '{item.column}'"
                    )
                    for item in plan.human_inputs_needed
                ],
            )
        plan = apply_human_inputs(plan, human_inputs, session.contract)
        if plan.human_inputs_needed:
            return CreationResult(
                verdict="AWAITING_HUMAN_INPUT",
                session_id=session.session_id,
                plan=plan,
                rejection_reasons=[
                    (
                        f"Human input still required for {item.section} "
                        f"'{item.row_id}' column '{item.column}'"
                    )
                    for item in plan.human_inputs_needed
                ],
            )

    plan_issues = validate_plan(plan, session.contract)
    if plan_issues:
        return CreationResult(
            verdict="REJECTED",
            session_id=session.session_id,
            plan=plan,
            rejection_reasons=[issue.message for issue in plan_issues],
        )

    required_approvals = {
        op.op_id
        for op in plan.operations
        if op.op_type in {"ADD_ROW", "ADD_COLUMN"}
    }
    approved = approvals or set()
    missing_approvals = required_approvals - approved
    if missing_approvals:
        return CreationResult(
            verdict="REJECTED",
            session_id=session.session_id,
            plan=plan,
            rejection_reasons=[
                f"Operation '{op_id}' was not approved"
                for op_id in sorted(missing_approvals)
            ],
        )

    old = parse_file(session.old_text, session.contract)
    merge_result = apply_plan(plan, old, session.contract)
    merged_text = serialize_merged(merge_result.merged_sections, session.contract)

    rereview = rereview_merged(
        merged_text,
        session.old_text,
        session.contract,
        plan,
    )

    if not rereview.passed:
        return CreationResult(
            verdict="REJECTED",
            session_id=session.session_id,
            plan=plan,
            rereview=rereview,
            merged_text=None,
            changelog=merge_result.changelog,
            rejection_reasons=rereview.rejection_reasons,
        )

    snapshot_path = save_creation_snapshot(
        session_id=session.session_id,
        old_text=session.old_text,
        merged_text=merged_text,
        changelog=merge_result.changelog,
        contract=session.contract,
        rereview=rereview,
        root=snapshot_root,
    )

    return CreationResult(
        verdict="ACCEPTED",
        session_id=session.session_id,
        plan=plan,
        rereview=rereview,
        merged_text=merged_text,
        changelog=merge_result.changelog,
        snapshot_path=snapshot_path,
    )


def save_creation_snapshot(
    session_id: str,
    old_text: str,
    merged_text: str,
    changelog: list[ChangelogEntry],
    contract: SchemaContract,
    rereview: RereviewReport,
    root: str | Path = DEFAULT_CREATION_SNAPSHOT_ROOT,
) -> Path:
    """Persist baseline, merged output, changelog, and re-review report."""

    snapshot_dir = Path(root) / session_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    (snapshot_dir / "old.txt").write_text(old_text, encoding="utf-8")
    (snapshot_dir / "merged.txt").write_text(merged_text, encoding="utf-8")
    (snapshot_dir / "changelog.json").write_text(
        json.dumps([_changelog_to_dict(entry) for entry in changelog], indent=2),
        encoding="utf-8",
    )
    (snapshot_dir / "rereview.json").write_text(
        json.dumps(_rereview_to_dict(rereview), indent=2),
        encoding="utf-8",
    )
    meta = {
        "session_id": session_id,
        "contract_name": contract.contract_name,
        "contract_version": contract.version,
        "verdict": rereview.verdict,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (snapshot_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return snapshot_dir


def _changelog_to_dict(entry: ChangelogEntry) -> dict:
    return {
        "op_id": entry.op_id,
        "section": entry.section,
        "target_id": entry.target_id,
        "action": entry.action,
        "field_provenance": entry.field_provenance,
        "reason": entry.reason,
    }


def _rereview_to_dict(report: RereviewReport) -> dict:
    return {
        "passed": report.passed,
        "verdict": report.verdict,
        "rejection_reasons": report.rejection_reasons,
        "integrity_violations": [
            {
                "section": item.section,
                "row_id": item.row_id,
                "violation_type": item.violation_type,
                "message": item.message,
            }
            for item in report.integrity_violations
        ],
        "unexpected_mutations": [
            {
                "section": item.section,
                "row_id": item.row_id,
                "change_type": item.change_type,
                "message": item.message,
                "changed_fields": item.changed_fields,
            }
            for item in report.unexpected_mutations
        ],
        "orphan_rows": [
            {
                "section": item.section,
                "row_id": item.row_id,
                "message": item.message,
            }
            for item in report.orphan_rows
        ],
    }
