"""Tests for the creation pipeline and deterministic re-review."""

from __future__ import annotations

from pathlib import Path

import pytest

from parser.generic_parser import parse_file
from schema.contract_loader import load_contract
from creation.creation_pipeline import finalize_creation, run_creation
from creation.merge_applier import serialize_merged
from creation.rereview import rereview_merged


EXAMPLE_CONTRACT = (
    Path(__file__).resolve().parent.parent / "schemas" / "example_contract.yaml"
)

CLUSTER_COLS = ["cluster_id", "cluster_name", "tier"]
NODE_COLS = ["node_id", "hostname", "cluster_ref", "enabled"]
IFACE_COLS = ["interface_id", "node_id", "ip_address", "listen_port"]


@pytest.fixture
def contract():
    return load_contract(EXAMPLE_CONTRACT)


def cluster(cid, name="prod", tier="gold"):
    return {"cluster_id": cid, "cluster_name": name, "tier": tier}


def node(nid, host="host", ref="1", enabled="true"):
    return {"node_id": nid, "hostname": host, "cluster_ref": ref, "enabled": enabled}


def iface(iid, nid="1", ip="10.0.0.1", port="8080"):
    return {
        "interface_id": iid,
        "node_id": nid,
        "ip_address": ip,
        "listen_port": port,
    }


def render(sections: list[tuple[str, list[str], list[dict]]]) -> str:
    lines: list[str] = []
    for name, columns, rows in sections:
        lines.append("," + ",".join(columns))
        lines.append(f"start_{name}")
        for row in rows:
            lines.append("," + ",".join(str(row[col]) for col in columns))
        lines.append(f"end_{name}")
    return "\n".join(lines) + "\n"


def base_old_text():
    return render(
        [
            ("clusters", CLUSTER_COLS, [cluster("1")]),
            ("nodes", NODE_COLS, [node("1", host="host-a")]),
            ("interfaces", IFACE_COLS, [iface("1", "1")]),
        ]
    )


def expansion_new_text():
    return render(
        [
            ("clusters", CLUSTER_COLS, [cluster("1")]),
            (
                "nodes",
                NODE_COLS,
                [node("1", host="host-a"), node("2", host="host-b")],
            ),
            (
                "interfaces",
                IFACE_COLS,
                [iface("1", "1"), iface("2", "2", ip="10.0.0.2")],
            ),
        ]
    )


def _required_approvals(plan):
    return {
        op.op_id
        for op in plan.operations
        if op.op_type in {"ADD_ROW", "ADD_COLUMN"}
    }


# --- happy path -------------------------------------------------------------


def test_happy_path_accepted(contract, tmp_path):
    session = run_creation(base_old_text(), expansion_new_text(), contract)

    assert session.state == "AWAITING_APPROVAL"
    assert session.plan_issues == []

    result = finalize_creation(
        session,
        approvals=_required_approvals(session.plan),
        snapshot_root=tmp_path,
    )

    assert result.verdict == "ACCEPTED"
    assert result.merged_text is not None
    assert result.rereview is not None
    assert result.rereview.passed is True
    assert result.snapshot_path is not None
    assert (result.snapshot_path / "merged.txt").is_file()

    merged = parse_file(result.merged_text, contract)
    node_ids = {row["node_id"] for row in merged["nodes"]}
    assert node_ids == {"1", "2"}


# --- injected FK break ------------------------------------------------------


def test_injected_fk_break_rejected_no_file(contract, tmp_path):
    session = run_creation(base_old_text(), expansion_new_text(), contract)
    result = finalize_creation(
        session,
        approvals=_required_approvals(session.plan),
        snapshot_root=tmp_path,
    )
    assert result.verdict == "ACCEPTED"

    # Tamper merged output: interface references a non-existent node.
    merged = parse_file(result.merged_text, contract)
    merged["interfaces"].append(
        {
            "interface_id": "99",
            "node_id": "999",
            "ip_address": "10.0.0.99",
            "listen_port": "8099",
        }
    )
    bad_text = serialize_merged(merged, contract)

    report = rereview_merged(
        bad_text,
        base_old_text(),
        contract,
        session.plan,
    )

    assert report.verdict == "REJECTED"
    assert report.integrity_violations
    assert not report.passed

    # Pipeline must not emit a file when re-review fails.
    reject_session = run_creation(base_old_text(), expansion_new_text(), contract)
    reject_result = finalize_creation(
        reject_session,
        approvals=_required_approvals(reject_session.plan),
        snapshot_root=tmp_path / "reject",
    )
    tampered = parse_file(reject_result.merged_text, contract)
    tampered["interfaces"].append(
        {
            "interface_id": "99",
            "node_id": "999",
            "ip_address": "10.0.0.99",
            "listen_port": "8099",
        }
    )
    tampered_report = rereview_merged(
        serialize_merged(tampered, contract),
        base_old_text(),
        contract,
        reject_session.plan,
    )
    assert tampered_report.verdict == "REJECTED"


# --- unexpected extra row ---------------------------------------------------


def test_injected_extra_row_is_unexpected_mutation(contract):
    session = run_creation(base_old_text(), expansion_new_text(), contract)
    merged = parse_file(expansion_new_text(), contract)
    # Extra node not in the approved plan.
    merged["nodes"].append(node("99", host="rogue"))
    bad_text = serialize_merged(merged, contract)

    report = rereview_merged(
        bad_text,
        base_old_text(),
        contract,
        session.plan,
    )

    assert report.verdict == "REJECTED"
    assert any(
        m.change_type == "ADDED" and m.row_id == "99"
        for m in report.unexpected_mutations
    )


# --- missing human input halts pipeline -------------------------------------


def test_missing_human_input_halts_without_file(contract, tmp_path):
    new_text = render(
        [
            ("clusters", CLUSTER_COLS, [cluster("1")]),
            (
                "nodes",
                NODE_COLS,
                [node("1", host="host-a"), node("2", host="host-b")],
            ),
            (
                "interfaces",
                IFACE_COLS,
                [iface("1", "1"), iface("2", "2", ip="")],
            ),
        ]
    )

    session = run_creation(base_old_text(), new_text, contract)

    assert session.state == "AWAITING_HUMAN_INPUT"

    result = finalize_creation(session, snapshot_root=tmp_path)

    assert result.verdict == "AWAITING_HUMAN_INPUT"
    assert result.merged_text is None
    assert result.snapshot_path is None
