"""Detect column-level (schema) differences between two parsed configs.

The comparator works purely off the column names observed in the parsed data
and the columns declared in the contract. It reports columns that were added,
removed, reordered, or that appear in the data but are not declared in the
contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from schema.contract_models import SchemaContract
from schema.contract_loader import get_section


@dataclass
class SchemaChange:
    """A single column-level change within one section.

    ``base_index`` / ``new_index`` are the column's position in the base and new
    headers respectively, or ``None`` when the column is absent from that side.
    """

    section: str
    change_type: str  # COLUMN_ADDED | COLUMN_REMOVED | COLUMN_REORDERED | UNDECLARED_COLUMN
    column_name: str
    base_index: int | None
    new_index: int | None


def compare_schemas(
    base: dict[str, list[dict]],
    new: dict[str, list[dict]],
    contract: SchemaContract,
) -> list[SchemaChange]:
    """Compare the column layout of every section across ``base`` and ``new``."""

    changes: list[SchemaChange] = []

    for section in _ordered_sections(base, new):
        base_cols = _columns_of(base.get(section, []))
        new_cols = _columns_of(new.get(section, []))
        base_index = {name: idx for idx, name in enumerate(base_cols)}
        new_index = {name: idx for idx, name in enumerate(new_cols)}

        section_def = get_section(contract, section)
        declared = (
            {column.name for column in section_def.columns}
            if section_def is not None
            else None
        )

        for column in _dedup(base_cols + new_cols):
            in_base = column in base_index
            in_new = column in new_index
            bi = base_index.get(column)
            ni = new_index.get(column)

            if in_base and not in_new:
                changes.append(
                    SchemaChange(section, "COLUMN_REMOVED", column, bi, None)
                )
            elif in_new and not in_base:
                changes.append(
                    SchemaChange(section, "COLUMN_ADDED", column, None, ni)
                )
            elif bi != ni:
                changes.append(
                    SchemaChange(section, "COLUMN_REORDERED", column, bi, ni)
                )

            # A column present in the data but not declared in the contract is
            # flagged regardless of whether it was also added/removed/reordered.
            if declared is not None and column not in declared:
                changes.append(
                    SchemaChange(section, "UNDECLARED_COLUMN", column, bi, ni)
                )

    return changes


def _columns_of(rows: list[dict]) -> list[str]:
    """Recover header column order from the first row (insertion-ordered dict)."""

    if not rows:
        return []
    return list(rows[0].keys())


def _ordered_sections(
    base: dict[str, list[dict]],
    new: dict[str, list[dict]],
) -> list[str]:
    return _dedup(list(base.keys()) + list(new.keys()))


def _dedup(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
