# Writing a Schema Contract

A schema contract teaches the reconciler how to read *your* config format and
what relationships matter. This guide walks through authoring one from scratch.

Templates to start from live in
[`backend/schemas/templates/`](../backend/schemas/templates/):

- `flat_csv_template.yaml` — a single flat table, no section markers.
- `multi_section_template.yaml` — several marker-delimited tables, no relations.
- `relational_template.yaml` — sections with foreign keys + companions + thresholds.

Validate as you go:

```bash
make validate FILE=path/to/your_contract.yaml
# or
python backend/cli.py validate-contract --file path/to/your_contract.yaml
```

---

## Step 1 — Describe the file format

Tell the engine how the file is physically laid out:

```yaml
file_format:
  file_pattern: "*.cfg"          # informational label shown in the UI
  delimiter: ","                 # field separator
  has_section_markers: true      # false => the whole file is one flat table
  section_start_prefix: "start_" # "start_<section>" opens a block
  section_end_prefix: "end_"     # "end_<section>" closes it
  header_position: "before_start" # or "first_row"
  leading_empty_field: true      # true if every row starts with the delimiter
```

- **Flat file?** Set `has_section_markers: false` and `header_position:
  first_row`. The section name will be taken from the uploaded file's stem
  (`devices.csv` → section `devices`).
- **`leading_empty_field`** handles formats where each line begins with the
  delimiter (e.g. `,1,host-a,...`). The empty leading field is dropped.

---

## Step 2 — Identify your sections

A **section** is a logical table — a group of rows that share the same columns.
For each one, give it a `name` and a plain-English `description`. The
description is sent to the AI so it can map ticket language onto the right
section, so make it meaningful.

```yaml
sections:
  - name: nodes
    description: >-
      Individual machines that live inside a cluster. Each node belongs to
      exactly one cluster and exposes at least one interface.
```

---

## Step 3 — Choose the id column

Every section needs an `id_column`: the column that uniquely identifies a row.
Row identity is based on this value, **never on position**, so reordering rows
does not register as a change.

```yaml
    id_column: node_id
    columns:
      - name: node_id
        is_id: true
        required: true
        data_type: int
```

`data_type` is one of `string`, `int`, `ip`, `port`, `enum`, `bool`. For
`enum`, list the allowed values:

```yaml
      - name: tier
        data_type: enum
        enum_values: ["gold", "silver", "bronze"]
```

---

## Step 4 — Declare foreign keys

A foreign key says "this column points at a row in another section." The engine
uses these both to validate integrity (the referenced row must exist) and to
compute **blast radius** (how many rows depend on a given row).

```yaml
    foreign_keys:
      - column: cluster_ref          # column in THIS section
        references_section: clusters # the target section
        references_column: cluster_id # the target's id column
```

---

## Step 5 — Declare companions

A companion rule says "a row here must be accompanied by a matching row in
another section." Use it for required pairings.

```yaml
    companions:
      # Every node must have at least one interface whose node_id matches.
      - requires_section: interfaces
        match_on: node_id
```

`match_on` is the column name used to correlate the two rows; it is expected to
exist on both sides.

---

## Step 6 — Pick an id_naming_rule

`id_naming_rule` documents how new ids are allocated when rows are added
(e.g. `sequential_int`). It is metadata for downstream id allocation and does
not change parsing.

```yaml
    id_naming_rule: sequential_int
```

---

## Step 7 — Tune thresholds (optional)

Thresholds drive the decision engine. Omit the block to accept the defaults.

```yaml
thresholds:
  auto_apply_max_blast_radius: 2          # auto-apply only when <= this many dependents
  suggest_min_blast_radius: 3             # declared changes above this drop to SUGGEST
  block_undeclared_modify_blast_radius: 2 # undeclared modify above this is BLOCKED
  allow_auto_apply: true                  # false caps every decision at SUGGEST
```

A conservative team might set `allow_auto_apply: false` so nothing is ever
applied without a human approving it.

---

## Fully worked example

A small "network" config with three related sections:

```yaml
contract_name: example_generic_network
version: "1.0.0"

file_format:
  file_pattern: "*.cfg"
  delimiter: ","
  has_section_markers: true
  section_start_prefix: "start_"
  section_end_prefix: "end_"
  header_position: "before_start"
  leading_empty_field: true

sections:
  - name: clusters
    description: Top-level container that nodes belong to.
    id_column: cluster_id
    id_naming_rule: sequential_int
    columns:
      - name: cluster_id
        is_id: true
        required: true
        data_type: int
      - name: cluster_name
        required: true
        data_type: string
      - name: tier
        data_type: enum
        enum_values: ["gold", "silver", "bronze"]

  - name: nodes
    description: Machines inside a cluster; each exposes at least one interface.
    id_column: node_id
    id_naming_rule: sequential_int
    columns:
      - name: node_id
        is_id: true
        required: true
        data_type: int
      - name: hostname
        required: true
        data_type: string
      - name: cluster_ref
        required: true
        data_type: int
    foreign_keys:
      - column: cluster_ref
        references_section: clusters
        references_column: cluster_id
    companions:
      - requires_section: interfaces
        match_on: node_id

  - name: interfaces
    description: Network interfaces attached to a node.
    id_column: interface_id
    id_naming_rule: sequential_int
    columns:
      - name: interface_id
        is_id: true
        required: true
        data_type: int
      - name: node_id
        required: true
        data_type: int
      - name: ip_address
        data_type: ip
      - name: listen_port
        data_type: port
    foreign_keys:
      - column: node_id
        references_section: nodes
        references_column: node_id

thresholds:
  auto_apply_max_blast_radius: 3
  suggest_min_blast_radius: 4
  block_undeclared_modify_blast_radius: 3
  allow_auto_apply: true
```

The matching config file looks like:

```
,cluster_id,cluster_name,tier
start_clusters
,1,prod,gold
end_clusters
,node_id,hostname,cluster_ref,enabled
start_nodes
,1,host-a,1,true
end_nodes
,interface_id,node_id,ip_address,listen_port
start_interfaces
,1,1,10.0.0.1,8080
end_interfaces
```

This is the contract shipped at
[`backend/schemas/example_contract.yaml`](../backend/schemas/example_contract.yaml).

---

## Common mistakes `validate_contract` catches

Running validation surfaces these issues as warnings:

| Warning                                   | Cause                                                                 | Fix                                                            |
| ----------------------------------------- | --------------------------------------------------------------------- | -------------------------------------------------------------- |
| *id_column ... is not one of its columns* | A section's `id_column` does not match any declared column name.      | Add the column, or correct the `id_column` spelling.           |
| *foreign key references missing section*  | An FK's `references_section` is not a declared section.               | Reference an existing section name.                            |
| *foreign key references missing column*   | An FK's `references_column` does not exist in the target section.     | Point at a real column (usually the target's `id_column`).     |
| *foreign key column ... is not one of its columns* | The FK `column` is not declared in the owning section.       | Declare the referencing column.                                |
| *companion references missing section*    | A companion's `requires_section` is not a declared section.           | Reference an existing section.                                 |
| *companion match_on ... is not in section* | The companion `match_on` column does not exist in the required section. | Use a column that exists in `requires_section`.              |
| *Duplicate section name*                  | Two sections share the same `name`.                                   | Give each section a unique name.                               |

Beyond these, structural problems (missing required keys, an invalid
`data_type`, malformed YAML) are caught when the contract is loaded and reported
as an "invalid contract" error rather than a warning.
