"""Row-level diff engine driven entirely by the schema contract.

Row identity comes from each section's ``id_column`` (never positional). Two
rows that share an id are compared on the *intersection* of their columns, so
adding or removing a column never registers as a value modification, and merely
reordering columns yields ``IDENTICAL``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schema.contract_models import SchemaContract
from schema.contract_loader import get_section

from .schema_comparator import SchemaChange, compare_schemas


@dataclass
class Finding:
    """The reconciliation result for a single row (or row pair)."""

    section: str
    row_id: str | None
    change_type: str  # ADDED | REMOVED | MODIFIED | IDENTICAL
    base_row: dict | None
    new_row: dict | None
    changed_fields: list[str] = field(default_factory=list)
    schema_changes: list[SchemaChange] = field(default_factory=list)


def diff_sections(
    base: dict[str, list[dict]],
    new: dict[str, list[dict]],
    contract: SchemaContract,
) -> list[Finding]:
    """Produce per-row findings for every section across ``base`` and ``new``."""

    all_schema_changes = compare_schemas(base, new, contract)
    schema_by_section: dict[str, list[SchemaChange]] = {}
    for change in all_schema_changes:
        schema_by_section.setdefault(change.section, []).append(change)

    findings: list[Finding] = []

    for section in _ordered_sections(base, new):
        section_def = get_section(contract, section)
        id_column = section_def.id_column if section_def is not None else None
        section_schema_changes = schema_by_section.get(section, [])

        base_rows = base.get(section, [])
        new_rows = new.get(section, [])
        base_by_id = _index_by_id(base_rows, id_column)
        new_by_id = _index_by_id(new_rows, id_column)

        shared_columns = _shared_columns(base_rows, new_rows)

        for row_id in _ordered_ids(base_by_id, new_by_id):
            base_row = base_by_id.get(row_id)
            new_row = new_by_id.get(row_id)

            if base_row is not None and new_row is None:
                change_type, changed = "REMOVED", []
            elif new_row is not None and base_row is None:
                change_type, changed = "ADDED", []
            else:
                changed = [
                    column
                    for column in shared_columns
                    if base_row.get(column) != new_row.get(column)
                ]
                change_type = "MODIFIED" if changed else "IDENTICAL"

            findings.append(
                Finding(
                    section=section,
                    row_id=row_id,
                    change_type=change_type,
                    base_row=base_row,
                    new_row=new_row,
                    changed_fields=changed,
                    schema_changes=section_schema_changes,
                )
            )

    return findings


def _index_by_id(rows: list[dict], id_column: str | None) -> dict:
    """Map rows by their id value. Falls back to positional keys if no id_column."""

    indexed: dict = {}
    for position, row in enumerate(rows):
        key = row.get(id_column) if id_column is not None else None
        if key is None or key == "":
            key = f"__row_{position}__"
        indexed[key] = row
    return indexed


def _shared_columns(base_rows: list[dict], new_rows: list[dict]) -> list[str]:
    base_cols = list(base_rows[0].keys()) if base_rows else []
    new_cols = set(new_rows[0].keys()) if new_rows else set()
    return [column for column in base_cols if column in new_cols]


def _ordered_ids(base_by_id: dict, new_by_id: dict) -> list:
    ordered = list(base_by_id.keys())
    for key in new_by_id:
        if key not in base_by_id:
            ordered.append(key)
    return ordered


def _ordered_sections(
    base: dict[str, list[dict]],
    new: dict[str, list[dict]],
) -> list[str]:
    return list(dict.fromkeys(list(base.keys()) + list(new.keys())))
