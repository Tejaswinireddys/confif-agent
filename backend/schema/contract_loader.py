"""Load and validate :class:`SchemaContract` instances from YAML.

The loader is intentionally the *only* place that turns raw YAML into the typed
contract objects the rest of the engine consumes. Helper accessors
(``get_section`` / ``get_id_column``) let engine code look things up by the
names declared in the contract instead of hardcoding them.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .contract_models import SchemaContract, SectionDef


def load_contract(path: str | Path) -> SchemaContract:
    """Parse a YAML file at ``path`` and validate it into a ``SchemaContract``.

    Raises ``FileNotFoundError`` if the file is missing, ``yaml.YAMLError`` if
    the YAML is malformed, and ``pydantic.ValidationError`` if the structure
    does not match the contract schema.
    """

    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Schema contract not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ValueError(
            f"Schema contract {file_path} must be a YAML mapping, "
            f"got {type(raw).__name__}"
        )

    return SchemaContract.model_validate(raw)


def validate_contract(contract: SchemaContract) -> list[str]:
    """Return a list of human-readable warnings about contract consistency.

    An empty list means the contract is internally consistent. Detected issues:

    * a foreign key references a section that does not exist;
    * a foreign key references a column that does not exist in the target section;
    * a companion rule references a section that does not exist;
    * a section's ``id_column`` is not one of its declared columns;
    * duplicate section names.
    """

    warnings: list[str] = []

    section_by_name: dict[str, SectionDef] = {}
    for section in contract.sections:
        if section.name in section_by_name:
            warnings.append(f"Duplicate section name: '{section.name}'")
        else:
            section_by_name[section.name] = section

    for section in contract.sections:
        column_names = {column.name for column in section.columns}

        if section.id_column not in column_names:
            warnings.append(
                f"Section '{section.name}' id_column '{section.id_column}' "
                f"is not one of its columns"
            )

        for fk in section.foreign_keys:
            if fk.column not in column_names:
                warnings.append(
                    f"Section '{section.name}' foreign key column "
                    f"'{fk.column}' is not one of its columns"
                )

            target = section_by_name.get(fk.references_section)
            if target is None:
                warnings.append(
                    f"Section '{section.name}' foreign key references missing "
                    f"section '{fk.references_section}'"
                )
            elif fk.references_column not in {c.name for c in target.columns}:
                warnings.append(
                    f"Section '{section.name}' foreign key references missing "
                    f"column '{fk.references_column}' in section "
                    f"'{fk.references_section}'"
                )

        for companion in section.companions:
            companion_target = section_by_name.get(companion.requires_section)
            if companion_target is None:
                warnings.append(
                    f"Section '{section.name}' companion references missing "
                    f"section '{companion.requires_section}'"
                )
            elif companion.match_on not in {c.name for c in companion_target.columns}:
                warnings.append(
                    f"Section '{section.name}' companion match_on column "
                    f"'{companion.match_on}' is not in section "
                    f"'{companion.requires_section}'"
                )

    return warnings


def get_section(contract: SchemaContract, name: str) -> SectionDef | None:
    """Return the section named ``name``, or ``None`` if it does not exist."""

    for section in contract.sections:
        if section.name == name:
            return section
    return None


def get_id_column(contract: SchemaContract, section_name: str) -> str:
    """Return the id column for ``section_name``.

    Raises ``KeyError`` if the section is not declared in the contract.
    """

    section = get_section(contract, section_name)
    if section is None:
        raise KeyError(f"Unknown section: '{section_name}'")
    return section.id_column
