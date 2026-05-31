"""Tests for relational gap analysis and deterministic id allocation."""

from __future__ import annotations

from pathlib import Path

import pytest

from schema.contract_loader import load_contract
from creation.gap_analyzer import analyze_gaps
from creation.id_allocator import NeedsHumanInput, allocate_id


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


# --- (a) missing rows -------------------------------------------------------


def test_missing_node_detected(contract):
    old = base_old()
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="host-b")],
        "interfaces": [iface("1", "1"), iface("2", "2", ip="10.0.0.2")],
    }

    report = analyze_gaps(old, new, contract)
    missing = [m for m in report.missing_rows if m.section == "nodes"]

    assert any(m.row_id == "2" for m in missing)
    found = next(m for m in missing if m.row_id == "2")
    assert found.source_values["hostname"] == "host-b"


# --- (b) companion completeness ---------------------------------------------


def test_missing_companion_is_completeness_requirement(contract):
    old = base_old()
    # node 2 is added but has no companion interface anywhere.
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="host-b")],
        "interfaces": [iface("1", "1")],
    }

    report = analyze_gaps(old, new, contract)
    req = [
        r
        for r in report.completeness_requirements
        if r.section == "interfaces" and r.triggered_by == "nodes#2"
    ]

    assert len(req) == 1
    assert req[0].satisfied is False


def test_satisfied_companion_marked_satisfied(contract):
    old = base_old()
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="host-b")],
        # node 2 DOES have a companion interface (node_id 2).
        "interfaces": [iface("1", "1"), iface("2", "2", ip="10.0.0.2")],
    }

    report = analyze_gaps(old, new, contract)
    req = [
        r
        for r in report.completeness_requirements
        if r.section == "interfaces" and r.triggered_by == "nodes#2"
    ]

    assert len(req) == 1
    assert req[0].satisfied is True


# --- (c) foreign-key resolution ---------------------------------------------


def test_fk_resolves_to_existing_no_gap(contract):
    old = base_old()
    # New interface references node 1, which already exists in old.
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1")],
        "interfaces": [iface("1", "1"), iface("5", "1", ip="10.0.0.5", port="8085")],
    }

    report = analyze_gaps(old, new, contract)

    # The interface row is missing, but its FK resolves and interfaces have no
    # companions, so there is no completeness/broken-reference gap.
    assert any(m.row_id == "5" for m in report.missing_rows)
    assert report.completeness_requirements == []


def test_fk_target_nowhere_is_broken_reference(contract):
    old = base_old()
    # New interface references node 999, which exists nowhere.
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1")],
        "interfaces": [iface("1", "1"), iface("5", "999", ip="10.0.0.5")],
    }

    report = analyze_gaps(old, new, contract)
    broken = [
        r
        for r in report.completeness_requirements
        if r.section == "nodes" and not r.satisfied and "broken" in r.reason.lower()
    ]

    assert any(r.triggered_by == "interfaces#5" for r in broken)


# --- (d) required columns / human input -------------------------------------


def test_required_column_empty_needs_human_input(contract):
    old = base_old()
    # node 2 added but hostname (required, no default) is empty.
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1"), node("2", host="")],
        "interfaces": [iface("1", "1"), iface("2", "2", ip="10.0.0.2")],
    }

    report = analyze_gaps(old, new, contract)
    items = [
        h
        for h in report.human_input_required
        if h.section == "nodes" and h.row_id == "2" and h.column == "hostname"
    ]

    assert len(items) == 1
    assert items[0].data_type == "string"


# --- (e) missing columns ----------------------------------------------------


def test_new_column_flagged_as_missing_column(contract):
    old = base_old()
    new = {
        "clusters": [cluster("1")],
        "nodes": [node("1")],
        "interfaces": [{**iface("1", "1"), "vlan": "100"}],
    }

    report = analyze_gaps(old, new, contract)
    cols = [c for c in report.missing_columns if c.column_name == "vlan"]

    assert len(cols) == 1
    assert cols[0].section == "interfaces"
    assert cols[0].appears_in == "new"
    # 'vlan' isn't declared in the contract, so no default is available.
    assert cols[0].default_available is False


# --- id allocation ----------------------------------------------------------


def test_sequential_int_increments(contract):
    assert allocate_id("nodes", contract, ["1", "2", "3"], ["4"]) == "5"
    assert allocate_id("nodes", contract, [], []) == "1"


def test_numeric_suffix_increments(contract):
    ns_section = contract.sections[1].model_copy(
        update={"id_naming_rule": "numeric_suffix"}
    )
    ns_contract = contract.model_copy(
        update={
            "sections": [contract.sections[0], ns_section, contract.sections[2]]
        }
    )
    assert (
        allocate_id("nodes", ns_contract, ["node37", "node38"], ["node39"])
        == "node40"
    )


def test_opaque_id_raises_needs_human_input(contract):
    opaque_section = contract.sections[1].model_copy(
        update={"id_naming_rule": "opaque"}
    )
    opaque_contract = contract.model_copy(
        update={
            "sections": [contract.sections[0], opaque_section, contract.sections[2]]
        }
    )
    with pytest.raises(NeedsHumanInput):
        allocate_id("nodes", opaque_contract, ["host-a", "host-b"], [])
