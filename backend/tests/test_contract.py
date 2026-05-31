"""Tests for the schema contract models and loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from schema.contract_loader import (
    get_id_column,
    get_section,
    load_contract,
    validate_contract,
)
from schema.contract_models import (
    ColumnDef,
    ForeignKeyRule,
    SchemaContract,
    SectionDef,
    FileFormat,
)


EXAMPLE_CONTRACT = (
    Path(__file__).resolve().parent.parent / "schemas" / "example_contract.yaml"
)


def _minimal_sections() -> list[SectionDef]:
    return [
        SectionDef(
            name="clusters",
            id_column="cluster_id",
            columns=[ColumnDef(name="cluster_id", is_id=True, data_type="int")],
        ),
        SectionDef(
            name="nodes",
            id_column="node_id",
            columns=[
                ColumnDef(name="node_id", is_id=True, data_type="int"),
                ColumnDef(name="cluster_ref", data_type="int"),
            ],
            foreign_keys=[
                ForeignKeyRule(
                    column="cluster_ref",
                    references_section="clusters",
                    references_column="cluster_id",
                )
            ],
        ),
    ]


def _make_contract(sections: list[SectionDef]) -> SchemaContract:
    return SchemaContract(
        contract_name="t",
        version="1.0.0",
        file_format=FileFormat(file_pattern="*.cfg"),
        sections=sections,
    )


def test_load_valid_contract():
    contract = load_contract(EXAMPLE_CONTRACT)

    assert contract.contract_name == "example_generic_network"
    assert contract.version == "1.0.0"
    assert {s.name for s in contract.sections} == {"clusters", "nodes", "interfaces"}

    # Custom thresholds from the YAML should be honored (not defaults).
    assert contract.thresholds.auto_apply_max_blast_radius == 3
    assert contract.thresholds.suggest_min_blast_radius == 4

    # A valid contract produces no warnings.
    assert validate_contract(contract) == []


def test_accessors():
    contract = load_contract(EXAMPLE_CONTRACT)

    nodes = get_section(contract, "nodes")
    assert nodes is not None
    assert nodes.id_column == "node_id"

    assert get_section(contract, "does_not_exist") is None
    assert get_id_column(contract, "interfaces") == "interface_id"

    with pytest.raises(KeyError):
        get_id_column(contract, "does_not_exist")


def test_validation_catches_bad_fk_reference():
    sections = _minimal_sections()
    # Point the FK at a section that does not exist.
    sections[1].foreign_keys[0].references_section = "ghost_section"
    contract = _make_contract(sections)

    warnings = validate_contract(contract)
    assert any("missing section 'ghost_section'" in w for w in warnings)


def test_validation_catches_bad_fk_column():
    sections = _minimal_sections()
    # Reference a column that does not exist in the (real) target section.
    sections[1].foreign_keys[0].references_column = "ghost_column"
    contract = _make_contract(sections)

    warnings = validate_contract(contract)
    assert any("missing column 'ghost_column'" in w for w in warnings)


def test_validation_catches_missing_id_column():
    sections = [
        SectionDef(
            name="clusters",
            id_column="not_a_real_column",
            columns=[ColumnDef(name="cluster_id", is_id=True, data_type="int")],
        )
    ]
    contract = _make_contract(sections)

    warnings = validate_contract(contract)
    assert any("id_column 'not_a_real_column'" in w for w in warnings)


def test_validation_catches_duplicate_sections():
    section = SectionDef(
        name="dupe",
        id_column="id",
        columns=[ColumnDef(name="id", is_id=True, data_type="int")],
    )
    contract = _make_contract([section, section.model_copy(deep=True)])

    warnings = validate_contract(contract)
    assert any("Duplicate section name: 'dupe'" in w for w in warnings)


def test_validation_catches_missing_companion_section():
    sections = _minimal_sections()
    nodes = sections[1]
    from schema.contract_models import CompanionRule

    nodes.companions.append(
        CompanionRule(requires_section="ghost", match_on="node_id")
    )
    contract = _make_contract(sections)

    warnings = validate_contract(contract)
    assert any("companion references missing section 'ghost'" in w for w in warnings)
