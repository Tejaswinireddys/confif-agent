"""Relational gap analysis driven by the schema contract.

This is *not* a textual diff. Given an ``old`` and ``new`` parsed config (each a
``{section: [row_dict, ...]}`` mapping), it reasons about what would be needed to
make ``new`` relationally complete with respect to the contract:

* rows present in ``new`` but absent from ``old`` (candidates to create);
* companion rows that the contract requires but that are missing everywhere;
* foreign keys that resolve to nothing in ``old`` or ``new`` (broken references
  that cannot be safely created);
* required columns that are empty in the source and have no contract default
  (human input needed);
* columns that appear in ``new`` but not ``old`` (with default availability).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schema.contract_models import SchemaContract, SectionDef


@dataclass
class MissingRow:
    section: str
    row_id: str | None
    source_values: dict
    reason: str


@dataclass
class RequiredRow:
    section: str
    reason: str
    triggered_by: str
    satisfied: bool


@dataclass
class MissingColumn:
    section: str
    column_name: str
    appears_in: str  # always "new" here
    default_available: bool


@dataclass
class HumanInputItem:
    section: str
    row_id: str | None
    column: str
    data_type: str
    why_needed: str


@dataclass
class GapReport:
    missing_rows: list[MissingRow] = field(default_factory=list)
    completeness_requirements: list[RequiredRow] = field(default_factory=list)
    missing_columns: list[MissingColumn] = field(default_factory=list)
    human_input_required: list[HumanInputItem] = field(default_factory=list)


Parsed = dict[str, list[dict]]


def analyze_gaps(old: Parsed, new: Parsed, contract: SchemaContract) -> GapReport:
    report = GapReport()

    # (a) Rows in new (by id_column) absent from old.
    missing_by_section: dict[str, list[dict]] = {}
    for section in contract.sections:
        id_col = section.id_column
        old_ids = _value_set(old, section.name, id_col)
        missing_rows: list[dict] = []
        for row in new.get(section.name, []):
            row_id = row.get(id_col)
            if row_id in (None, ""):
                continue
            if row_id not in old_ids:
                report.missing_rows.append(
                    MissingRow(
                        section=section.name,
                        row_id=row_id,
                        source_values=dict(row),
                        reason=(
                            f"Row '{row_id}' is present in new but absent from "
                            f"old section '{section.name}'"
                        ),
                    )
                )
                missing_rows.append(row)
        missing_by_section[section.name] = missing_rows

    # (b) + (c) + (d): for each missing row, walk companions, FKs, required cols.
    for section in contract.sections:
        for row in missing_by_section.get(section.name, []):
            row_id = row.get(section.id_column)
            _check_companions(report, section, row, row_id, old, new)
            _check_foreign_keys(report, section, row, row_id, old, new)
            _check_required_columns(report, section, row, row_id)

    # (e) Columns in new not in old.
    for section in contract.sections:
        old_cols = _columns(old.get(section.name, []))
        new_cols = _columns(new.get(section.name, []))
        coldef_by_name = {c.name: c for c in section.columns}
        for column in new_cols:
            if column in old_cols:
                continue
            coldef = coldef_by_name.get(column)
            report.missing_columns.append(
                MissingColumn(
                    section=section.name,
                    column_name=column,
                    appears_in="new",
                    default_available=bool(coldef is not None and coldef.default is not None),
                )
            )

    return report


def _check_companions(
    report: GapReport,
    section: SectionDef,
    row: dict,
    row_id: str | None,
    old: Parsed,
    new: Parsed,
) -> None:
    for companion in section.companions:
        value = row.get(companion.match_on)
        present_values = _value_set(new, companion.requires_section, companion.match_on) | _value_set(
            old, companion.requires_section, companion.match_on
        )
        satisfied = value not in (None, "") and value in present_values
        report.completeness_requirements.append(
            RequiredRow(
                section=companion.requires_section,
                reason=(
                    f"{section.name} '{row_id}' requires a companion row in "
                    f"'{companion.requires_section}' matching {companion.match_on}="
                    f"'{value}'"
                ),
                triggered_by=f"{section.name}#{row_id}",
                satisfied=satisfied,
            )
        )


def _check_foreign_keys(
    report: GapReport,
    section: SectionDef,
    row: dict,
    row_id: str | None,
    old: Parsed,
    new: Parsed,
) -> None:
    for fk in section.foreign_keys:
        value = row.get(fk.column)
        if value in (None, ""):
            continue
        # FK target must exist in old OR among the new rows (the planned set).
        targets = _value_set(old, fk.references_section, fk.references_column) | _value_set(
            new, fk.references_section, fk.references_column
        )
        if value not in targets:
            report.completeness_requirements.append(
                RequiredRow(
                    section=fk.references_section,
                    reason=(
                        f"Broken reference: {section.name} '{row_id}' "
                        f"{fk.column}='{value}' has no target "
                        f"{fk.references_section}.{fk.references_column} in old or "
                        f"new — cannot safely create"
                    ),
                    triggered_by=f"{section.name}#{row_id}",
                    satisfied=False,
                )
            )


def _check_required_columns(
    report: GapReport,
    section: SectionDef,
    row: dict,
    row_id: str | None,
) -> None:
    for column in section.columns:
        if not column.required:
            continue
        value = row.get(column.name)
        if value in (None, "") and column.default is None:
            report.human_input_required.append(
                HumanInputItem(
                    section=section.name,
                    row_id=row_id,
                    column=column.name,
                    data_type=column.data_type,
                    why_needed=(
                        f"Required column '{column.name}' is empty in the source "
                        f"and the contract provides no default"
                    ),
                )
            )


def _value_set(data: Parsed, section_name: str, column: str) -> set:
    return {
        row.get(column)
        for row in data.get(section_name, [])
        if row.get(column) not in (None, "")
    }


def _columns(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    return list(rows[0].keys())
