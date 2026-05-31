"""Persist and reload reconciliation snapshots for audit.

Each snapshot lives under ``snapshots/{deployment_id}/`` and records the full
report, the original base config text, and a small metadata file that always
includes the contract name and version that produced it.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from parser.schema_comparator import SchemaChange
from parser.integrity_checker import IntegrityViolation

from .reconciler import AgentFinding, ReconciliationReport


DEFAULT_SNAPSHOT_ROOT = Path(__file__).resolve().parent.parent / "snapshots"

_REPORT_FILE = "report.json"
_BASE_FILE = "base.txt"
_META_FILE = "meta.json"
_DECISIONS_FILE = "decisions.json"


class SnapshotError(RuntimeError):
    """Raised when a snapshot cannot be saved or loaded."""


def save_snapshot(
    report: ReconciliationReport,
    base_text: str,
    root: str | Path = DEFAULT_SNAPSHOT_ROOT,
) -> Path:
    """Persist ``report`` + ``base_text`` and return the snapshot directory path."""

    snapshot_dir = Path(root) / report.deployment_id
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        (snapshot_dir / _REPORT_FILE).write_text(
            json.dumps(asdict(report), indent=2), encoding="utf-8"
        )
        (snapshot_dir / _BASE_FILE).write_text(base_text, encoding="utf-8")

        meta = {
            "deployment_id": report.deployment_id,
            "contract_name": report.contract_name,
            "contract_version": report.contract_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": report.summary,
        }
        (snapshot_dir / _META_FILE).write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        raise SnapshotError(
            f"Failed to save snapshot for '{report.deployment_id}': {exc}"
        ) from exc

    return snapshot_dir


def load_snapshot(
    deployment_id: str,
    root: str | Path = DEFAULT_SNAPSHOT_ROOT,
) -> tuple[ReconciliationReport, str]:
    """Reload a previously saved snapshot as ``(report, base_text)``."""

    snapshot_dir = Path(root) / deployment_id
    report_path = snapshot_dir / _REPORT_FILE
    base_path = snapshot_dir / _BASE_FILE

    if not report_path.is_file() or not base_path.is_file():
        raise SnapshotError(f"Snapshot not found: '{deployment_id}'")

    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        base_text = base_path.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(
            f"Failed to load snapshot '{deployment_id}': {exc}"
        ) from exc

    report = ReconciliationReport(
        deployment_id=data["deployment_id"],
        contract_name=data["contract_name"],
        contract_version=data["contract_version"],
        findings=[AgentFinding(**item) for item in data.get("findings", [])],
        integrity_violations=[
            IntegrityViolation(**item)
            for item in data.get("integrity_violations", [])
        ],
        schema_changes=[
            SchemaChange(**item) for item in data.get("schema_changes", [])
        ],
        summary=data.get("summary", {}),
    )
    return report, base_text


def list_snapshots(root: str | Path = DEFAULT_SNAPSHOT_ROOT) -> list[dict]:
    """Return metadata for all snapshots, newest first (by created_at)."""

    root_path = Path(root)
    if not root_path.is_dir():
        return []

    snapshots: list[dict] = []
    for entry in root_path.iterdir():
        meta_path = entry / _META_FILE
        if not meta_path.is_file():
            continue
        try:
            snapshots.append(json.loads(meta_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue

    snapshots.sort(key=lambda meta: meta.get("created_at", ""), reverse=True)
    return snapshots


def load_decisions(
    deployment_id: str,
    root: str | Path = DEFAULT_SNAPSHOT_ROOT,
) -> dict:
    """Return the recorded approve/reject decisions for a snapshot."""

    decisions_path = Path(root) / deployment_id / _DECISIONS_FILE
    if not decisions_path.is_file():
        return {}
    try:
        return json.loads(decisions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def record_decision(
    deployment_id: str,
    finding_id: str,
    action: str,
    root: str | Path = DEFAULT_SNAPSHOT_ROOT,
) -> dict:
    """Record an approve/reject ``action`` for ``finding_id`` and return the record."""

    snapshot_dir = Path(root) / deployment_id
    if not snapshot_dir.is_dir():
        raise SnapshotError(f"Snapshot not found: '{deployment_id}'")

    decisions = load_decisions(deployment_id, root=root)
    record = {
        "finding_id": finding_id,
        "action": action,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    decisions[finding_id] = record

    try:
        (snapshot_dir / _DECISIONS_FILE).write_text(
            json.dumps(decisions, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        raise SnapshotError(
            f"Failed to record decision for '{deployment_id}': {exc}"
        ) from exc

    return record
