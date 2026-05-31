"""Tests for human input collection and merge plan application."""

from __future__ import annotations

from pathlib import Path

import pytest

from schema.contract_loader import load_contract
from parser.generic_parser import parse_file
from creation.gap_analyzer import analyze_gaps
from creation.input_collector import HumanInputValidationError, apply_human_inputs
from creation.merge_applier import apply_plan, serialize_merged
from creation.merge_planner import build_plan


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


def base_old():
    return {
        "clusters": [cluster("1")],
        "nodes": [node("1")],
        "interfaces": [iface("1", "1")],
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


# --- apply adds new rows ----------------------------------------------------


def test_apply_plan_adds_missing_rows(contract):
    old = base_old()
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="host-b")],
        "interfaces": [iface("1", "1"), iface("2", "2", ip="10.0.0.2")],
    }

    report = analyze_gaps(old, new, contract)
    plan = build_plan(report, old, new, contract)
    result = apply_plan(plan, old, contract)

    node_ids = {row["node_id"] for row in result.merged_sections["nodes"]}
    iface_ids = {row["interface_id"] for row in result.merged_sections["interfaces"]}

    assert node_ids == {"1", "2"}
    assert iface_ids == {"1", "2"}
    assert any(entry.action == "ADD_ROW" for entry in result.changelog)


# --- idempotency ------------------------------------------------------------


def test_reapply_is_identical_without_duplicates(contract):
    old = base_old()
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="host-b")],
        "interfaces": [iface("1", "1"), iface("2", "2", ip="10.0.0.2")],
    }

    report = analyze_gaps(old, new, contract)
    plan = build_plan(report, old, new, contract)

    first = apply_plan(plan, old, contract)
    second = apply_plan(plan, old, contract)

    assert first.merged_sections == second.merged_sections
    assert len(first.merged_sections["nodes"]) == 2
    assert len(first.merged_sections["interfaces"]) == 2
    assert len(second.merged_sections["nodes"]) == 2

    # Applying again to the already-merged baseline skips every ADD_ROW.
    third = apply_plan(plan, first.merged_sections, contract)
    assert third.merged_sections == first.merged_sections
    assert third.applied_ops == []
    assert not any(entry.action == "ADD_ROW" for entry in third.changelog)


# --- serialize round-trip ---------------------------------------------------


def test_serialize_round_trips(contract):
    old = base_old()
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="host-b")],
        "interfaces": [iface("1", "1"), iface("2", "2", ip="10.0.0.2")],
    }

    report = analyze_gaps(old, new, contract)
    plan = build_plan(report, old, new, contract)
    merged = apply_plan(plan, old, contract).merged_sections

    text = serialize_merged(merged, contract)
    reparsed = parse_file(text, contract)

    assert reparsed == merged


def test_serialize_matches_contract_layout(contract):
    old = base_old()
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="host-b")],
        "interfaces": [iface("1", "1"), iface("2", "2", ip="10.0.0.2")],
    }

    report = analyze_gaps(old, new, contract)
    plan = build_plan(report, old, new, contract)
    merged = apply_plan(plan, old, contract).merged_sections
    text = serialize_merged(merged, contract)

    assert text.startswith(",cluster_id,cluster_name,tier\nstart_clusters\n")
    assert ",2,host-b,1,true\n" in text
    assert ",2,2,10.0.0.2,8080\n" in text


# --- human-supplied values --------------------------------------------------


def test_human_supplied_ip_in_changelog(contract):
    old = base_old()
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="host-b")],
        "interfaces": [iface("1", "1"), iface("2", "2", ip="")],
    }

    report = analyze_gaps(old, new, contract)
    plan = build_plan(report, old, new, contract)
    assert plan.human_inputs_needed

    updated = apply_human_inputs(
        plan,
        {
            "add-row-interfaces-2": {
                "interface_id": "2",
                "node_id": "2",
                "ip_address": "10.0.0.99",
                "listen_port": "8080",
            }
        },
        contract,
    )
    assert updated.human_inputs_needed == []

    result = apply_plan(updated, old, contract)
    iface_row = next(
        row for row in result.merged_sections["interfaces"] if row["interface_id"] == "2"
    )
    assert iface_row["ip_address"] == "10.0.0.99"

    add_entry = next(
        entry
        for entry in result.changelog
        if entry.action == "ADD_ROW"
        and entry.section == "interfaces"
        and entry.target_id == "2"
    )
    assert add_entry.field_provenance["ip_address"] == "human_supplied"
    assert add_entry.field_provenance["node_id"] == "from_new_file"


def test_invalid_human_input_is_rejected(contract):
    old = base_old()
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="host-b")],
        "interfaces": [iface("1", "1"), iface("2", "2", ip="")],
    }

    report = analyze_gaps(old, new, contract)
    plan = build_plan(report, old, new, contract)

    with pytest.raises(HumanInputValidationError, match="valid IP"):
        apply_human_inputs(
            plan,
            {
                "add-row-interfaces-2": {
                    "interface_id": "2",
                    "node_id": "2",
                    "ip_address": "not-an-ip",
                    "listen_port": "8080",
                }
            },
            contract,
        )
