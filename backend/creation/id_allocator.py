"""Deterministic id allocation for newly created rows.

Allocation is driven entirely by ``section_def.id_naming_rule`` and is always
deterministic: no randomness, no AI. Strategies that cannot be derived
mechanically (opaque / semantic ids such as hostnames or realm-encoded names)
raise :class:`NeedsHumanInput` rather than guessing.
"""

from __future__ import annotations

import re
from typing import Iterable

from schema.contract_models import SchemaContract
from schema.contract_loader import get_section


class NeedsHumanInput(Exception):
    """Raised when an id cannot be allocated deterministically."""


_SUFFIX_RE = re.compile(r"^(.*?)(\d+)$")


def allocate_id(
    section: str,
    contract: SchemaContract,
    existing_old: Iterable[str],
    planned: Iterable[str],
) -> str:
    """Allocate the next id for ``section`` given existing and planned ids.

    ``existing_old`` and ``planned`` are iterables of id values (strings).
    """

    section_def = get_section(contract, section)
    if section_def is None:
        raise KeyError(f"Unknown section: '{section}'")

    rule = section_def.id_naming_rule
    ids = [str(value) for value in [*existing_old, *planned] if value not in (None, "")]

    if rule == "sequential_int":
        return _allocate_sequential_int(ids)
    if rule == "numeric_suffix":
        return _allocate_numeric_suffix(section_def.name, ids)

    raise NeedsHumanInput(
        f"Section '{section}' uses id_naming_rule '{rule}', which is not "
        f"mechanically derivable; a human must supply the id"
    )


def _allocate_sequential_int(ids: list[str]) -> str:
    numbers = [int(value) for value in ids if _is_int(value)]
    return str((max(numbers) if numbers else 0) + 1)


def _allocate_numeric_suffix(section_name: str, ids: list[str]) -> str:
    matches = [(m.group(1), m.group(2)) for m in (_SUFFIX_RE.match(i) for i in ids) if m]
    if not matches:
        raise NeedsHumanInput(
            f"Cannot derive a numeric-suffix id for section '{section_name}': "
            f"no existing id matches the '<prefix><number>' pattern"
        )

    prefixes = {prefix for prefix, _ in matches}
    if len(prefixes) > 1:
        raise NeedsHumanInput(
            f"Cannot derive a numeric-suffix id for section '{section_name}': "
            f"inconsistent prefixes {sorted(prefixes)}"
        )

    prefix = next(iter(prefixes))
    max_prefix, max_suffix = max(matches, key=lambda pair: int(pair[1]))
    width = len(max_suffix)
    next_number = int(max_suffix) + 1
    return f"{prefix}{str(next_number).zfill(width)}"


def _is_int(value: str) -> bool:
    text = str(value).strip()
    if text.startswith("-"):
        text = text[1:]
    return text.isdigit()
