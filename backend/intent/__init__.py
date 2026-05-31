"""Intent extraction.

Reads the *declared* intent of a change from external sources (a Jira ticket and
a git diff) and uses an LLM to map that intent onto the customer's schema
contract sections. The extractor is told the contract's section names and
descriptions at runtime; nothing about a specific customer is hardcoded.
"""

from .jira_reader import JiraReader, JiraTicket, extract_raw_text
from .diff_reader import (
    DeclaredChange,
    DiffHunk,
    extract_csv_changes,
    parse_git_diff,
)
from .ai_extractor import AIExtractor, IntentSummary

__all__ = [
    "JiraReader",
    "JiraTicket",
    "extract_raw_text",
    "DiffHunk",
    "DeclaredChange",
    "parse_git_diff",
    "extract_csv_changes",
    "AIExtractor",
    "IntentSummary",
]
