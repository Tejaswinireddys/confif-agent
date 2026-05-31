"""Generic, contract-driven config file parser.

The parser turns raw config text into ``{section_name: [row_dict, ...]}`` using
only the layout described by ``contract.file_format`` and the section/column
definitions in the contract. It never assumes a particular delimiter, marker
convention, header placement, or column name.

Row dicts are keyed by the column names found in the file's header. Those names
correspond to contract columns, but columns that are *not* declared in the
contract are still preserved here so that downstream comparison can flag them as
undeclared.
"""

from __future__ import annotations

from pathlib import Path

from schema.contract_models import FileFormat, SchemaContract, SectionDef
from schema.contract_loader import get_section


def parse_file(
    text: str,
    contract: SchemaContract,
    filename: str | None = None,
) -> dict[str, list[dict]]:
    """Parse ``text`` into sections of row dicts according to ``contract``.

    When ``contract.file_format.has_section_markers`` is true the file is split
    into marker-delimited sections. Otherwise the whole file is treated as a
    single table whose section name is the file stem (``filename``), falling
    back to the sole contract section name, then to ``"default"``.
    """

    fmt = contract.file_format
    if fmt.has_section_markers:
        return _parse_sectioned(text, contract, fmt)
    return _parse_flat(text, contract, fmt, filename)


def detect_section_id(row: dict, section_def: SectionDef) -> str | None:
    """Return the identity value of ``row`` using ``section_def.id_column``."""

    return row.get(section_def.id_column)


# ---------------------------------------------------------------------------
# Field-level helpers
# ---------------------------------------------------------------------------


def _split_fields(line: str, fmt: FileFormat) -> list[str]:
    """Split a single line into trimmed fields, honoring ``leading_empty_field``."""

    fields = line.split(fmt.delimiter)
    if fmt.leading_empty_field and fields and fields[0].strip() == "":
        fields = fields[1:]
    return [field.strip() for field in fields]


def _marker_token(line: str, fmt: FileFormat) -> str:
    """Normalize a line for marker detection (drop indentation / leading empty)."""

    token = line.strip()
    if fmt.leading_empty_field and token.startswith(fmt.delimiter):
        token = token[len(fmt.delimiter):].strip()
    return token


def _is_start(line: str, fmt: FileFormat) -> bool:
    return _marker_token(line, fmt).startswith(fmt.section_start_prefix)


def _is_end(line: str, fmt: FileFormat) -> bool:
    return _marker_token(line, fmt).startswith(fmt.section_end_prefix)


def _section_name(line: str, fmt: FileFormat, prefix: str) -> str:
    return _marker_token(line, fmt)[len(prefix):]


def _row_dict(columns: list[str], values: list[str]) -> dict:
    """Zip column names with values, padding missing trailing values with ""."""

    return {
        column: (values[index] if index < len(values) else "")
        for index, column in enumerate(columns)
    }


def _fallback_columns(contract: SchemaContract, section_name: str) -> list[str]:
    section_def = get_section(contract, section_name)
    if section_def is None:
        return []
    return [column.name for column in section_def.columns]


# ---------------------------------------------------------------------------
# Sectioned (marker-delimited) parsing
# ---------------------------------------------------------------------------


def _parse_sectioned(
    text: str,
    contract: SchemaContract,
    fmt: FileFormat,
) -> dict[str, list[dict]]:
    lines = text.splitlines()
    result: dict[str, list[dict]] = {}

    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_start(line, fmt):
            index += 1
            continue

        section_name = _section_name(line, fmt, fmt.section_start_prefix)

        # Collect the section body up to the matching end marker.
        body_start = index + 1
        body_end = body_start
        while body_end < len(lines) and not _is_end(lines[body_end], fmt):
            body_end += 1
        body = lines[body_start:body_end]

        if fmt.header_position == "first_row":
            columns, data_lines = _header_first_row(body, fmt)
        else:  # "before_start"
            columns = _header_before_start(lines, index, fmt)
            data_lines = body

        if not columns:
            columns = _fallback_columns(contract, section_name)

        rows = [
            _row_dict(columns, _split_fields(data_line, fmt))
            for data_line in data_lines
            if data_line.strip()
        ]
        result[section_name] = rows

        index = body_end + 1

    return result


def _header_before_start(
    lines: list[str],
    start_index: int,
    fmt: FileFormat,
) -> list[str]:
    """Find the header on the nearest non-blank line *before* the start marker."""

    cursor = start_index - 1
    while cursor >= 0 and lines[cursor].strip() == "":
        cursor -= 1
    if cursor < 0:
        return []
    candidate = lines[cursor]
    if _is_start(candidate, fmt) or _is_end(candidate, fmt):
        return []
    return _split_fields(candidate, fmt)


def _header_first_row(
    body: list[str],
    fmt: FileFormat,
) -> tuple[list[str], list[str]]:
    """Treat the first non-blank body line as the header, rest as data."""

    for position, line in enumerate(body):
        if line.strip():
            return _split_fields(line, fmt), body[position + 1:]
    return [], []


# ---------------------------------------------------------------------------
# Flat (single-table) parsing
# ---------------------------------------------------------------------------


def _parse_flat(
    text: str,
    contract: SchemaContract,
    fmt: FileFormat,
    filename: str | None,
) -> dict[str, list[dict]]:
    section_name = _flat_section_name(contract, filename)
    columns, data_lines = _header_first_row(text.splitlines(), fmt)

    if not columns:
        columns = _fallback_columns(contract, section_name)

    rows = [
        _row_dict(columns, _split_fields(data_line, fmt))
        for data_line in data_lines
        if data_line.strip()
    ]
    return {section_name: rows}


def _flat_section_name(contract: SchemaContract, filename: str | None) -> str:
    if filename:
        return Path(filename).stem
    if len(contract.sections) == 1:
        return contract.sections[0].name
    return "default"
