"""Decision-branch coverage for the core reconciler.

Configs are rendered in the exact layout described by example_contract.yaml
(header-before-start, leading empty field, start_/end_ markers). Thresholds are
read from the contract, never hardcoded in the engine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from schema.contract_loader import load_contract
from intent.ai_extractor import IntentSummary
from intent.diff_reader import DeclaredChange
from agent.reconciler import (
    AUTO_APPLY,
    BLOCK,
    ESCALATE,
    SUGGEST,
    Reconciler,
)


EXAMPLE_CONTRACT = (
    Path(__file__).resolve().parent.parent / "schemas" / "example_contract.yaml"
)

CLUSTER_COLS = ["cluster_id", "cluster_name", "tier"]
NODE_COLS = ["node_id", "hostname", "cluster_ref", "enabled"]
IFACE_COLS = ["interface_id", "node_id", "ip_address", "listen_port"]


@pytest.fixture
def contract():
    return load_contract(EXAMPLE_CONTRACT)


def render(sections: list[tuple[str, list[str], list[dict]]]) -> str:
    """Render sections to the example contract's on-disk format."""

    lines: list[str] = []
    for name, columns, rows in sections:
        lines.append("," + ",".join(columns))
        lines.append(f"start_{name}")
        for row in rows:
            lines.append("," + ",".join(str(row[col]) for col in columns))
        lines.append(f"end_{name}")
    return "\n".join(lines) + "\n"


def find(report, **criteria):
    for finding in report.findings:
        if all(getattr(finding, key) == value for key, value in criteria.items()):
            return finding
    return None


# Reusable single-row baselines.
ONE_CLUSTER = ("clusters", CLUSTER_COLS, [{"cluster_id": "1", "cluster_name": "prod", "tier": "gold"}])
ONE_NODE = ("nodes", NODE_COLS, [{"node_id": "1", "hostname": "host-a", "cluster_ref": "1", "enabled": "true"}])
ONE_IFACE = ("interfaces", IFACE_COLS, [{"interface_id": "1", "node_id": "1", "ip_address": "10.0.0.1", "listen_port": "8080"}])


def test_declared_addition_low_blast_auto_applies(contract):
    base = render([ONE_CLUSTER, ONE_NODE, ONE_IFACE])
    new = render([
        ONE_CLUSTER,
        ONE_NODE,
        ("interfaces", IFACE_COLS, [
            {"interface_id": "1", "node_id": "1", "ip_address": "10.0.0.1", "listen_port": "8080"},
            {"interface_id": "3", "node_id": "1", "ip_address": "10.0.0.3", "listen_port": "8082"},
        ]),
    ])
    intent = IntentSummary(
        declared_additions=[
            {"section": "interfaces", "row_hint": "add interface 3 to node 1", "confidence": "clear"}
        ]
    )
    declared = [DeclaredChange("interfaces", "ADD", ",3,1,10.0.0.3,8082")]

    report = Reconciler().reconcile(base, new, intent, declared, contract)
    finding = find(report, section="interfaces", row_id="3", change_type="ADDED")

    assert finding is not None
    assert finding.in_jira_ticket and finding.in_code_diff
    assert finding.fk_valid and finding.companion_rows_present
    assert finding.blast_radius == 0
    assert finding.decision == AUTO_APPLY


def test_undeclared_removal_blocks(contract):
    base = render([
        ("clusters", CLUSTER_COLS, [
            {"cluster_id": "1", "cluster_name": "prod", "tier": "gold"},
            {"cluster_id": "2", "cluster_name": "dev", "tier": "silver"},
        ]),
        ONE_NODE,
        ONE_IFACE,
    ])
    new = render([ONE_CLUSTER, ONE_NODE, ONE_IFACE])

    report = Reconciler().reconcile(base, new, IntentSummary(), [], contract)
    finding = find(report, section="clusters", row_id="2", change_type="REMOVED")

    assert finding is not None
    assert finding.decision == BLOCK


def test_undeclared_modify_high_blast_blocks(contract):
    nodes = [
        {"node_id": str(i), "hostname": f"host-{i}", "cluster_ref": "1", "enabled": "true"}
        for i in range(1, 5)
    ]
    ifaces = [
        {"interface_id": str(i), "node_id": str(i), "ip_address": f"10.0.0.{i}", "listen_port": "8080"}
        for i in range(1, 5)
    ]
    base = render([ONE_CLUSTER, ("nodes", NODE_COLS, nodes), ("interfaces", IFACE_COLS, ifaces)])
    new = render([
        ("clusters", CLUSTER_COLS, [{"cluster_id": "1", "cluster_name": "prod", "tier": "silver"}]),
        ("nodes", NODE_COLS, nodes),
        ("interfaces", IFACE_COLS, ifaces),
    ])

    report = Reconciler().reconcile(base, new, IntentSummary(), [], contract)
    finding = find(report, section="clusters", row_id="1", change_type="MODIFIED")

    assert finding is not None
    # 4 nodes reference cluster 1 -> blast radius 4 > block threshold (3).
    assert finding.blast_radius == 4
    assert finding.decision == BLOCK


