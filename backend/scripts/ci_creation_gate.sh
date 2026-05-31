#!/usr/bin/env bash
# CI gate for the creation CLI: exercises op_id-keyed human inputs end-to-end.
#
# Exit codes (same as cli.py create):
#   0 — merged file accepted
#   1 — blocked / re-review rejected
#   2 — human inputs required (prints JSON with op_id keys)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"
PY="${ROOT}/backend/venv/bin/python"
CLI="${ROOT}/backend/cli.py"
CONTRACT="example_generic_network"
FIX="${ROOT}/backend/fixtures/creation"
WORK="${ROOT}/backend/.ci-creation-work"

mkdir -p "${ROOT}/backend/contracts" "${WORK}"

# Register the example contract for CLI lookups.
"${PY}" - <<'PY'
from pathlib import Path
import sys

sys.path.insert(0, str(Path("backend").resolve()))
from api import contract_store

yaml_text = Path("backend/schemas/example_contract.yaml").read_text(encoding="utf-8")
contract_store.save_contract(
    "example_generic_network",
    "1.0.0",
    yaml_text,
    root=Path("backend/contracts"),
)
print("Registered contract: example_generic_network v1.0.0")
PY

echo "==> explain-plan (sanity)"
"${PY}" "${CLI}" explain-plan \
  --contract "${CONTRACT}" \
  --old "${FIX}/old.cfg" \
  --new "${FIX}/new-complete.cfg"

echo "==> create happy path (no human inputs)"
MERGED="${WORK}/merged-complete.cfg"
"${PY}" "${CLI}" create \
  --contract "${CONTRACT}" \
  --old "${FIX}/old.cfg" \
  --new "${FIX}/new-complete.cfg" \
  --out "${MERGED}"
test -s "${MERGED}"
grep -q ",2,host-b,1,true" "${MERGED}"
grep -q ",2,2,10.0.0.2,8080" "${MERGED}"

echo "==> create without inputs (expect exit 2 + op_id JSON)"
set +e
NEEDS_JSON="${WORK}/needs-input.json"
"${PY}" "${CLI}" create \
  --contract "${CONTRACT}" \
  --old "${FIX}/old.cfg" \
  --new "${FIX}/new-needs-input.cfg" \
  > "${NEEDS_JSON}" 2>"${WORK}/needs-input.err"
CODE=$?
set -e

if [[ "${CODE}" -ne 2 ]]; then
  echo "expected exit 2 when human inputs missing, got ${CODE}" >&2
  cat "${WORK}/needs-input.err" >&2 || true
  exit 1
fi

echo "==> verify op_id keys in required-inputs JSON"
"${PY}" - <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path("backend/.ci-creation-work/needs-input.json").read_text())
assert payload.get("human_inputs_needed"), "missing human_inputs_needed"
inputs = payload.get("inputs") or {}
assert inputs, "missing inputs template"
op_id = "add-row-interfaces-2"
assert op_id in inputs, f"expected op_id {op_id!r} in inputs, got {list(inputs)}"
assert "ip_address" in inputs[op_id], "inputs template must include ip_address"
print(f"op_id ok: {op_id}")
PY

echo "==> fill inputs by op_id and re-run create"
INPUTS="${WORK}/inputs.json"
"${PY}" - <<'PY'
import json
from pathlib import Path

needs = json.loads(
    Path("backend/.ci-creation-work/needs-input.json").read_text(encoding="utf-8")
)
inputs = dict(needs["inputs"])
op_id = "add-row-interfaces-2"
inputs[op_id]["ip_address"] = "10.0.0.99"
Path("backend/.ci-creation-work/inputs.json").write_text(
    json.dumps(inputs, indent=2) + "\n",
    encoding="utf-8",
)
print(f"Wrote inputs for {op_id}")
PY

MERGED2="${WORK}/merged-with-inputs.cfg"
"${PY}" "${CLI}" create \
  --contract "${CONTRACT}" \
  --old "${FIX}/old.cfg" \
  --new "${FIX}/new-needs-input.cfg" \
  --inputs "${INPUTS}" \
  --out "${MERGED2}"
grep -q "10.0.0.99" "${MERGED2}"

echo "==> idempotent re-run (same plan, same old → identical output)"
MERGED3="${WORK}/merged-rerun.cfg"
"${PY}" "${CLI}" create \
  --contract "${CONTRACT}" \
  --old "${FIX}/old.cfg" \
  --new "${FIX}/new-complete.cfg" \
  --out "${MERGED3}"
cmp -s "${MERGED}" "${MERGED3}"

echo "CREATION GATE: OK"
