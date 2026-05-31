"""The reconciliation agent.

Combines the contract-driven parser/diff/integrity layers with declared intent
(Jira + diff) to produce a per-finding decision. Every threshold used to make a
decision comes from ``contract.thresholds`` -- nothing is hardcoded.
"""

from .reconciler import (
    AUTO_APPLY,
    BLOCK,
    ESCALATE,
    SUGGEST,
    AgentFinding,
    Reconciler,
    ReconciliationReport,
)
from .snapshot import list_snapshots, load_snapshot, save_snapshot
from .ai_validator import AIValidator, ValidationNote

__all__ = [
    "Reconciler",
    "ReconciliationReport",
    "AgentFinding",
    "BLOCK",
    "ESCALATE",
    "SUGGEST",
    "AUTO_APPLY",
    "save_snapshot",
    "load_snapshot",
    "list_snapshots",
    "AIValidator",
    "ValidationNote",
]
