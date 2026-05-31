"""Apply an approved merge plan to a parsed baseline config."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Literal

from schema.contract_loader import get_section
from schema.contract_models import SchemaContract, SectionDef

from .gap_analyzer import Parsed
from .merge_planner import MergeOperation, MergePlan

Action = Literal[
    "ADD_ROW",
    "ADD_COLUMN",
    "ALLOCATE_ID",
    "RESOLVE_FK",
    "FILL_DEFAULT",
    "SKIPPED_DUPLICATE",
]


@dataclass
class ChangelogEntry:
    op_id: str
    section: str
    target_id: str | None
    action: Action
    field_provenance: dict[str, str]
    reason: str


@dataclass
class MergeResult:
    merged_sections: Parsed
    applied_ops: list[str] = field(default_factory=list)
    changelog: list[ChangelogEntry] = field(default_factory=list)


def apply_plan(plan: MergePlan, old: Parsed, contract: SchemaContract) -> MergeResult:
    """Apply ``plan`` to a copy of ``old`` in dependency order."""

    merged = copy.deepcopy(old)
    applied_ops: list[str] = []
    changelog: list[ChangelogEntry] = []

    for op in plan.operations:
        if op.op_type == "ADD_ROW":
            entry = _apply_add_row(op, merged, contract)
            if entry.action == "SKIPPED_DUPLICATE":
                changelog.append(entry)
                continue
            applied_ops.append(op.op_id)
            changelog.append(entry)
            continue

        if op.op_type == "ADD_COLUMN":
            entry = _apply_add_column(op, merged, contract)
            applied_ops.append(op.op_id)
            changelog.append(entry)
            continue

        # Preparatory ops are reflected in ADD_ROW values; record for audit only.
        if op.op_type in {"ALLOCATE_ID", "RESOLVE_FK", "FILL_DEFAULT"}:
            changelog.append(
                ChangelogEntry(
                    op_id=op.op_id,
                    section=op.section,
                    target_id=op.target_id,
                    action=op.op_type,  # type: ignore[arg-type]
                    field_provenance=dict(op.provenance),
                    reason=op.reason,
                )
            )

    return MergeResult(
        merged_sections=merged,
        applied_ops=applied_ops,
        changelog=changelog,
    )


def serialize_merged(merged_sections: Parsed, contract: SchemaContract) -> str:
    """Serialize ``merged_sections`` using the contract's exact file layout."""

    fmt = contract.file_format
    lines: list[str] = []

    if fmt.has_section_markers:
        for section in contract.sections:
            rows = merged_sections.get(section.name, [])
            columns = _section_columns(section, rows)
            if fmt.header_position == "before_start":
                lines.append(_format_line(columns, fmt))
                lines.append(f"{fmt.section_start_prefix}{section.name}")
                for row in rows:
                    lines.append(_format_row(row, columns, fmt))
                lines.append(f"{fmt.section_end_prefix}{section.name}")
            else:
                lines.append(f"{fmt.section_start_prefix}{section.name}")
                lines.append(_format_line(columns, fmt))
                for row in rows:
                    lines.append(_format_row(row, columns, fmt))
                lines.append(f"{fmt.section_end_prefix}{section.name}")
    else:
        section = contract.sections[0]
        rows = merged_sections.get(section.name, [])
        columns = _section_columns(section, rows)
        lines.append(_format_line(columns, fmt))
        for row in rows:
            lines.append(_format_row(row, columns, fmt))

    return "\n".join(lines) + "\n"


def _apply_add_row(
    op: MergeOperation,
    merged: Parsed,
    contract: SchemaContract,
) -> ChangelogEntry:
    section_def = get_section(contract, op.section)
    if section_def is None:
        raise KeyError(f"Unknown section: '{op.section}'")

    id_col = section_def.id_column
    rows = merged.setdefault(op.section, [])
    existing_ids = {
        row.get(id_col) for row in rows if row.get(id_col) not in (None, "")
    }

    if op.target_id in existing_ids:
        return ChangelogEntry(
            op_id=op.op_id,
            section=op.section,
            target_id=op.target_id,
            action="SKIPPED_DUPLICATE",
            field_provenance=dict(op.provenance),
            reason=(
                f"Row '{op.target_id}' already exists in section '{op.section}' "
                f"(idempotent skip)"
            ),
        )

    row = {key: str(value) for key, value in op.values.items()}
    for column in section_def.columns:
        row.setdefault(column.name, "")

    rows.append(row)
    return ChangelogEntry(
        op_id=op.op_id,
        section=op.section,
        target_id=op.target_id,
        action="ADD_ROW",
        field_provenance=dict(op.provenance),
        reason=op.reason,
    )


def _apply_add_column(
    op: MergeOperation,
    merged: Parsed,
    contract: SchemaContract,
) -> ChangelogEntry:
    section_def = get_section(contract, op.section)
    rows = merged.setdefault(op.section, [])

    for column_name, default_value in op.values.items():
        for row in rows:
            row.setdefault(column_name, str(default_value))

    return ChangelogEntry(
        op_id=op.op_id,
        section=op.section,
        target_id=op.target_id,
        action="ADD_COLUMN",
        field_provenance=dict(op.provenance),
        reason=op.reason,
    )


def _section_columns(section: SectionDef, rows: list[dict]) -> list[str]:
    declared = [column.name for column in section.columns]
    seen = set(declared)
    extras: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                extras.append(key)
                seen.add(key)
    return declared + extras


def _format_line(fields: list[str], fmt) -> str:
    body = fmt.delimiter.join(fields)
    if fmt.leading_empty_field:
        return fmt.delimiter + body
    return body


def _format_row(row: dict, columns: list[str], fmt) -> str:
    values = [str(row.get(column, "")) for column in columns]
    return _format_line(values, fmt)
