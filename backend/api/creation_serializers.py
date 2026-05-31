"""JSON serializers for creation pipeline API responses."""

from __future__ import annotations

from dataclasses import asdict

from creation.creation_pipeline import CreationResult, CreationSession
from creation.gap_analyzer import GapReport
from creation.merge_applier import ChangelogEntry
from creation.merge_planner import MergePlan
from creation.rereview import RereviewReport


def session_to_dict(session: CreationSession) -> dict:
    return {
        "session_id": session.session_id,
        "state": session.state,
        "contract_name": session.contract.contract_name,
        "contract_version": session.contract.version,
        "gap_report": gap_report_to_dict(session.gap_report),
        "plan": plan_to_dict(session.plan),
        "plan_issues": [asdict(issue) for issue in session.plan_issues],
        "human_inputs_needed": [
            asdict(item) for item in session.plan.human_inputs_needed
        ],
        "blocked": [asdict(item) for item in session.plan.blocked],
    }


def result_to_dict(result: CreationResult, *, download_url: str | None = None) -> dict:
    payload = {
        "verdict": result.verdict,
        "session_id": result.session_id,
        "plan": plan_to_dict(result.plan),
        "rejection_reasons": result.rejection_reasons,
        "changelog": [changelog_to_dict(entry) for entry in result.changelog],
        "rereview": (
            rereview_to_dict(result.rereview) if result.rereview is not None else None
        ),
        "merged_text": result.merged_text,
        "download_url": download_url,
    }
    return payload


def plan_to_dict(plan: MergePlan) -> dict:
    return {
        "plan_id": plan.plan_id,
        "contract_name": plan.contract_name,
        "operations": [asdict(op) for op in plan.operations],
        "blocked": [asdict(item) for item in plan.blocked],
        "human_inputs_needed": [asdict(item) for item in plan.human_inputs_needed],
    }


def gap_report_to_dict(report: GapReport) -> dict:
    return asdict(report)


def changelog_to_dict(entry: ChangelogEntry) -> dict:
    return asdict(entry)


def rereview_to_dict(report: RereviewReport) -> dict:
    return {
        "passed": report.passed,
        "verdict": report.verdict,
        "rejection_reasons": report.rejection_reasons,
        "integrity_violations": [asdict(v) for v in report.integrity_violations],
        "unexpected_mutations": [asdict(m) for m in report.unexpected_mutations],
        "orphan_rows": [asdict(o) for o in report.orphan_rows],
    }
