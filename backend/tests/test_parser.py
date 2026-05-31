"""Tests for the generic parser, schema comparator, diff engine, and integrity checker.

All tests are driven by ``schemas/example_contract.yaml`` so that we exercise
the contract-driven behavior end to end without hardcoding layout in the engine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from schema.contract_loader import load_contract
from parser.generic_parser import parse_file
from parser.schema_comparator import compare_schemas
from parser.diff_engine import diff_sections
from parser.integrity_checker import check_integrity


EXAMPLE_CONTRACT = (
    Path(__file__).resolve().parent.parent / "schemas" / "example_contract.yaml"
)


@pytest.fixture
def contract():
    return load_contract(EXAMPLE_CONTRACT)


# A marker-delimited, leading-empty-field, header-before-start file matching the
# example contract's file_format.
MULTI_SECTION_FILE = """\
,cluster_id,cluster_name,tier
start_clusters
,1,prod,gold
,2,dev,silver
end_clusters
,node_id,hostname,cluster_ref,enabled
start_nodes
,1,host-a,1,true
,2,host-b,2,false
end_nodes
,interface_id,node_id,ip_address,listen_port
start_interfaces
,1,1,10.0.0.1,8080
,2,2,10.0.0.2,9090
end_interfaces
"""


def test_parse_multi_section(contract):
    sections = parse_file(MULTI_SECTION_FILE, contract)

    assert set(sections) == {"clusters", "nodes", "interfaces"}
    assert len(sections["clusters"]) == 2
    assert len(sections["nodes"]) == 2
    assert len(sections["interfaces"]) == 2

    # Rows are keyed by the contract column names (not positional indices).
    assert sections["nodes"][0] == {
        "node_id": "1",
        "hostname": "host-a",
        "cluster_ref": "1",
        "enabled": "true",
    }
    assert sections["clusters"][1]["tier"] == "silver"
    assert sections["interfaces"][1]["ip_address"] == "10.0.0.2"


def test_parse_flat_single_table(contract):
    # A flat file has no section markers; the section name comes from the file
    # stem. Use a contract variant with markers/leading-empty disabled.
    flat_format = contract.file_format.model_copy(
        update={"has_section_markers": False, "leading_empty_field": False}
    )
    flat_contract = contract.model_copy(update={"file_format": flat_format})

    flat_text = """\
node_id,hostname,cluster_ref,enabled
1,host-a,1,true
2,host-b,2,false
"""
    sections = parse_file(flat_text, flat_contract, filename="nodes.cfg")

    assert set(sections) == {"nodes"}
    assert len(sections["nodes"]) == 2
    assert sections["nodes"][0]["hostname"] == "host-a"
    assert sections["nodes"][1]["cluster_ref"] == "2"


def test_column_added_does_not_create_false_modified(contract):
    base = {"nodes": [{"node_id": "1", "hostname": "host-a"}]}
    new = {"nodes": [{"node_id": "1", "hostname": "host-a", "enabled": "true"}]}

    findings = diff_sections(base, new, contract)
    node = next(f for f in findings if f.row_id == "1")

    # The shared columns are identical; the added column must not count as a mod.
    assert node.change_type == "IDENTICAL"
    assert node.changed_fields == []

    change_types = {(c.change_type, c.column_name) for c in node.schema_changes}
    assert ("COLUMN_ADDED", "enabled") in change_types


def test_column_removed_is_flagged(contract):
    base = {"nodes": [{"node_id": "1", "hostname": "host-a", "enabled": "true"}]}
    new = {"nodes": [{"node_id": "1", "hostname": "host-a"}]}

    findings = diff_sections(base, new, contract)
    node = next(f for f in findings if f.row_id == "1")

    # A removed column is not a value modification either.
    assert node.change_type == "IDENTICAL"

    schema_changes = compare_schemas(base, new, contract)
    removed = [
        c for c in schema_changes
        if c.change_type == "COLUMN_REMOVED" and c.column_name == "enabled"
    ]
    assert len(removed) == 1
    assert removed[0].base_index == 2
    assert removed[0].new_index is None


def test_reordered_columns_same_values_are_identical(contract):
    base = {"nodes": [{"node_id": "1", "hostname": "host-a", "cluster_ref": "1"}]}
    new = {"nodes": [{"node_id": "1", "cluster_ref": "1", "hostname": "host-a"}]}

    findings = diff_sections(base, new, contract)
    node = next(f for f in findings if f.row_id == "1")

    assert node.change_type == "IDENTICAL"
    assert any(c.change_type == "COLUMN_REORDERED" for c in node.schema_changes)


def test_modified_when_shared_value_differs(contract):
    base = {"nodes": [{"node_id": "1", "hostname": "host-a"}]}
    new = {"nodes": [{"node_id": "1", "hostname": "host-z"}]}

    findings = diff_sections(base, new, contract)
    node = next(f for f in findings if f.row_id == "1")

    assert node.change_type == "MODIFIED"
    assert node.changed_fields == ["hostname"]


def test_fk_violation_detected(contract):
    sections = {
        "clusters": [{"cluster_id": "1", "cluster_name": "prod", "tier": "gold"}],
        "nodes": [
            {"node_id": "1", "hostname": "a", "cluster_ref": "1", "enabled": "true"},
            # cluster_ref 99 does not exist in clusters -> FK violation.
            {"node_id": "2", "hostname": "b", "cluster_ref": "99", "enabled": "true"},
        ],
        "interfaces": [
            {"interface_id": "1", "node_id": "1", "ip_address": "10.0.0.1", "listen_port": "80"},
            {"interface_id": "2", "node_id": "2", "ip_address": "10.0.0.2", "listen_port": "80"},
        ],
    }

    violations = check_integrity(sections, contract)
    fk = [v for v in violations if v.violation_type == "FK_VIOLATION"]

    assert any(v.section == "nodes" and v.row_id == "2" for v in fk)
    assert not any(v.row_id == "1" for v in fk)


def test_companion_violation_detected(contract):
    sections = {
        "clusters": [{"cluster_id": "1", "cluster_name": "prod", "tier": "gold"}],
        "nodes": [
            {"node_id": "1", "hostname": "a", "cluster_ref": "1", "enabled": "true"},
            # node 2 has no companion interface -> companion violation.
            {"node_id": "2", "hostname": "b", "cluster_ref": "1", "enabled": "true"},
        ],
        "interfaces": [
            {"interface_id": "1", "node_id": "1", "ip_address": "10.0.0.1", "listen_port": "80"},
        ],
    }

    violations = check_integrity(sections, contract)
    companion = [v for v in violations if v.violation_type == "COMPANION_VIOLATION"]

    assert any(v.section == "nodes" and v.row_id == "2" for v in companion)
    assert not any(v.row_id == "1" for v in companion)
