"""Referential and companion integrity checks, driven by the contract.

All checks are derived by iterating ``contract.sections`` and their declared
``foreign_keys`` / ``companions``. No section or column name is hardcoded.
"""

from __future__ import annotations

from dataclasses import dataclass

from schema.contract_models import SchemaContract, SectionDef


@dataclass
class IntegrityViolation:
    """A single referential or companion integrity problem for one row."""

    section: str
    row_id: str | None
    violation_type: str  # FK_VIOLATION | COMPANION_VIOLATION
    message: str


def check_integrity(
    sections: dict[str, list[dict]],
    contract: SchemaContract,
) -> list[IntegrityViolation]:
    """Validate every foreign-key and companion rule declared in the contract."""

    violations: list[IntegrityViolation] = []

    for section_def in contract.sections:
        rows = sections.get(section_def.name, [])
        violations.extend(_check_foreign_keys(section_def, rows, sections))
        violations.extend(_check_companions(section_def, rows, sections))

    return violations


def _check_foreign_keys(
    section_def: SectionDef,
    rows: list[dict],
    sections: dict[str, list[dict]],
) -> list[IntegrityViolation]:
    violations: list[IntegrityViolation] = []

    for fk in section_def.foreign_keys:
        target_rows = sections.get(fk.references_section, [])
        valid_values = {
            target_row[fk.references_column]
            for target_row in target_rows
            if fk.references_column in target_row
            and target_row[fk.references_column] not in (None, "")
        }

        for row in rows:
            value = row.get(fk.column)
            if value in (None, ""):
                continue
            if value not in valid_values:
                violations.append(
                    IntegrityViolation(
                        section=section_def.name,
                        row_id=row.get(section_def.id_column),
                        violation_type="FK_VIOLATION",
                        message=(
                            f"{section_def.name}.{fk.column}='{value}' has no "
                            f"matching {fk.references_section}.{fk.references_column}"
                        ),
                    )
                )

    return violations


def _check_companions(
    section_def: SectionDef,
    rows: list[dict],
    sections: dict[str, list[dict]],
) -> list[IntegrityViolation]:
    violations: list[IntegrityViolation] = []

    for companion in section_def.companions:
        companion_rows = sections.get(companion.requires_section, [])
        companion_values = {
            companion_row[companion.match_on]
            for companion_row in companion_rows
            if companion.match_on in companion_row
            and companion_row[companion.match_on] not in (None, "")
        }

        for row in rows:
            value = row.get(companion.match_on)
            if value in (None, ""):
                continue
            if value not in companion_values:
                violations.append(
                    IntegrityViolation(
                        section=section_def.name,
                        row_id=row.get(section_def.id_column),
                        violation_type="COMPANION_VIOLATION",
                        message=(
                            f"{section_def.name} row with {companion.match_on}="
                            f"'{value}' has no companion in "
                            f"{companion.requires_section}"
                        ),
                    )
                )

    return violations
