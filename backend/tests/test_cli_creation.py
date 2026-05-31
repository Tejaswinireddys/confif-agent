"""Tests for creation-related CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import cli
from api import contract_store


EXAMPLE_CONTRACT = (
    Path(__file__).resolve().parent.parent / "schemas" / "example_contract.yaml"
)

CLUSTER_COLS = ["cluster_id", "cluster_name", "tier"]
NODE_COLS = ["node_id", "hostname", "cluster_ref", "enabled"]
IFACE_COLS = ["interface_id", "node_id", "ip_address", "listen_port"]


def render(sections: list[tuple[str, list[str], list[dict]]]) -> str:
    lines: list[str] = []
    for name, columns, rows in sections:
        lines.append("," + ",".join(columns))
        lines.append(f"start_{name}")
        for row in rows:
            lines.append("," + ",".join(str(row[col]) for col in columns))
        lines.append(f"end_{name}")
    return "\n".join(lines) + "\n"


def cluster(cid, name="prod", tier="gold"):
    return {"cluster_id": cid, "cluster_name": name, "tier": tier}


def node(nid, host="host", ref="1", enabled="true"):
    return {"node_id": nid, "hostname": host, "cluster_ref": ref, "enabled": enabled}


def iface(iid, nid="1", ip="10.0.0.1", port="8080"):
    return {
        "interface_id": iid,
        "node_id": nid,
        "ip_address": ip,
        "listen_port": port,
    }


@pytest.fixture
def contract_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(contract_store, "DEFAULT_CONTRACTS_DIR", tmp_path)
    contract_store.save_contract(
        "example_generic_network",
        "1.0.0",
        EXAMPLE_CONTRACT.read_text(encoding="utf-8"),
        root=tmp_path,
    )
    return tmp_path


@pytest.fixture
def config_files(tmp_path):
    old_path = tmp_path / "old.cfg"
    new_path = tmp_path / "new.cfg"
    old_path.write_text(
        render(
            [
                ("clusters", CLUSTER_COLS, [cluster("1")]),
                ("nodes", NODE_COLS, [node("1", host="host-a")]),
                ("interfaces", IFACE_COLS, [iface("1", "1")]),
            ]
        ),
        encoding="utf-8",
    )
    new_path.write_text(
        render(
            [
                ("clusters", CLUSTER_COLS, [cluster("1")]),
                (
                    "nodes",
                    NODE_COLS,
                    [node("1", host="host-a"), node("2", host="host-b")],
                ),
                (
                    "interfaces",
                    IFACE_COLS,
                    [iface("1", "1"), iface("2", "2", ip="10.0.0.2")],
                ),
            ]
        ),
        encoding="utf-8",
    )
    return old_path, new_path


def test_explain_plan_prints_provenance(contract_registry, config_files, capsys):
    old_path, new_path = config_files
    code = cli.main(
        [
            "explain-plan",
            "--contract",
            "example_generic_network",
            "--old",
            str(old_path),
            "--new",
            str(new_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Merge plan" in out
    assert "from_new_file" in out
    assert "RESULT: READY FOR APPROVAL" in out


def test_create_happy_path_writes_merged(
    contract_registry, config_files, tmp_path, capsys
):
    old_path, new_path = config_files
    out_path = tmp_path / "merged.cfg"
    code = cli.main(
        [
            "create",
            "--contract",
            "example_generic_network",
            "--old",
            str(old_path),
            "--new",
            str(new_path),
            "--out",
            str(out_path),
        ]
    )
    captured = capsys.readouterr().out
    assert code == 0
    assert out_path.is_file()
    assert "RESULT: ACCEPTED" in captured
    assert "Changelog:" in captured
    text = out_path.read_text(encoding="utf-8")
    assert ",2,host-b,1,true" in text
    assert ",2,2,10.0.0.2,8080" in text


def test_create_missing_inputs_exits_2(contract_registry, config_files, capsys):
    old_path, new_path = config_files
    new_path.write_text(
        render(
            [
                ("clusters", CLUSTER_COLS, [cluster("1")]),
                (
                    "nodes",
                    NODE_COLS,
                    [node("1", host="host-a"), node("2", host="host-b")],
                ),
                (
                    "interfaces",
                    IFACE_COLS,
                    [iface("1", "1"), iface("2", "2", ip="")],
                ),
            ]
        ),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "create",
            "--contract",
            "example_generic_network",
            "--old",
            str(old_path),
            "--new",
            str(new_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == 2
    payload = json.loads(out)
    assert payload["human_inputs_needed"]
    assert "add-row-interfaces-2" in payload["inputs"]


def test_create_with_inputs_accepted(
    contract_registry, config_files, tmp_path, capsys
):
    old_path, new_path = config_files
    new_path.write_text(
        render(
            [
                ("clusters", CLUSTER_COLS, [cluster("1")]),
                (
                    "nodes",
                    NODE_COLS,
                    [node("1", host="host-a"), node("2", host="host-b")],
                ),
                (
                    "interfaces",
                    IFACE_COLS,
                    [iface("1", "1"), iface("2", "2", ip="")],
                ),
            ]
        ),
        encoding="utf-8",
    )

    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(
        json.dumps(
            {
                "add-row-interfaces-2": {
                    "interface_id": "2",
                    "node_id": "2",
                    "ip_address": "10.0.0.99",
                    "listen_port": "8080",
                }
            }
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "merged.cfg"

    code = cli.main(
        [
            "create",
            "--contract",
            "example_generic_network",
            "--old",
            str(old_path),
            "--new",
            str(new_path),
            "--inputs",
            str(inputs_path),
            "--out",
            str(out_path),
        ]
    )
    captured = capsys.readouterr().out
    assert code == 0
    assert out_path.is_file()
    assert "human_supplied" in captured
    assert "10.0.0.99" in out_path.read_text(encoding="utf-8")


def test_create_blocked_exits_1(contract_registry, config_files, capsys):
    old_path, new_path = config_files
    new_path.write_text(
        render(
            [
                ("clusters", CLUSTER_COLS, [cluster("1")]),
                ("nodes", NODE_COLS, [node("1", host="host-a")]),
                (
                    "interfaces",
                    IFACE_COLS,
                    [iface("1", "1"), iface("5", "999", ip="10.0.0.5")],
                ),
            ]
        ),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "create",
            "--contract",
            "example_generic_network",
            "--old",
            str(old_path),
            "--new",
            str(new_path),
        ]
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "REJECTED" in err
