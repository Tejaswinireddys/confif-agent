#!/usr/bin/env python3
"""Headless command-line interface for the config reconciler.

Examples
--------
    python cli.py reconcile --contract NAME --base old.cfg --new new.cfg
    python cli.py reconcile --contract NAME --base old.cfg --new new.cfg --diff change.diff
    python cli.py validate-contract --file schemas/example_contract.yaml
    python cli.py list-contracts
    python cli.py create --contract NAME --old old.cfg --new new.cfg --out merged.cfg
    python cli.py create --contract NAME --old old.cfg --new new.cfg --inputs inputs.json --out merged.cfg
    python cli.py explain-plan --contract NAME --old old.cfg --new new.cfg

The ``reconcile`` command exits non-zero if any finding is BLOCK, so it can gate
a CI/CD pipeline. ``validate-contract`` exits non-zero on errors or warnings.

``create`` exit codes:
    0 — re-review ACCEPTED, merged file written
    1 — blocked or re-review REJECTED
    2 — human inputs required (prints required inputs JSON for CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

# Allow running as `python backend/cli.py ...` from any directory.
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from schema.contract_loader import load_contract, validate_contract  # noqa: E402
from agent.reconciler import BLOCK, Reconciler  # noqa: E402
from agent.snapshot import SnapshotError, save_snapshot  # noqa: E402
from api import contract_store  # noqa: E402
from intent.ai_extractor import (  # noqa: E402
    AIExtractionError,
    AIExtractor,
    IntentSummary,
)
from intent.diff_reader import extract_csv_changes, parse_git_diff  # noqa: E402
from intent.jira_reader import (  # noqa: E402
    JiraConfigError,
    JiraFetchError,
    JiraReader,
    extract_raw_text,
)
from creation.creation_pipeline import finalize_creation, run_creation  # noqa: E402
from creation.input_collector import (  # noqa: E402
    HumanInputValidationError,
    apply_human_inputs,
    validate_column_value,
)
from creation.merge_planner import MergePlan, _op_id  # noqa: E402
from schema.contract_loader import get_section  # noqa: E402
from schema.contract_models import SchemaContract  # noqa: E402


class CLIError(Exception):
    """User-facing CLI error."""


def _load_registered_contract(name: str) -> SchemaContract:
    path = contract_store.get_contract(
        name,
        root=contract_store.DEFAULT_CONTRACTS_DIR,
    )
    if path is None:
        raise CLIError(f"no contract registered under name '{name}'")
    try:
        return load_contract(path)
    except Exception as exc:  # noqa: BLE001
        raise CLIError(f"stored contract is invalid: {exc}") from exc


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _print_report(report) -> None:
    summary = report.summary
    decisions = summary.get("decisions", {})

    print("=" * 70)
    print(f"Deployment : {report.deployment_id}")
    print(f"Contract   : {report.contract_name} v{report.contract_version}")
    print("-" * 70)
    print(
        "Decisions  : "
        f"AUTO_APPLY={decisions.get('AUTO_APPLY', 0)}  "
        f"SUGGEST={decisions.get('SUGGEST', 0)}  "
        f"ESCALATE={decisions.get('ESCALATE', 0)}  "
        f"BLOCK={decisions.get('BLOCK', 0)}"
    )
    print(
        f"Schema chg : {summary.get('schema_changes', 0)}   "
        f"Integrity violations: {summary.get('integrity_violations', 0)}"
    )
    print("=" * 70)

    if report.findings:
        print("\nFindings:")
        for finding in report.findings:
            row = f"#{finding.row_id}" if finding.row_id is not None else "-"
            print(
                f"  [{finding.decision:<10}] {finding.section}/{finding.change_type} "
                f"{row}  (blast={finding.blast_radius})"
            )
            print(f"      {finding.reason}")

    if report.integrity_violations:
        print("\nIntegrity violations (always blocked):")
        for violation in report.integrity_violations:
            row = f"#{violation.row_id}" if violation.row_id is not None else "-"
            print(
                f"  [{violation.violation_type}] {violation.section} {row}: "
                f"{violation.message}"
            )

    blocked = [f for f in report.findings if f.decision == BLOCK]
    print("\n" + "-" * 70)
    if blocked:
        print(f"RESULT: BLOCKED ({len(blocked)} blocking finding(s)).")
    else:
        print("RESULT: OK (no blocking findings).")
    print("-" * 70)


def cmd_reconcile(args: argparse.Namespace) -> int:
    path = contract_store.get_contract(args.contract)
    if path is None:
        print(f"error: no contract registered under name '{args.contract}'", file=sys.stderr)
        return 2

    try:
        contract = load_contract(path)
    except Exception as exc:  # noqa: BLE001
        print(f"error: stored contract is invalid: {exc}", file=sys.stderr)
        return 2

    try:
        base_text = _read(args.base)
        new_text = _read(args.new)
    except OSError as exc:
        print(f"error: could not read config file: {exc}", file=sys.stderr)
        return 2

    diff_hunks = []
    declared_changes = []
    if args.diff:
        try:
            diff_hunks = parse_git_diff(_read(args.diff))
            declared_changes = extract_csv_changes(diff_hunks, contract)
        except OSError as exc:
            print(f"error: could not read diff file: {exc}", file=sys.stderr)
            return 2

    intent = IntentSummary()
    if args.jira:
        try:
            ticket = JiraReader().fetch_ticket(args.jira)
            jira_text = extract_raw_text(ticket)
        except (JiraConfigError, JiraFetchError) as exc:
            print(f"error: jira fetch failed: {exc}", file=sys.stderr)
            return 2
        try:
            intent = AIExtractor().extract_intent(jira_text, diff_hunks, contract)
        except AIExtractionError as exc:
            print(f"error: AI intent extraction failed: {exc}", file=sys.stderr)
            return 2

    report = Reconciler().reconcile(
        base_text, new_text, intent, declared_changes, contract
    )

    try:
        save_snapshot(report, base_text)
    except SnapshotError as exc:
        print(f"warning: could not persist snapshot: {exc}", file=sys.stderr)

    _print_report(report)

    blocked = any(f.decision == BLOCK for f in report.findings)
    return 1 if blocked else 0


def cmd_validate_contract(args: argparse.Namespace) -> int:
    try:
        contract = load_contract(args.file)
    except Exception as exc:  # noqa: BLE001
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2

    warnings = validate_contract(contract)
    print(f"Contract: {contract.contract_name} v{contract.version}")
    print(f"Sections: {len(contract.sections)}")
    if warnings:
        print(f"\n{len(warnings)} validation warning(s):")
        for warning in warnings:
            print(f"  - {warning}")
        return 1
    print("\nNo validation warnings. Contract is internally consistent.")
    return 0


def cmd_list_contracts(_: argparse.Namespace) -> int:
    contracts = contract_store.list_contracts()
    if not contracts:
        print("No contracts registered.")
        return 0
    print(f"{'NAME':<32} {'VERSION':<10} SECTIONS")
    print("-" * 54)
    for item in contracts:
        print(f"{item['name']:<32} {item['version']:<10} {item['section_count']}")
    return 0


def _load_intent(
    args: argparse.Namespace,
    contract: SchemaContract,
) -> tuple[object | None, object | None]:
    diff_hunks = []
    diff_changes = None
    jira_intent = None

    if getattr(args, "diff", None):
        diff_hunks = parse_git_diff(_read(args.diff))
        diff_changes = extract_csv_changes(diff_hunks, contract)

    if getattr(args, "jira", None):
        try:
            ticket = JiraReader().fetch_ticket(args.jira)
            jira_text = extract_raw_text(ticket)
        except (JiraConfigError, JiraFetchError) as exc:
            raise CLIError(f"jira fetch failed: {exc}") from exc
        try:
            jira_intent = AIExtractor().extract_intent(jira_text, diff_hunks, contract)
        except AIExtractionError as exc:
            raise CLIError(f"AI intent extraction failed: {exc}") from exc

    return jira_intent, diff_changes


def _add_row_op_id(section: str, row_id: str | None) -> str:
    return _op_id("add-row", section, row_id)


def _build_inputs_template(session) -> dict[str, dict[str, str]]:
    template: dict[str, dict[str, str]] = {}
    missing_by_key = {
        (row.section, row.row_id): row for row in session.gap_report.missing_rows
    }

    seen_ops: set[str] = set()
    for item in session.plan.human_inputs_needed:
        op_id = _add_row_op_id(item.section, item.row_id)
        if op_id in seen_ops:
            continue
        seen_ops.add(op_id)
        missing = missing_by_key.get((item.section, item.row_id))
        source = dict(missing.source_values) if missing else {}
        for field_item in session.plan.human_inputs_needed:
            if field_item.section != item.section or field_item.row_id != item.row_id:
                continue
            source.setdefault(field_item.column, "")
        template[op_id] = {key: str(value) for key, value in source.items()}

    return template


def _required_inputs_payload(session) -> dict:
    return {
        "human_inputs_needed": [
            asdict(item) for item in session.plan.human_inputs_needed
        ],
        "inputs": _build_inputs_template(session),
    }


def _inputs_complete(
    session,
    inputs: dict[str, dict[str, str]],
    contract: SchemaContract,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for item in session.plan.human_inputs_needed:
        op_id = _add_row_op_id(item.section, item.row_id)
        value = inputs.get(op_id, {}).get(item.column, "")
        if not str(value).strip():
            errors.append(f"Missing value for {op_id} field '{item.column}'")
            continue

        section_def = get_section(contract, item.section)
        if section_def is None:
            continue
        coldef = next(
            (column for column in section_def.columns if column.name == item.column),
            None,
        )
        if coldef is None:
            continue
        try:
            validate_column_value(str(value), coldef, item.section, item.column)
        except HumanInputValidationError as exc:
            errors.append(str(exc))

    return not errors, errors


def _enrich_inputs(
    session,
    inputs: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    template = _build_inputs_template(session)
    enriched: dict[str, dict[str, str]] = {}
    for op_id, base in template.items():
        enriched[op_id] = {**base, **inputs.get(op_id, {})}
    for op_id, fields in inputs.items():
        if op_id not in enriched:
            enriched[op_id] = dict(fields)
    return enriched


def _auto_approvals(plan: MergePlan) -> set[str]:
    return {
        op.op_id
        for op in plan.operations
        if op.op_type in {"ADD_ROW", "ADD_COLUMN"}
    }


def _print_merge_plan(session) -> None:
    plan = session.plan
    print("=" * 70)
    print(f"Merge plan : {plan.plan_id}")
    print(f"Contract   : {session.contract.contract_name} v{session.contract.version}")
    print(f"State      : {session.state}")
    print("=" * 70)

    if plan.blocked:
        print("\nBlocked (not applicable):")
        for item in plan.blocked:
            target = f"#{item.target_id}" if item.target_id else "-"
            print(f"  {item.section}{target}")
            print(f"      {item.reason}")

    if plan.human_inputs_needed:
        print("\nHuman input required:")
        for item in plan.human_inputs_needed:
            print(
                f"  {_add_row_op_id(item.section, item.row_id)}."
                f"{item.column} ({item.data_type}): {item.why_needed}"
            )

    grouped: dict[str, list] = {}
    for op in plan.operations:
        grouped.setdefault(op.section, []).append(op)

    for section, ops in grouped.items():
        print(f"\nSection: {section}")
        for op in ops:
            target = f"#{op.target_id}" if op.target_id else "-"
            print(f"  [{op.op_type}] {op.section}{target}  ({op.op_id})")
            print(f"      {op.reason}")
            for field, value in op.values.items():
                prov = op.provenance.get(field, "from_new_file")
                print(f"      {field}: {value}  ({prov})")
            if op.depends_on:
                print(f"      depends_on: {', '.join(op.depends_on)}")

    if session.plan_issues:
        print("\nPlan validation issues:")
        for issue in session.plan_issues:
            print(f"  [{issue.code}] {issue.message}")

    print("\n" + "-" * 70)


def _print_changelog(changelog) -> None:
    if not changelog:
        print("Changelog: (no applied operations)")
        return

    print("\nChangelog:")
    for entry in changelog:
        target = f"#{entry.target_id}" if entry.target_id else "-"
        print(f"  [{entry.action}] {entry.section}{target}  ({entry.op_id})")
        print(f"      {entry.reason}")
        for field, prov in entry.field_provenance.items():
            print(f"      {field}: {prov}")


def _print_rejection(reasons: list[str]) -> None:
    print("\nREJECTED:", file=sys.stderr)
    for reason in reasons:
        print(f"  - {reason}", file=sys.stderr)


def cmd_create(args: argparse.Namespace) -> int:
    try:
        contract = _load_registered_contract(args.contract)
        old_text = _read(args.old)
        new_text = _read(args.new)
        jira_intent, diff_changes = _load_intent(args, contract)
    except CLIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: could not read file: {exc}", file=sys.stderr)
        return 2

    try:
        session = run_creation(
            old_text,
            new_text,
            contract,
            jira_intent=jira_intent,
            diff_changes=diff_changes,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"error: gap analysis failed: {exc}", file=sys.stderr)
        return 2

    if session.state == "BLOCKED":
        _print_rejection([item.reason for item in session.plan.blocked])
        return 1

    human_inputs: dict[str, dict[str, str]] | None = None
    if session.plan.human_inputs_needed:
        if not args.inputs:
            print(json.dumps(_required_inputs_payload(session), indent=2))
            return 2

        try:
            raw = json.loads(Path(args.inputs).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"error: could not read inputs file: {exc}", file=sys.stderr)
            return 2

        if not isinstance(raw, dict):
            print("error: inputs file must be a JSON object", file=sys.stderr)
            return 2

        supplied = raw["inputs"] if isinstance(raw.get("inputs"), dict) else raw
        if not isinstance(supplied, dict):
            print("error: inputs must be a JSON object keyed by op_id", file=sys.stderr)
            return 2

        human_inputs = _enrich_inputs(session, supplied)
        complete, errors = _inputs_complete(session, human_inputs, contract)
        if not complete:
            payload = _required_inputs_payload(session)
            payload["validation_errors"] = errors
            print(json.dumps(payload, indent=2))
            return 2

    working_session = session
    if human_inputs:
        try:
            updated_plan = apply_human_inputs(
                session.plan, human_inputs, contract
            )
        except HumanInputValidationError as exc:
            print(f"error: invalid human input: {exc}", file=sys.stderr)
            return 1
        working_session = replace(
            session,
            plan=updated_plan,
            state=(
                "AWAITING_APPROVAL"
                if not updated_plan.human_inputs_needed
                else "AWAITING_HUMAN_INPUT"
            ),
        )
        if working_session.state == "AWAITING_HUMAN_INPUT":
            print(json.dumps(_required_inputs_payload(working_session), indent=2))
            return 2

    try:
        result = finalize_creation(
            working_session,
            human_inputs=None,
            approvals=_auto_approvals(working_session.plan),
        )
    except HumanInputValidationError as exc:
        print(f"error: invalid human input: {exc}", file=sys.stderr)
        return 1

    if result.verdict == "AWAITING_HUMAN_INPUT":
        print(json.dumps(_required_inputs_payload(working_session), indent=2))
        return 2

    if result.verdict in {"REJECTED", "BLOCKED"}:
        _print_rejection(result.rejection_reasons)
        return 1

    if result.verdict != "ACCEPTED" or not result.merged_text:
        _print_rejection(result.rejection_reasons or ["Unexpected creation result"])
        return 1

    if args.out:
        try:
            Path(args.out).write_text(result.merged_text, encoding="utf-8")
            print(f"Wrote merged config to {args.out}")
        except OSError as exc:
            print(f"error: could not write output file: {exc}", file=sys.stderr)
            return 1
    else:
        print(result.merged_text, end="")

    _print_changelog(result.changelog)
    print("\nRESULT: ACCEPTED")
    return 0


def cmd_explain_plan(args: argparse.Namespace) -> int:
    try:
        contract = _load_registered_contract(args.contract)
        old_text = _read(args.old)
        new_text = _read(args.new)
        jira_intent, diff_changes = _load_intent(args, contract)
    except CLIError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: could not read file: {exc}", file=sys.stderr)
        return 2

    try:
        session = run_creation(
            old_text,
            new_text,
            contract,
            jira_intent=jira_intent,
            diff_changes=diff_changes,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"error: gap analysis failed: {exc}", file=sys.stderr)
        return 2

    _print_merge_plan(session)
    if session.state == "BLOCKED":
        print("RESULT: BLOCKED")
        return 1
    if session.state == "AWAITING_HUMAN_INPUT":
        print("RESULT: AWAITING_HUMAN_INPUT")
        return 2
    print("RESULT: READY FOR APPROVAL")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py", description="Config reconciler command-line interface"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_rec = sub.add_parser("reconcile", help="Reconcile two config versions")
    p_rec.add_argument("--contract", required=True, help="Registered contract name")
    p_rec.add_argument("--base", required=True, help="Path to the base config file")
    p_rec.add_argument("--new", required=True, help="Path to the new config file")
    p_rec.add_argument("--jira", help="Optional Jira ticket ID for intent extraction")
    p_rec.add_argument("--diff", help="Optional path to a unified git diff file")
    p_rec.set_defaults(func=cmd_reconcile)

    p_val = sub.add_parser("validate-contract", help="Validate a contract YAML file")
    p_val.add_argument("--file", required=True, help="Path to the contract YAML")
    p_val.set_defaults(func=cmd_validate_contract)

    p_list = sub.add_parser("list-contracts", help="List registered contracts")
    p_list.set_defaults(func=cmd_list_contracts)

    p_create = sub.add_parser(
        "create",
        help="Run creation pipeline (gap analysis → merge → re-review)",
    )
    p_create.add_argument("--contract", required=True, help="Registered contract name")
    p_create.add_argument("--old", required=True, help="Path to the baseline config file")
    p_create.add_argument("--new", required=True, help="Path to the new config file")
    p_create.add_argument("--jira", help="Optional Jira ticket ID for intent extraction")
    p_create.add_argument("--diff", help="Optional path to a unified git diff file")
    p_create.add_argument(
        "--inputs",
        help="JSON file with human-supplied field values keyed by op_id",
    )
    p_create.add_argument(
        "--out",
        help="Write merged config here on ACCEPTED (stdout if omitted)",
    )
    p_create.set_defaults(func=cmd_create)

    p_explain = sub.add_parser(
        "explain-plan",
        help="Print the merge plan with provenance (no changes applied)",
    )
    p_explain.add_argument("--contract", required=True, help="Registered contract name")
    p_explain.add_argument("--old", required=True, help="Path to the baseline config file")
    p_explain.add_argument("--new", required=True, help="Path to the new config file")
    p_explain.add_argument("--jira", help="Optional Jira ticket ID for intent extraction")
    p_explain.add_argument("--diff", help="Optional path to a unified git diff file")
    p_explain.set_defaults(func=cmd_explain_plan)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
