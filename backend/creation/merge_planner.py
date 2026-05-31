"""Turn a :class:`GapReport` into a reviewable, typed merge plan.

Every planned operation carries per-field provenance so reviewers can see
where each value came from. No values are invented: anything that cannot be
sourced from the new file, a contract default, or deterministic id allocation
is deferred to ``human_inputs_needed`` rather than appearing in ``operations``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal

from schema.contract_loader import get_section
from schema.contract_models import SchemaContract, SectionDef

from .gap_analyzer import GapReport, HumanInputItem, MissingRow, Parsed
from .id_allocator import NeedsHumanInput, allocate_id

Provenance = Literal[
    "from_new_file",
    "auto_allocated",
    "contract_default",
    "human_supplied",
    "needs_human",
]

OpType = Literal[
    "ADD_ROW",
    "ADD_COLUMN",
    "ALLOCATE_ID",
    "RESOLVE_FK",
    "FILL_DEFAULT",
    "REQUIRE_HUMAN_INPUT",
]


@dataclass
class MergeOperation:
    op_id: str
    op_type: OpType
    section: str
    target_id: str | None
    values: dict
    provenance: dict[str, Provenance]
    depends_on: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class BlockedItem:
    section: str
    target_id: str | None
    reason: str
    triggered_by: str = ""


@dataclass
class MergePlan:
    plan_id: str
    contract_name: str
    operations: list[MergeOperation]
    blocked: list[BlockedItem] = field(default_factory=list)
    human_inputs_needed: list[HumanInputItem] = field(default_factory=list)


def build_plan(
    gap_report: GapReport,
    old: Parsed,
    new: Parsed,
    contract: SchemaContract,
) -> MergePlan:
    """Build a topologically ordered merge plan from gap analysis."""

    blocked_keys: set[tuple[str, str | None]] = set()
    blocked: list[BlockedItem] = []

    for req in gap_report.completeness_requirements:
        if req.satisfied or "broken" not in req.reason.lower():
            continue
        section, row_id = _parse_triggered_by(req.triggered_by)
        key = (section, row_id)
        if key in blocked_keys:
            continue
        blocked_keys.add(key)
        blocked.append(
            BlockedItem(
                section=section,
                target_id=row_id,
                reason=req.reason,
                triggered_by=req.triggered_by,
            )
        )

    human_by_row: dict[tuple[str, str | None], list[HumanInputItem]] = {}
    for item in gap_report.human_input_required:
        human_by_row.setdefault((item.section, item.row_id), []).append(item)

    operations: list[MergeOperation] = []
    human_inputs_needed: list[HumanInputItem] = []
    add_row_index: dict[tuple[str, str], str] = {}
    planned_ids: dict[str, list[str]] = {
        section.name: _existing_ids(old, section.name, section.id_column)
        for section in contract.sections
    }

    for missing in gap_report.missing_rows:
        key = (missing.section, missing.row_id)
        if key in blocked_keys:
            continue
        if key in human_by_row:
            human_inputs_needed.extend(human_by_row[key])
            continue

        section_def = get_section(contract, missing.section)
        if section_def is None:
            continue

        row_ops, row_human = _plan_missing_row(
            missing,
            section_def,
            old,
            planned_ids,
            contract,
        )
        if row_human:
            human_inputs_needed.extend(row_human)
            continue

        for op in row_ops:
            operations.append(op)
            if op.op_type == "ADD_ROW" and op.target_id:
                add_row_index[(op.section, op.target_id)] = op.op_id
                planned_ids.setdefault(op.section, []).append(op.target_id)

    for missing in _rows_needing_id_allocation(old, new, contract, gap_report):
        key = (missing.section, missing.row_id)
        if key in blocked_keys or key in human_by_row:
            continue
        if (missing.section, missing.row_id or "") in {
            (op.section, op.target_id or "") for op in operations if op.op_type == "ADD_ROW"
        }:
            continue

        section_def = get_section(contract, missing.section)
        if section_def is None:
            continue

        row_ops, row_human = _plan_missing_row(
            missing,
            section_def,
            old,
            planned_ids,
            contract,
        )
        if row_human:
            human_inputs_needed.extend(row_human)
            continue

        for op in row_ops:
            operations.append(op)
            if op.op_type == "ADD_ROW" and op.target_id:
                add_row_index[(op.section, op.target_id)] = op.op_id
                planned_ids.setdefault(op.section, []).append(op.target_id)

    _attach_fk_dependencies(operations, add_row_index, old, contract)
    operations = _topological_sort(operations)

    for col in gap_report.missing_columns:
        operations.append(_plan_add_column(col, contract))

    operations = _topological_sort(operations)
    plan_id = _deterministic_plan_id(contract.contract_name, operations, blocked)

    return MergePlan(
        plan_id=plan_id,
        contract_name=contract.contract_name,
        operations=operations,
        blocked=blocked,
        human_inputs_needed=human_inputs_needed,
    )


def _plan_missing_row(
    missing: MissingRow,
    section_def: SectionDef,
    old: Parsed,
    planned_ids: dict[str, list[str]],
    contract: SchemaContract,
) -> tuple[list[MergeOperation], list[HumanInputItem]]:
    """Return operations for one missing row, or human-input items if blocked."""

    ops: list[MergeOperation] = []
    values: dict[str, str] = {}
    provenance: dict[str, Provenance] = {}
    depends_on: list[str] = []
    human: list[HumanInputItem] = []

    id_col = section_def.id_column
    coldefs = {c.name: c for c in section_def.columns}
    source = missing.source_values

    row_id = missing.row_id
    id_value = source.get(id_col, "")

    if id_value in (None, ""):
        try:
            allocated = allocate_id(
                missing.section,
                contract,
                planned_ids.get(missing.section, []),
                [],
            )
        except NeedsHumanInput as exc:
            human.append(
                HumanInputItem(
                    section=missing.section,
                    row_id=row_id,
                    column=id_col,
                    data_type=coldefs[id_col].data_type if id_col in coldefs else "string",
                    why_needed=str(exc),
                )
            )
            return [], human

        alloc_op = MergeOperation(
            op_id=_op_id("allocate-id", missing.section, allocated),
            op_type="ALLOCATE_ID",
            section=missing.section,
            target_id=allocated,
            values={id_col: allocated},
            provenance={id_col: "auto_allocated"},
            reason=f"Deterministic id allocation for new {missing.section} row",
        )
        ops.append(alloc_op)
        depends_on.append(alloc_op.op_id)
        row_id = allocated
        id_value = allocated
        values[id_col] = allocated
        provenance[id_col] = "auto_allocated"
    else:
        values[id_col] = str(id_value)
        provenance[id_col] = "from_new_file"

    for column in section_def.columns:
        if column.name == id_col:
            continue

        raw = source.get(column.name, "")
        if raw not in (None, ""):
            values[column.name] = str(raw)
            provenance[column.name] = "from_new_file"
            continue

        if column.default is not None:
            values[column.name] = column.default
            provenance[column.name] = "contract_default"
            fill_op = MergeOperation(
                op_id=_op_id("fill-default", missing.section, row_id, column.name),
                op_type="FILL_DEFAULT",
                section=missing.section,
                target_id=row_id,
                values={column.name: column.default},
                provenance={column.name: "contract_default"},
                depends_on=list(depends_on),
                reason=(
                    f"Contract default for '{column.name}' on {missing.section} "
                    f"'{row_id}'"
                ),
            )
            ops.append(fill_op)
            depends_on.append(fill_op.op_id)
            continue

        if column.required:
            human.append(
                HumanInputItem(
                    section=missing.section,
                    row_id=row_id,
                    column=column.name,
                    data_type=column.data_type,
                    why_needed=(
                        f"Required column '{column.name}' is empty in the source "
                        f"and the contract provides no default"
                    ),
                )
            )

    if human:
        return [], human

    add_op = MergeOperation(
        op_id=_op_id("add-row", missing.section, row_id),
        op_type="ADD_ROW",
        section=missing.section,
        target_id=row_id,
        values=values,
        provenance=provenance,
        depends_on=list(depends_on),
        reason=missing.reason,
    )
    ops.append(add_op)
    return ops, []


def _plan_add_column(col, contract: SchemaContract) -> MergeOperation:
    section_def = get_section(contract, col.section)
    default = None
    if section_def is not None:
        for column in section_def.columns:
            if column.name == col.column_name:
                default = column.default
                break

    values: dict[str, str] = {}
    provenance: dict[str, Provenance] = {}
    reason = (
        f"Column '{col.column_name}' appears in new but not old for "
        f"section '{col.section}'"
    )

    if col.default_available and default is not None:
        values[col.column_name] = default
        provenance[col.column_name] = "contract_default"
        reason += f"; backfill default '{default}' for existing rows"

    return MergeOperation(
        op_id=_op_id("add-column", col.section, col.column_name),
        op_type="ADD_COLUMN",
        section=col.section,
        target_id=None,
        values=values,
        provenance=provenance,
        reason=reason,
    )


def _attach_fk_dependencies(
    operations: list[MergeOperation],
    add_row_index: dict[tuple[str, str], str],
    old: Parsed,
    contract: SchemaContract,
) -> None:
    """Wire RESOLVE_FK ops and depends_on for FK targets created in this plan."""

    old_targets: dict[tuple[str, str], set[str]] = {}
    for section in contract.sections:
        for fk in section.foreign_keys:
            key = (fk.references_section, fk.references_column)
            old_targets.setdefault(key, set()).update(
                _existing_ids(old, fk.references_section, fk.references_column)
            )

    for op in list(operations):
        if op.op_type != "ADD_ROW":
            continue

        section_def = get_section(contract, op.section)
        if section_def is None:
            continue

        for fk in section_def.foreign_keys:
            fk_value = op.values.get(fk.column)
            if fk_value in (None, ""):
                continue

            target_key = (fk.references_section, fk.references_column)
            if fk_value in old_targets.get(target_key, set()):
                continue

            parent_key = (fk.references_section, fk_value)
            parent_op_id = add_row_index.get(parent_key)
            if parent_op_id is None:
                continue

            resolve_op = MergeOperation(
                op_id=_op_id(
                    "resolve-fk",
                    op.section,
                    op.target_id,
                    fk.column,
                    fk_value,
                ),
                op_type="RESOLVE_FK",
                section=op.section,
                target_id=op.target_id,
                values={fk.column: fk_value},
                provenance={fk.column: op.provenance.get(fk.column, "from_new_file")},
                depends_on=[parent_op_id],
                reason=(
                    f"{op.section} '{op.target_id}' {fk.column}='{fk_value}' "
                    f"depends on {fk.references_section} '{fk_value}' being created first"
                ),
            )
            operations.append(resolve_op)
            if parent_op_id not in op.depends_on:
                op.depends_on.append(parent_op_id)
            if resolve_op.op_id not in op.depends_on:
                op.depends_on.append(resolve_op.op_id)


def _rows_needing_id_allocation(
    old: Parsed,
    new: Parsed,
    contract: SchemaContract,
    gap_report: GapReport,
) -> list[MissingRow]:
    """Rows present in new with an empty id column (not reported by gap analyzer)."""

    already = {(m.section, m.row_id) for m in gap_report.missing_rows}
    extras: list[MissingRow] = []

    for section in contract.sections:
        id_col = section.id_column
        for row in new.get(section.name, []):
            row_id = row.get(id_col)
            if row_id not in (None, ""):
                continue
            extras.append(
                MissingRow(
                    section=section.name,
                    row_id=None,
                    source_values=dict(row),
                    reason=(
                        f"Row in new section '{section.name}' has no {id_col}; "
                        f"id must be allocated"
                    ),
                )
            )

    return [e for e in extras if (e.section, e.row_id) not in already]


def _topological_sort(operations: list[MergeOperation]) -> list[MergeOperation]:
    by_id = {op.op_id: op for op in operations}
    in_degree = {op.op_id: 0 for op in operations}
    dependents: dict[str, list[str]] = {op.op_id: [] for op in operations}

    for op in operations:
        for dep in op.depends_on:
            if dep not in by_id:
                continue
            in_degree[op.op_id] += 1
            dependents[dep].append(op.op_id)

    queue = sorted(op_id for op_id, degree in in_degree.items() if degree == 0)
    ordered: list[MergeOperation] = []

    while queue:
        op_id = queue.pop(0)
        ordered.append(by_id[op_id])
        for child in sorted(dependents[op_id]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
                queue.sort()

    if len(ordered) != len(operations):
        # Cycle or missing dependency target — preserve original order as fallback.
        return operations

    return ordered


def _deterministic_plan_id(
    contract_name: str,
    operations: list[MergeOperation],
    blocked: list[BlockedItem],
) -> str:
    payload = {
        "contract": contract_name,
        "ops": [
            {
                "id": op.op_id,
                "type": op.op_type,
                "section": op.section,
                "target": op.target_id,
                "values": op.values,
                "deps": op.depends_on,
            }
            for op in operations
        ],
        "blocked": [(b.section, b.target_id, b.reason) for b in blocked],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"{contract_name}-{digest[:12]}"


def _parse_triggered_by(triggered_by: str) -> tuple[str, str | None]:
    if "#" in triggered_by:
        section, row_id = triggered_by.split("#", 1)
        return section, row_id or None
    return triggered_by, None


def _existing_ids(data: Parsed, section: str, column: str) -> list[str]:
    return [
        str(row.get(column))
        for row in data.get(section, [])
        if row.get(column) not in (None, "")
    ]


def _op_id(kind: str, *parts: str | None) -> str:
    slug = "-".join(str(p) for p in parts if p not in (None, ""))
    return f"{kind}-{slug}" if slug else kind
