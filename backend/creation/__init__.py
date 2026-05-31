"""Creation-side intelligence: relational gap analysis and deterministic id allocation.

These modules reason about *relational completeness* using the schema contract
(missing rows, unsatisfied companions, broken references, required-but-empty
columns) rather than performing a textual line diff.
"""

from .gap_analyzer import (
    GapReport,
    HumanInputItem,
    MissingColumn,
    MissingRow,
    RequiredRow,
    analyze_gaps,
)
from .id_allocator import NeedsHumanInput, allocate_id
from .merge_planner import (
    BlockedItem,
    MergeOperation,
    MergePlan,
    build_plan,
)
from .plan_validator import PlanIssue, validate_plan
from .input_collector import (
    HumanInputValidationError,
    apply_human_inputs,
    validate_column_value,
)
from .merge_applier import (
    ChangelogEntry,
    MergeResult,
    apply_plan,
    serialize_merged,
)
from .rereview import (
    OrphanRow,
    RereviewReport,
    UnexpectedMutation,
    rereview_merged,
)
from .creation_pipeline import (
    CreationResult,
    CreationSession,
    finalize_creation,
    run_creation,
    save_creation_snapshot,
)

__all__ = [
    "analyze_gaps",
    "GapReport",
    "MissingRow",
    "RequiredRow",
    "MissingColumn",
    "HumanInputItem",
    "allocate_id",
    "NeedsHumanInput",
    "build_plan",
    "MergePlan",
    "MergeOperation",
    "BlockedItem",
    "validate_plan",
    "PlanIssue",
    "apply_human_inputs",
    "HumanInputValidationError",
    "validate_column_value",
    "apply_plan",
    "serialize_merged",
    "MergeResult",
    "ChangelogEntry",
    "rereview_merged",
    "RereviewReport",
    "UnexpectedMutation",
    "OrphanRow",
    "run_creation",
    "finalize_creation",
    "CreationSession",
    "CreationResult",
    "save_creation_snapshot",
]
