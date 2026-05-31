"""Validate a :class:`MergePlan` for internal consistency and FK ordering."""

from __future__ import annotations

from dataclasses import dataclass

from schema.contract_loader import get_section
from schema.contract_models import SchemaContract

from .merge_planner import MergePlan, MergeOperation


@dataclass
class PlanIssue:
    code: str
    message: str
    op_id: str | None = None


def validate_plan(plan: MergePlan, contract: SchemaContract) -> list[PlanIssue]:
    """Return structural and semantic issues with ``plan`` (empty if valid)."""

    issues: list[PlanIssue] = []
    by_id: dict[str, MergeOperation] = {op.op_id: op for op in plan.operations}

    # depends_on references must exist.
    for op in plan.operations:
        for dep in op.depends_on:
            if dep not in by_id:
                issues.append(
                    PlanIssue(
                        code="MISSING_DEPENDENCY",
                        message=f"Operation '{op.op_id}' depends on unknown op '{dep}'",
                        op_id=op.op_id,
                    )
                )

    # No dependency cycles.
    issues.extend(_cycle_issues(plan.operations, by_id))

    # No needs_human provenance inside operations.
    for op in plan.operations:
        for field, source in op.provenance.items():
            if source == "needs_human":
                issues.append(
                    PlanIssue(
                        code="HUMAN_INPUT_IN_OPERATIONS",
                        message=(
                            f"Operation '{op.op_id}' field '{field}' has "
                            f"provenance 'needs_human'; defer to human_inputs_needed"
                        ),
                        op_id=op.op_id,
                    )
                )

    # FK-referencing ADD_ROW ops must have targets in old or earlier in the plan.
    issues.extend(_fk_order_issues(plan.operations, by_id, contract))

    return issues


def _cycle_issues(
    operations: list[MergeOperation],
    by_id: dict[str, MergeOperation],
) -> list[PlanIssue]:
    issues: list[PlanIssue] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(op_id: str) -> bool:
        if op_id in visiting:
            issues.append(
                PlanIssue(
                    code="DEPENDENCY_CYCLE",
                    message=f"Dependency cycle detected involving '{op_id}'",
                    op_id=op_id,
                )
            )
            return True
        if op_id in visited:
            return False
        visiting.add(op_id)
        op = by_id.get(op_id)
        if op is not None:
            for dep in op.depends_on:
                if dep in by_id and dfs(dep):
                    return True
        visiting.remove(op_id)
        visited.add(op_id)
        return False

    for op in operations:
        dfs(op.op_id)

    return issues


def _fk_order_issues(
    operations: list[MergeOperation],
    by_id: dict[str, MergeOperation],
    contract: SchemaContract,
) -> list[PlanIssue]:
    issues: list[PlanIssue] = []
    op_position = {op.op_id: index for index, op in enumerate(operations)}

    add_rows_by_target: dict[tuple[str, str], str] = {}
    for op in operations:
        if op.op_type == "ADD_ROW" and op.target_id:
            add_rows_by_target[(op.section, op.target_id)] = op.op_id

    for op in operations:
        if op.op_type != "ADD_ROW":
            continue

        section_def = get_section(contract, op.section)
        if section_def is None:
            continue

        for fk in section_def.foreign_keys:
            fk_value = op.values.get(fk.column)
            if fk_value in (None, ""):
                continue

            parent_key = (fk.references_section, fk_value)
            parent_op_id = add_rows_by_target.get(parent_key)
            if parent_op_id is None:
                # Target is assumed to exist in the baseline (old) config.
                continue

            parent_pos = op_position.get(parent_op_id)
            child_pos = op_position.get(op.op_id)
            if parent_pos is None or child_pos is None:
                continue

            if parent_pos >= child_pos:
                issues.append(
                    PlanIssue(
                        code="FK_ORDER_VIOLATION",
                        message=(
                            f"ADD_ROW '{op.op_id}' references "
                            f"{fk.references_section} '{fk_value}' which is "
                            f"created by '{parent_op_id}' but appears earlier "
                            f"in the plan"
                        ),
                        op_id=op.op_id,
                    )
                )

            if parent_op_id not in op.depends_on:
                issues.append(
                    PlanIssue(
                        code="FK_NOT_WIRED",
                        message=(
                            f"ADD_ROW '{op.op_id}' should depend on "
                            f"'{parent_op_id}' for FK {fk.column}='{fk_value}'"
                        ),
                        op_id=op.op_id,
                    )
                )

    return issues
