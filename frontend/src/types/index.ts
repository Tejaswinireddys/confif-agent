// Shared types mirroring the backend contract + reconciliation models.

export type Decision = "AUTO_APPLY" | "SUGGEST" | "ESCALATE" | "BLOCK";

export type ChangeType = "ADDED" | "REMOVED" | "MODIFIED";

// Findings can also be schema-level (column changes), which carry decisions too.
export type FindingChangeType = ChangeType | "COLUMN_ADDED" | "COLUMN_REMOVED";

export type DataType = "string" | "int" | "ip" | "port" | "enum" | "bool";

export interface ColumnDef {
  name: string;
  is_id: boolean;
  required: boolean;
  data_type: DataType;
  enum_values: string[] | null;
}

export interface ForeignKeyRule {
  column: string;
  references_section: string;
  references_column: string;
}

export interface CompanionRule {
  requires_section: string;
  match_on: string;
}

export interface SectionDef {
  name: string;
  description: string;
  id_column: string;
  id_naming_rule: string;
  columns: ColumnDef[];
  foreign_keys: ForeignKeyRule[];
  companions: CompanionRule[];
}

export interface FileFormat {
  file_pattern: string;
  delimiter: string;
  has_section_markers: boolean;
  section_start_prefix: string;
  section_end_prefix: string;
  header_position: "before_start" | "first_row";
  leading_empty_field: boolean;
}

export interface DecisionThresholds {
  auto_apply_max_blast_radius: number;
  suggest_min_blast_radius: number;
  block_undeclared_modify_blast_radius: number;
  allow_auto_apply: boolean;
}

export interface SchemaContract {
  contract_name: string;
  version: string;
  file_format: FileFormat;
  sections: SectionDef[];
  thresholds: DecisionThresholds;
}

export interface ContractSummary {
  name: string;
  version: string;
  section_count: number;
}

export interface UploadContractResult {
  name: string;
  version: string;
  section_count: number;
  warnings: string[];
  stored_at: string;
}

export type SchemaChangeType =
  | "COLUMN_ADDED"
  | "COLUMN_REMOVED"
  | "COLUMN_REORDERED"
  | "UNDECLARED_COLUMN";

export interface SchemaChange {
  section: string;
  change_type: SchemaChangeType;
  column_name: string;
  base_index: number | null;
  new_index: number | null;
}

export type ViolationType = "FK_VIOLATION" | "COMPANION_VIOLATION";

export interface IntegrityViolation {
  section: string;
  row_id: string | null;
  violation_type: ViolationType;
  message: string;
}

export type RowValue = Record<string, string> | string | null;

export interface AgentFinding {
  finding_id: string;
  section: string;
  row_id: string | null;
  change_type: FindingChangeType;
  in_jira_ticket: boolean;
  in_code_diff: boolean;
  fk_valid: boolean;
  companion_rows_present: boolean;
  blast_radius: number;
  decision: Decision;
  reason: string;
  base_value: RowValue;
  new_value: RowValue;
  // Optional, attached client-side when an AI validator note is available.
  validator_note?: ValidatorNote;
}

export interface ValidatorNote {
  finding_id: string;
  note: string;
  confidence: string;
  flags: string[];
}

export interface ReportSummary {
  total_findings: number;
  decisions: Record<Decision, number>;
  integrity_violations: number;
  schema_changes: number;
}

export interface ReconciliationReport {
  deployment_id: string;
  contract_name: string;
  contract_version: string;
  findings: AgentFinding[];
  integrity_violations: IntegrityViolation[];
  schema_changes: SchemaChange[];
  summary: ReportSummary;
}

export interface Snapshot {
  deployment_id: string;
  contract_name: string;
  contract_version: string;
  created_at: string;
  summary: ReportSummary;
}

export type ApplyActionValue = "approve" | "reject";

// Summary-bar filter applied to the findings list. null = show everything.
export type Filter = Decision | "SCHEMA" | "VIOLATIONS" | null;

// ---------------------------------------------------------------------------
// Creation pipeline
// ---------------------------------------------------------------------------

export type Provenance =
  | "from_new_file"
  | "auto_allocated"
  | "contract_default"
  | "human_supplied"
  | "needs_human";

export type MergeOpType =
  | "ADD_ROW"
  | "ADD_COLUMN"
  | "ALLOCATE_ID"
  | "RESOLVE_FK"
  | "FILL_DEFAULT"
  | "REQUIRE_HUMAN_INPUT";

export interface MergeOperation {
  op_id: string;
  op_type: MergeOpType;
  section: string;
  target_id: string | null;
  values: Record<string, string>;
  provenance: Record<string, Provenance>;
  depends_on: string[];
  reason: string;
}

export interface BlockedItem {
  section: string;
  target_id: string | null;
  reason: string;
  triggered_by?: string;
}

export interface MergePlan {
  plan_id: string;
  contract_name: string;
  operations: MergeOperation[];
  blocked: BlockedItem[];
  human_inputs_needed: HumanInputItem[];
}

export interface HumanInputItem {
  section: string;
  row_id: string | null;
  column: string;
  data_type: DataType;
  why_needed: string;
}

export interface PlanIssue {
  code: string;
  message: string;
  op_id?: string | null;
}

export type CreationSessionState =
  | "AWAITING_HUMAN_INPUT"
  | "AWAITING_APPROVAL"
  | "BLOCKED";

export interface CreationSession {
  session_id: string;
  state: CreationSessionState;
  contract_name: string;
  contract_version: string;
  gap_report: Record<string, unknown>;
  plan: MergePlan;
  plan_issues: PlanIssue[];
  human_inputs_needed: HumanInputItem[];
  blocked: BlockedItem[];
}

export interface ChangelogEntry {
  op_id: string;
  section: string;
  target_id: string | null;
  action: string;
  field_provenance: Record<string, string>;
  reason: string;
}

export interface UnexpectedMutation {
  section: string;
  row_id: string | null;
  change_type: string;
  message: string;
  changed_fields: string[];
}

export interface OrphanRow {
  section: string;
  row_id: string | null;
  message: string;
}

export interface RereviewReport {
  passed: boolean;
  verdict: "ACCEPTED" | "REJECTED";
  rejection_reasons: string[];
  integrity_violations: IntegrityViolation[];
  unexpected_mutations: UnexpectedMutation[];
  orphan_rows: OrphanRow[];
}

export type CreationVerdict =
  | "ACCEPTED"
  | "REJECTED"
  | "AWAITING_HUMAN_INPUT"
  | "BLOCKED";

export interface CreationResult {
  verdict: CreationVerdict;
  session_id: string;
  plan: MergePlan;
  rejection_reasons: string[];
  changelog: ChangelogEntry[];
  rereview: RereviewReport | null;
  merged_text: string | null;
  download_url: string | null;
}
