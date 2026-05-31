"""Tests for merge plan construction and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from schema.contract_loader import load_contract
from creation.gap_analyzer import analyze_gaps
from creation.merge_planner import build_plan
from creation.plan_validator import validate_plan


EXAMPLE_CONTRACT = (
    Path(__file__).resolve().parent.parent / "schemas" / "example_contract.yaml"
)


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


def _add_rows(plan):
    return [op for op in plan.operations if op.op_type == "ADD_ROW"]


def _add_row_index(plan):
    return {op.op_id: i for i, op in enumerate(_add_rows(plan))}


# --- missing node + companion ordering --------------------------------------


def test_missing_node_and_companion_add_rows_ordered(contract):
    old = base_old()
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="host-b")],
        "interfaces": [iface("1", "1"), iface("2", "2", ip="10.0.0.2")],
    }

    report = analyze_gaps(old, new, contract)
    plan = build_plan(report, old, new, contract)

    add_rows = _add_rows(plan)
    sections = [op.section for op in add_rows]
    assert "nodes" in sections
    assert "interfaces" in sections
    assert sections.index("nodes") < sections.index("interfaces")

    node_op = next(op for op in add_rows if op.section == "nodes" and op.target_id == "2")
    iface_op = next(
        op for op in add_rows if op.section == "interfaces" and op.target_id == "2"
    )
    assert node_op.provenance["hostname"] == "from_new_file"
    assert iface_op.provenance["ip_address"] == "from_new_file"
    assert node_op.op_id in iface_op.depends_on

    issues = validate_plan(plan, contract)
    assert issues == []


# --- auto-allocated id ------------------------------------------------------


def test_auto_allocated_id_provenance_is_deterministic(contract):
    old = base_old()
    # Interface row without interface_id — id must be allocated.
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="host-b")],
        "interfaces": [
            iface("1", "1"),
            {"node_id": "2", "ip_address": "10.0.0.2", "listen_port": "8080"},
        ],
    }

    report = analyze_gaps(old, new, contract)
    plan = build_plan(report, old, new, contract)

    alloc_ops = [op for op in plan.operations if op.op_type == "ALLOCATE_ID"]
    assert len(alloc_ops) == 1
    assert alloc_ops[0].provenance["interface_id"] == "auto_allocated"
    assert alloc_ops[0].values["interface_id"] == "2"

    add_rows = _add_rows(plan)
    iface_op = next(op for op in add_rows if op.section == "interfaces")
    assert iface_op.provenance["interface_id"] == "auto_allocated"
    assert alloc_ops[0].op_id in iface_op.depends_on

    # Deterministic across repeated builds.
    plan2 = build_plan(report, old, new, contract)
    assert plan2.plan_id == plan.plan_id
    assert (
        plan2.operations[0].values.get("interface_id")
        == plan.operations[0].values.get("interface_id")
    )


# --- human input defers whole row -------------------------------------------


def test_missing_required_ip_goes_to_human_inputs_not_operations(contract):
    old = base_old()
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="host-b")],
        "interfaces": [iface("1", "1"), iface("2", "2", ip="")],
    }

    report = analyze_gaps(old, new, contract)
    plan = build_plan(report, old, new, contract)

    iface_adds = [
        op for op in _add_rows(plan) if op.section == "interfaces" and op.target_id == "2"
    ]
    assert iface_adds == []

    human = [
        h
        for h in plan.human_inputs_needed
        if h.section == "interfaces" and h.row_id == "2" and h.column == "ip_address"
    ]
    assert len(human) == 1

    issues = validate_plan(plan, contract)
    assert not any(i.code == "HUMAN_INPUT_IN_OPERATIONS" for i in issues)


# --- broken FK blocked ------------------------------------------------------


def test_broken_fk_is_blocked_not_operation(contract):
    old = base_old()
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1")],
        "interfaces": [iface("1", "1"), iface("5", "999", ip="10.0.0.5")],
    }

    report = analyze_gaps(old, new, contract)
    plan = build_plan(report, old, new, contract)

    assert any(b.section == "interfaces" and b.target_id == "5" for b in plan.blocked)
    assert not any(
        op.section == "interfaces" and op.target_id == "5" for op in _add_rows(plan)
    )


# --- parent precedes child --------------------------------------------------


def test_parent_precedes_child_in_plan(contract):
    old = base_old()
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="host-b")],
        "interfaces": [iface("1", "1"), iface("2", "2", ip="10.0.0.2")],
    }

    report = analyze_gaps(old, new, contract)
    plan = build_plan(report, old, new, contract)

    positions = {op.op_id: i for i, op in enumerate(plan.operations)}
    node_op = next(
        op
        for op in plan.operations
        if op.op_type == "ADD_ROW" and op.section == "nodes" and op.target_id == "2"
    )
    iface_op = next(
        op
        for op in plan.operations
        if op.op_type == "ADD_ROW"
        and op.section == "interfaces"
        and op.target_id == "2"
    )

    assert positions[node_op.op_id] < positions[iface_op.op_id]
    assert validate_plan(plan, contract) == []
