"""Synthetic end-to-end reconciliation run against the example contract.

Builds a base/new config pair with exactly two changes:

* a DECLARED addition (a new cluster that several existing nodes reference, so
  its blast radius pushes it to SUGGEST), and
* an UNDECLARED removal (an interface deleted with no ticket/diff evidence,
  which BLOCKs).

Expected outcome: 1 SUGGEST + 1 BLOCK.

Run from the backend/ directory:  python scripts/test_run.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from schema.contract_loader import load_contract
from intent.ai_extractor import IntentSummary
from intent.diff_reader import DeclaredChange
from agent.reconciler import BLOCK, SUGGEST, Reconciler

CONTRACT_PATH = BACKEND_DIR / "schemas" / "example_contract.yaml"

CLUSTER_COLS = ["cluster_id", "cluster_name", "tier"]
NODE_COLS = ["node_id", "hostname", "cluster_ref", "enabled"]
IFACE_COLS = ["interface_id", "node_id", "ip_address", "listen_port"]


def render(sections) -> str:
    lines: list[str] = []
    for name, columns, rows in sections:
        lines.append("," + ",".join(columns))
        lines.append(f"start_{name}")
        for row in rows:
            lines.append("," + ",".join(str(row[col]) for col in columns))
        lines.append(f"end_{name}")
    return "\n".join(lines) + "\n"


def build_configs() -> tuple[str, str]:
    # Five nodes all reference cluster 2; cluster 2 only exists in the NEW
    # config (it is the declared addition). Each node has a companion interface.
    nodes = [
        {"node_id": str(i), "hostname": f"host-{i}", "cluster_ref": "2", "enabled": "true"}
        for i in range(1, 6)
    ]
    interfaces = [
        {"interface_id": str(i), "node_id": str(i), "ip_address": f"10.0.0.{i}", "listen_port": "8080"}
        for i in range(1, 6)
    ]

    base = render(
        [
            ("clusters", CLUSTER_COLS, [{"cluster_id": "1", "cluster_name": "prod", "tier": "gold"}]),
            ("nodes", NODE_COLS, nodes),
            ("interfaces", IFACE_COLS, interfaces),
        ]
    )
    new = render(
        [
            (
                "clusters",
                CLUSTER_COLS,
                [
                    {"cluster_id": "1", "cluster_name": "prod", "tier": "gold"},
                    {"cluster_id": "2", "cluster_name": "staging", "tier": "silver"},
                ],
            ),
            ("nodes", NODE_COLS, nodes),
            # interface 5 removed (undeclared).
            ("interfaces", IFACE_COLS, interfaces[:-1]),
        ]
    )
    return base, new


def main() -> int:
    contract = load_contract(CONTRACT_PATH)
    base, new = build_configs()

    intent = IntentSummary(
        declared_additions=[
            {"section": "clusters", "row_hint": "add cluster 2 (staging)", "confidence": "clear"}
        ]
    )
    declared_changes = [DeclaredChange("clusters", "ADD", ",2,staging,silver")]

    report = Reconciler().reconcile(base, new, intent, declared_changes, contract)

    print(f"deployment_id : {report.deployment_id}")
    print(f"contract      : {report.contract_name} v{report.contract_version}")
    print(f"summary       : {report.summary}")
    print("findings:")
    for finding in report.findings:
        print(
            f"  - [{finding.decision:10}] {finding.section}/{finding.change_type}"
            f" id={finding.row_id} blast={finding.blast_radius} :: {finding.reason}"
        )

    decisions = [finding.decision for finding in report.findings]
    suggest_count = decisions.count(SUGGEST)
    block_count = decisions.count(BLOCK)

    ok = len(report.findings) == 2 and suggest_count == 1 and block_count == 1
    print()
    print(
        f"RESULT: {'PASS' if ok else 'FAIL'} "
        f"(expected 1 SUGGEST + 1 BLOCK; got {suggest_count} SUGGEST, "
        f"{block_count} BLOCK, {len(report.findings)} total)"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
