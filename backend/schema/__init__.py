"""Schema contract package.

This package defines the *contract* that makes the reconciliation engine
generic. The engine never hardcodes field, file, or table names: every
customer-specific detail is described by a :class:`SchemaContract` that is
loaded from YAML at runtime.
"""

from .contract_models import (
    ColumnDef,
    CompanionRule,
    DecisionThresholds,
    FileFormat,
    ForeignKeyRule,
    SchemaContract,
    SectionDef,
)
from .contract_loader import (
    get_id_column,
    get_section,
    load_contract,
    validate_contract,
)

__all__ = [
    "ColumnDef",
    "CompanionRule",
    "DecisionThresholds",
    "FileFormat",
    "ForeignKeyRule",
    "SchemaContract",
    "SectionDef",
    "get_id_column",
    "get_section",
    "load_contract",
    "validate_contract",
]
