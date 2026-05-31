"""Parse a unified git diff and map changed lines onto contract sections.

Section detection is contract-driven: a hunk is attributed to a section by
finding the section's start marker (``file_format.section_start_prefix`` +
section name) in the hunk's surrounding context. No section name is hardcoded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schema.contract_models import SchemaContract


@dataclass
class DiffHunk:
    """One ``@@`` hunk of a unified diff.

    ``context_lines`` (unchanged lines) are retained in addition to the required
    added/removed lines because section markers usually live on context lines.
    """

    filename: str
    added_lines: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)
    context_lines: list[str] = field(default_factory=list)


@dataclass
class DeclaredChange:
    """A change declared in the diff, attributed to a contract section."""

    section: str | None
    operation: str  # ADD | REMOVE
    row_hint: str


def parse_git_diff(diff_text: str) -> list[DiffHunk]:
    """Split a unified diff into per-hunk :class:`DiffHunk` records."""

    hunks: list[DiffHunk] = []
    current_file = ""
    current_hunk: DiffHunk | None = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            current_file = _filename_from_diff_git(line) or current_file
            current_hunk = None
            continue

        if line.startswith("+++ "):
            current_file = _strip_diff_path(line[4:]) or current_file
            continue

        if line.startswith("--- "):
            continue

        if line.startswith("@@"):
            current_hunk = DiffHunk(filename=current_file)
            hunks.append(current_hunk)
            continue

        if current_hunk is None:
            continue

        if line.startswith("+"):
            current_hunk.added_lines.append(line[1:])
        elif line.startswith("-"):
            current_hunk.removed_lines.append(line[1:])
        elif line.startswith(" "):
            current_hunk.context_lines.append(line[1:])

    return hunks


def extract_csv_changes(
    hunks: list[DiffHunk],
    contract: SchemaContract,
) -> list[DeclaredChange]:
    """Turn diff hunks into section-attributed declared changes."""

    prefix = contract.file_format.section_start_prefix
    section_names = [section.name for section in contract.sections]
    changes: list[DeclaredChange] = []

    for hunk in hunks:
        section = _detect_section(hunk, prefix, section_names)

        for line in hunk.added_lines:
            if _is_data_line(line, contract):
                changes.append(DeclaredChange(section, "ADD", line.strip()))
        for line in hunk.removed_lines:
            if _is_data_line(line, contract):
                changes.append(DeclaredChange(section, "REMOVE", line.strip()))

    return changes


def _detect_section(
    hunk: DiffHunk,
    prefix: str,
    section_names: list[str],
) -> str | None:
    """Find the section whose start marker appears in this hunk.

    Context lines are scanned first (markers are usually unchanged context),
    then added/removed lines for hunks that introduce or delete whole sections.
    """

    for line in hunk.context_lines + hunk.added_lines + hunk.removed_lines:
        token = line.strip()
        for name in section_names:
            if token.lstrip(",; \t").startswith(f"{prefix}{name}"):
                return name
    return None


def _is_data_line(line: str, contract: SchemaContract) -> bool:
    """A data line is a non-empty line that is not a section marker."""

    fmt = contract.file_format
    token = line.strip().lstrip(",; \t")
    if not token:
        return False
    if token.startswith(fmt.section_start_prefix) or token.startswith(
        fmt.section_end_prefix
    ):
        return False
    return True


def _filename_from_diff_git(line: str) -> str | None:
    # "diff --git a/path/to/file b/path/to/file"
    parts = line.split()
    if len(parts) >= 4:
        return _strip_diff_path(parts[-1])
    return None


def _strip_diff_path(path: str) -> str:
    path = path.strip()
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path
