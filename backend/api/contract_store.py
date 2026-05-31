"""File-based registry of schema contracts.

Contracts are stored as ``contracts/{name}_{version}.yaml`` so multiple teams
can register and use their own contracts side by side. The canonical name and
version are read back from the YAML content (not the filename) so lookups stay
correct even when characters are sanitized for the filesystem.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


DEFAULT_CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _safe(value: str) -> str:
    return _SAFE.sub("_", value)


def _iter_contracts(root: Path):
    """Yield ``(path, data)`` for every parseable YAML contract under ``root``."""

    if not root.is_dir():
        return
    for path in sorted(root.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict) and data.get("contract_name"):
            yield path, data


def _version_key(version: str):
    """Sort key that orders dotted numeric versions naturally, else lexically."""

    parts = []
    for chunk in str(version).split("."):
        parts.append((0, int(chunk)) if chunk.isdigit() else (1, chunk))
    return parts


def save_contract(
    name: str,
    version: str,
    yaml_text: str,
    root: str | Path = DEFAULT_CONTRACTS_DIR,
) -> Path:
    """Persist ``yaml_text`` as ``{name}_{version}.yaml`` and return its path."""

    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    path = root_path / f"{_safe(name)}_{_safe(version)}.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return path


def get_contract(
    name: str,
    version: str | None = None,
    root: str | Path = DEFAULT_CONTRACTS_DIR,
) -> Path | None:
    """Return the path to a contract by ``name`` (and optional ``version``).

    When ``version`` is omitted the highest version registered for ``name`` is
    returned. Returns ``None`` if no match exists.
    """

    matches: list[tuple[str, Path]] = []
    for path, data in _iter_contracts(Path(root)):
        if data.get("contract_name") != name:
            continue
        contract_version = str(data.get("version", ""))
        if version is not None and contract_version != version:
            continue
        matches.append((contract_version, path))

    if not matches:
        return None
    matches.sort(key=lambda item: _version_key(item[0]))
    return matches[-1][1]


def list_contracts(root: str | Path = DEFAULT_CONTRACTS_DIR) -> list[dict]:
    """Return summary metadata for every registered contract."""

    contracts: list[dict] = []
    for path, data in _iter_contracts(Path(root)):
        sections = data.get("sections") or []
        contracts.append(
            {
                "name": data.get("contract_name"),
                "version": str(data.get("version", "")),
                "section_count": len(sections) if isinstance(sections, list) else 0,
                "path": str(path),
            }
        )
    return contracts


def delete_contract(
    name: str,
    version: str | None = None,
    root: str | Path = DEFAULT_CONTRACTS_DIR,
) -> bool:
    """Delete matching contract file(s). Returns True if anything was removed."""

    removed = False
    for path, data in list(_iter_contracts(Path(root))):
        if data.get("contract_name") != name:
            continue
        if version is not None and str(data.get("version", "")) != version:
            continue
        try:
            path.unlink()
            removed = True
        except OSError:
            continue
    return removed