def test_broken_fk_blocks(contract):
    base = render([ONE_CLUSTER, ONE_NODE, ONE_IFACE])
    new = render([
        ONE_CLUSTER,
        ("nodes", NODE_COLS, [{"node_id": "1", "hostname": "host-a", "cluster_ref": "99", "enabled": "true"}]),
        ONE_IFACE,
    ])

    report = Reconciler().reconcile(base, new, IntentSummary(), [], contract)
    finding = find(report, section="nodes", row_id="1", change_type="MODIFIED")

    assert finding is not None
    assert finding.fk_valid is False
    assert finding.decision == BLOCK


def test_column_removed_on_fk_referenced_section_blocks(contract):
    # 'clusters' is referenced by nodes.cluster_ref, so dropping a column blocks.
    base = render([ONE_CLUSTER, ONE_NODE, ONE_IFACE])
    new = render([
        ("clusters", ["cluster_id", "cluster_name"], [{"cluster_id": "1", "cluster_name": "prod"}]),
        ONE_NODE,
        ONE_IFACE,
    ])

    report = Reconciler().reconcile(base, new, IntentSummary(), [], contract)
    finding = find(report, section="clusters", change_type="COLUMN_REMOVED")

    assert finding is not None
    assert finding.base_value == "tier"
    assert finding.decision == BLOCK


def test_column_removed_on_unreferenced_section_escalates(contract):
    # 'interfaces' is not referenced by any FK -> escalate rather than block.
    base = render([ONE_CLUSTER, ONE_NODE, ONE_IFACE])
    new = render([
        ONE_CLUSTER,
        ONE_NODE,
        ("interfaces", ["interface_id", "node_id", "ip_address"],
         [{"interface_id": "1", "node_id": "1", "ip_address": "10.0.0.1"}]),
    ])

    report = Reconciler().reconcile(base, new, IntentSummary(), [], contract)
    finding = find(report, section="interfaces", change_type="COLUMN_REMOVED")

    assert finding is not None
    assert finding.decision == ESCALATE


def test_column_added_suggests(contract):
    base = render([ONE_CLUSTER, ONE_NODE, ONE_IFACE])
    new = render([
        ONE_CLUSTER,
        ONE_NODE,
        ("interfaces", IFACE_COLS + ["mtu"],
         [{"interface_id": "1", "node_id": "1", "ip_address": "10.0.0.1", "listen_port": "8080", "mtu": "1500"}]),
    ])

    report = Reconciler().reconcile(base, new, IntentSummary(), [], contract)
    finding = find(report, section="interfaces", change_type="COLUMN_ADDED")

    assert finding is not None
    assert finding.new_value == "mtu"
    assert finding.decision == SUGGEST


def test_undeclared_addition_escalates(contract):
    base = render([ONE_CLUSTER, ONE_NODE, ONE_IFACE])
    new = render([
        ONE_CLUSTER,
        ONE_NODE,
        ("interfaces", IFACE_COLS, [
            {"interface_id": "1", "node_id": "1", "ip_address": "10.0.0.1", "listen_port": "8080"},
            {"interface_id": "3", "node_id": "1", "ip_address": "10.0.0.3", "listen_port": "8082"},
        ]),
    ])

    report = Reconciler().reconcile(base, new, IntentSummary(), [], contract)
    finding = find(report, section="interfaces", row_id="3", change_type="ADDED")

    assert finding is not None
    assert not finding.in_jira_ticket and not finding.in_code_diff
    assert finding.decision == ESCALATE


def test_auto_apply_disabled_caps_at_suggest(contract):
    disabled_thresholds = contract.thresholds.model_copy(update={"allow_auto_apply": False})
    disabled_contract = contract.model_copy(update={"thresholds": disabled_thresholds})

    base = render([ONE_CLUSTER, ONE_NODE, ONE_IFACE])
    new = render([
        ONE_CLUSTER,
        ONE_NODE,
        ("interfaces", IFACE_COLS, [
            {"interface_id": "1", "node_id": "1", "ip_address": "10.0.0.1", "listen_port": "8080"},
            {"interface_id": "3", "node_id": "1", "ip_address": "10.0.0.3", "listen_port": "8082"},
        ]),
    ])
    intent = IntentSummary(
        declared_additions=[
            {"section": "interfaces", "row_hint": "add interface 3", "confidence": "clear"}
        ]
    )
    declared = [DeclaredChange("interfaces", "ADD", ",3,1,10.0.0.3,8082")]

    report = Reconciler().reconcile(base, new, intent, declared, disabled_contract)
    finding = find(report, section="interfaces", row_id="3", change_type="ADDED")

    assert finding is not None
    # All AUTO_APPLY criteria are met, but the contract disables auto-apply.
    assert finding.decision == SUGGEST
