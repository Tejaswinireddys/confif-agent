"""Collect and validate human-supplied values for deferred merge operations."""

from __future__ import annotations

import ipaddress
from dataclasses import replace

from schema.contract_loader import get_section
from schema.contract_models import ColumnDef, SchemaContract

from .merge_planner import (
    MergeOperation,
    MergePlan,
    Provenance,
    _attach_fk_dependencies,
    _op_id,
    _topological_sort,
)


class HumanInputValidationError(ValueError):
    """Raised when a supplied value fails contract data_type validation."""


def apply_human_inputs(
    plan: MergePlan,
    inputs: dict[str, dict[str, str]],
    contract: SchemaContract,
) -> MergePlan:
    """Validate human inputs and promote satisfied rows into ``operations``.

    Does not mutate the baseline config — only returns an updated plan whose
    satisfied ``human_inputs_needed`` items become ``ADD_ROW`` operations with
    ``human_supplied`` provenance on the fields that required human input.
    """

    if not plan.human_inputs_needed:
        return plan

    grouped: dict[tuple[str, str | None], list] = {}
    for item in plan.human_inputs_needed:
        grouped.setdefault((item.section, item.row_id), []).append(item)

    remaining_human = list(plan.human_inputs_needed)
    promoted_keys: set[tuple[str, str | None]] = set()
    new_operations = list(plan.operations)
    add_row_index = {
        (op.section, op.target_id): op.op_id
        for op in new_operations
        if op.op_type == "ADD_ROW" and op.target_id
    }

    for (section, row_id), items in grouped.items():
        op_id = _op_id("add-row", section, row_id)
        field_values = inputs.get(op_id)
        if field_values is None:
            continue

        section_def = get_section(contract, section)
        if section_def is None:
            raise HumanInputValidationError(f"Unknown section '{section}'")

        coldefs = {column.name: column for column in section_def.columns}
        human_columns = {item.column for item in items}

        missing = [item.column for item in items if item.column not in field_values]
        if missing:
            raise HumanInputValidationError(
                f"Operation '{op_id}' is missing required human input for: "
                f"{', '.join(sorted(missing))}"
            )

        values: dict[str, str] = {}
        provenance: dict[str, Provenance] = {}
        for column_name, raw_value in field_values.items():
            column = coldefs.get(column_name)
            if column is None:
                values[column_name] = str(raw_value)
                provenance[column_name] = (
                    "human_supplied" if column_name in human_columns else "from_new_file"
                )
                continue

            validated = validate_column_value(str(raw_value), column, section, column_name)
            values[column_name] = validated
            provenance[column_name] = (
                "human_supplied" if column_name in human_columns else "from_new_file"
            )

        for item in items:
            if item.column not in values:
                raise HumanInputValidationError(
                    f"Operation '{op_id}' is missing required human input for "
                    f"'{item.column}'"
                )

        add_op = MergeOperation(
            op_id=op_id,
            op_type="ADD_ROW",
            section=section,
            target_id=row_id or values.get(section_def.id_column),
            values=values,
            provenance=provenance,
            depends_on=[],
            reason=(
                f"Row '{row_id}' promoted from human_inputs_needed after "
                f"reviewer supplied required values"
            ),
        )
        new_operations.append(add_op)
        if add_op.target_id:
            add_row_index[(section, add_op.target_id)] = op_id

        for item in items:
            promoted_keys.add((item.section, item.row_id))

    remaining_human = [
        item
        for item in plan.human_inputs_needed
        if (item.section, item.row_id) not in promoted_keys
    ]

    old_stub: dict[str, list[dict]] = {}
    _attach_fk_dependencies(new_operations, add_row_index, old_stub, contract)
    new_operations = _topological_sort(new_operations)

    return replace(
        plan,
        operations=new_operations,
        human_inputs_needed=remaining_human,
    )


def validate_column_value(
    value: str,
    column: ColumnDef,
    section: str,
    column_name: str,
) -> str:
    """Validate ``value`` against ``column.data_type`` and return normalized text."""

    text = value.strip()
    if text == "":
        raise HumanInputValidationError(
            f"Section '{section}' column '{column_name}' cannot be empty"
        )

    data_type = column.data_type

    if data_type == "int":
        if not _is_int(text):
            raise HumanInputValidationError(
                f"Section '{section}' column '{column_name}' expects an integer, "
                f"got '{value}'"
            )
        return str(int(text))

    if data_type == "ip":
        try:
            ipaddress.ip_address(text)
        except ValueError as exc:
            raise HumanInputValidationError(
                f"Section '{section}' column '{column_name}' expects a valid IP "
                f"address, got '{value}'"
            ) from exc
        return text

    if data_type == "port":
        if not _is_int(text):
            raise HumanInputValidationError(
                f"Section '{section}' column '{column_name}' expects a port number, "
                f"got '{value}'"
            )
        port = int(text)
        if not 1 <= port <= 65535:
            raise HumanInputValidationError(
                f"Section '{section}' column '{column_name}' port must be 1-65535, "
                f"got '{value}'"
            )
        return str(port)

    if data_type == "enum":
        allowed = column.enum_values or []
        if text not in allowed:
            raise HumanInputValidationError(
                f"Section '{section}' column '{column_name}' must be one of "
                f"{allowed}, got '{value}'"
            )
        return text

    if data_type == "bool":
        normalized = text.lower()
        if normalized in {"true", "1", "yes"}:
            return "true"
        if normalized in {"false", "0", "no"}:
            return "false"
        raise HumanInputValidationError(
            f"Section '{section}' column '{column_name}' expects a boolean, "
            f"got '{value}'"
        )

    return text


def _is_int(value: str) -> bool:
    text = value.strip()
    if text.startswith("-"):
        text = text[1:]
    return text.isdigit()
