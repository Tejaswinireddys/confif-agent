"""Generic, contract-driven parsing and diffing.

Everything in this package reads layout, section, and column information from a
:class:`schema.contract_models.SchemaContract`. No field, section, file, or
table name is ever hardcoded in the logic here.
"""

from .generic_parser import detect_section_id, parse_file
from .schema_comparator import SchemaChange, compare_schemas
from .diff_engine import Finding, diff_sections
from .integrity_checker import IntegrityViolation, check_integrity

__all__ = [
    "parse_file",
    "detect_section_id",
    "SchemaChange",
    "compare_schemas",
    "Finding",
    "diff_sections",
    "IntegrityViolation",
    "check_integrity",
]
