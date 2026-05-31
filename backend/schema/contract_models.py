"""Pydantic models that describe a customer's config *schema contract*.

These models are the single source of truth for everything the engine needs to
know about a specific customer's configuration layout. The engine reads
sections, columns, relationships and thresholds *through* these models, so no
literal field/file/table names ever appear in engine logic.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DataType = Literal["string", "int", "ip", "port", "enum", "bool"]


class ColumnDef(BaseModel):
    """A single column within a section.

    ``is_id`` marks the column that uniquely identifies a row within its
    section. ``enum_values`` is only meaningful when ``data_type == "enum"``.
    ``default`` is the contract-supplied value used when the column is missing
    from a source row; ``None`` means no default is available (human input is
    required for a missing required value).
    """

    name: str
    is_id: bool = False
    required: bool = False
    data_type: DataType = "string"
    enum_values: list[str] | None = None
    default: str | None = None


class ForeignKeyRule(BaseModel):
    """Declares that ``column`` in this section points at a row in another section.

    Example: an ``interfaces`` section whose ``node_id`` column references the
    ``node_id`` column of the ``nodes`` section.
    """

    column: str
    references_section: str
    references_column: str


class CompanionRule(BaseModel):
    """Declares that a row in this section must be accompanied by a row elsewhere.

    ``requires_section`` is the section that must also contain a matching row,
    and ``match_on`` is the column whose value is used to correlate the two
    rows (the same column name is expected on both sides).
    """

    requires_section: str
    match_on: str


class SectionDef(BaseModel):
    """A logical grouping of rows that share the same columns.

    A section maps to a delimited block in the config file (for example a
    ``start_<name>`` / ``end_<name>`` marked region). ``description`` carries a
    plain-English meaning that helps the AI map user intent onto the right
    section without the engine hardcoding any names.
    """

    name: str
    description: str = ""
    id_column: str
    id_naming_rule: str = "sequential_int"
    columns: list[ColumnDef]
    foreign_keys: list[ForeignKeyRule] = Field(default_factory=list)
    companions: list[CompanionRule] = Field(default_factory=list)


class FileFormat(BaseModel):
    """Describes how the customer's config file is physically laid out.

    The engine uses this to parse and re-serialize files without assuming any
    particular delimiter, marker convention, or header placement.
    """

    file_pattern: str
    delimiter: str = ","
    has_section_markers: bool = True
    section_start_prefix: str = "start_"
    section_end_prefix: str = "end_"
    header_position: Literal["before_start", "first_row"] = "before_start"
    leading_empty_field: bool = True


class DecisionThresholds(BaseModel):
    """Policy knobs controlling how aggressively the engine acts.

    "Blast radius" is the number of rows/sections a change touches. Small
    changes can be auto-applied; larger ones are only suggested; undeclared
    modifications above a limit are blocked outright.
    """

    auto_apply_max_blast_radius: int = 2
    suggest_min_blast_radius: int = 3
    block_undeclared_modify_blast_radius: int = 2
    allow_auto_apply: bool = True


class SchemaContract(BaseModel):
    """The complete contract for one customer's configuration."""

    contract_name: str
    version: str
    file_format: FileFormat
    sections: list[SectionDef]
    thresholds: DecisionThresholds = Field(default_factory=DecisionThresholds)
