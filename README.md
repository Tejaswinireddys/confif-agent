# Config Reconciler

A **schema-driven** configuration reconciliation engine. It compares two versions
of a configuration file, cross-checks the change against the *declared intent*
(a Jira ticket and/or a code diff), validates referential integrity, and assigns
each change a decision: **AUTO_APPLY**, **SUGGEST**, **ESCALATE**, or **BLOCK**.

The engine contains **no hardcoded field, section, file, or table names**.
Everything specific to a customer's configuration comes from a YAML *schema
contract* that the team provides. That is what makes the same engine reusable
across many teams with completely different config formats.

---

## The schema contract concept

A **schema contract** is a YAML file that tells the engine how to understand a
particular config format. It declares:

- **file_format** — delimiter, section markers, header placement, etc.
- **sections** — the logical tables in the file, each with an `id_column`,
  typed `columns`, and a plain-English `description`.
- **foreign_keys** — which columns reference rows in other sections.
- **companions** — rows that must be accompanied by a matching row elsewhere.
- **thresholds** — the policy knobs that drive the decision logic.

The engine reads sections and columns *only* through the contract, so onboarding
a new team is a matter of writing a contract — not changing code.

See [`docs/WRITING_A_CONTRACT.md`](docs/WRITING_A_CONTRACT.md) for a full guide,
and [`backend/schemas/templates/`](backend/schemas/templates/) for starting points.

---

## Architecture

```
backend/
  schema/      Pydantic contract models + loader/validator
  parser/      Contract-driven parser, diff engine, schema comparator, integrity checker
  intent/      Jira reader, git-diff reader, Claude-based intent extractor
  agent/       Reconciler (decision engine), snapshots (audit), AI validator
  api/         FastAPI app + file-based multi-contract registry
  cli.py       Headless CLI (gates CI/CD)
  schemas/     example_contract.yaml + templates/
frontend/      React + TypeScript + Tailwind review UI
```

---

## Setup

**Prerequisites:** Python 3.11+, Node 18+, (optional) Docker.

```bash
make install          # backend venv + deps, frontend npm install
cp .env.example .env  # then fill in credentials (see below)
```

### Environment variables

| Variable            | Required for            | Description                                  |
| ------------------- | ----------------------- | -------------------------------------------- |
| `ANTHROPIC_API_KEY` | Jira/AI intent, AI validator | Anthropic Claude API key                |
| `JIRA_URL`          | `--jira` reconciliation | Base URL, e.g. `https://org.atlassian.net`   |
| `JIRA_EMAIL`        | `--jira` reconciliation | Account email for basic auth                 |
| `JIRA_API_TOKEN`    | `--jira` reconciliation | Jira API token                               |

Reconciling with only config files (no Jira ticket, no diff) needs **no**
credentials — it runs in "diff-only" mode where every change is treated as
undeclared.

---

## Running

### Local

```bash
make backend     # API on http://localhost:8000
make frontend    # UI  on http://localhost:3000
make test        # backend pytest + frontend tests
make sample      # synthetic end-to-end reconcile
```

### Docker

```bash
cp .env.example .env
make run         # docker compose up --build  (backend :8000, frontend :3000)
```

The `contracts/` registry and `snapshots/` audit trail are mounted as host
volumes so they persist across restarts.

### CLI (headless / CI-CD)

```bash
# Validate a contract before registering it
python backend/cli.py validate-contract --file backend/schemas/example_contract.yaml

# List registered contracts
python backend/cli.py list-contracts

# Reconcile two config versions (exits non-zero if any finding is BLOCK)
python backend/cli.py reconcile \
    --contract example_generic_network \
    --base old.cfg --new new.cfg \
    [--jira NET-1234] [--diff change.diff]
```

Because `reconcile` exits non-zero on any **BLOCK**, you can drop it straight
into a pipeline as a gate.

---

## Onboarding a new team

1. **Write a contract.** Start from a template in `backend/schemas/templates/`
   (`flat_csv_template.yaml`, `multi_section_template.yaml`, or
   `relational_template.yaml`). Follow
   [`docs/WRITING_A_CONTRACT.md`](docs/WRITING_A_CONTRACT.md).
2. **Validate it.** `make validate FILE=path/to/contract.yaml` (or the CLI).
   Fix any warnings it reports.
3. **Register it.** Upload via the UI's "Upload new contract" panel, or
   `POST /contracts` with the YAML. It is stored as
   `contracts/{name}_{version}.yaml`.
4. **Reconcile.** Select the contract in the UI and upload a base + new config,
   or run the CLI in CI. Optionally attach a Jira ticket and/or a diff so
   changes can be matched to declared intent.
5. **Review & apply.** Approve/reject SUGGEST and ESCALATE findings; BLOCK and
   AUTO_APPLY are determined automatically. Every run is snapshotted with its
   contract name + version for audit.

Multiple teams coexist: each registers its own contract(s) by name and version,
and reconciliations always run against the contract you select.

---

## Decision logic

Decisions are evaluated in priority order (the first matching rule wins). `t`
refers to `contract.thresholds`. "Declared" means the change appears in the Jira
ticket **or** the diff. "Blast radius" is the number of rows in other sections
that reference this row via the contract's foreign keys.

| Priority | Decision     | Condition                                                                                                   |
| -------- | ------------ | ----------------------------------------------------------------------------------------------------------- |
| 1        | **BLOCK**    | `REMOVED` and not declared in ticket or diff                                                                |
| 2        | **BLOCK**    | Foreign key is invalid (`fk_valid == false`)                                                                |
| 3        | **BLOCK**    | `MODIFIED`, not declared, and blast radius > `t.block_undeclared_modify_blast_radius`                       |
| 4        | **BLOCK**    | `COLUMN_REMOVED` on a section referenced by any FK in the contract                                          |
| 5        | **ESCALATE** | Not declared in ticket or diff (any change type)                                                            |
| 6        | **ESCALATE** | Required companion rows are missing                                                                         |
| 7        | **ESCALATE** | `COLUMN_REMOVED` on a section with no FK dependencies                                                        |
| 8        | **SUGGEST**  | `COLUMN_ADDED`                                                                                              |
| 9        | **SUGGEST**  | Declared, but blast radius > `t.suggest_min_blast_radius`                                                    |
| 10       | **AUTO_APPLY** | Declared in **both** ticket and diff, FK valid, companions present, blast radius ≤ `t.auto_apply_max_blast_radius`, and `t.allow_auto_apply` |

Notes:

- Schema changes (`COLUMN_*`) never auto-apply — the floor is SUGGEST.
- When `t.allow_auto_apply` is false, a change that would otherwise auto-apply is
  capped at SUGGEST.
- Integrity violations (FK / companion) are always reflected as blocked findings.

---

## Limitations

- **String comparison.** Values are compared as raw strings from the file; there
  is no per-`data_type` coercion in the diff (typed validation lives in the AI
  validator, which is advisory only).
- **Heuristic intent matching.** A finding is matched to a ticket/diff by section
  plus the row id appearing in a free-form `row_hint`; it is not a guaranteed
  structural match.
- **LLM dependence.** Jira/AI intent extraction and the AI validator require a
  valid `ANTHROPIC_API_KEY`; without it, run in diff-only mode.
- **Single-file configs.** Each reconciliation compares one base file vs one new
  file. Multi-file configs must be reconciled per file.
- **File-based registry.** Contracts and snapshots are stored on disk (suitable
  for a single deployment); there is no multi-node database backend.
- **No automatic apply step.** The engine *decides*; it does not write changes
  back to your systems. Applying an approved change is left to your pipeline.
