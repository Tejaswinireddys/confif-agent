// Thin fetch-based API client. Every call throws ApiError on a non-2xx response.

import {
  ApplyActionValue,
  ContractSummary,
  CreationResult,
  CreationSession,
  ReconciliationReport,
  SchemaContract,
  Snapshot,
  UploadContractResult,
} from "../types";

export const API_BASE = "http://localhost:8000";

export class ApiError extends Error {
  code: string;
  detail: string;
  status: number;

  constructor(message: string, code: string, detail: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.detail = detail;
    this.status = status;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) {
    return (await res.json()) as T;
  }

  let code = "INTERNAL_ERROR";
  let detail = res.statusText || "Request failed";
  let error = "Request failed";
  try {
    const body = await res.json();
    code = body.code ?? code;
    detail = body.detail ?? detail;
    error = body.error ?? error;
  } catch {
    // Non-JSON error body; fall back to status text.
  }
  throw new ApiError(error, code, detail, res.status);
}

export async function listContracts(): Promise<ContractSummary[]> {
  return handle<ContractSummary[]>(await fetch(`${API_BASE}/contracts`));
}

export async function getContract(name: string): Promise<SchemaContract> {
  return handle<SchemaContract>(
    await fetch(`${API_BASE}/contracts/${encodeURIComponent(name)}`)
  );
}

export async function uploadContract(
  yamlText: string
): Promise<UploadContractResult> {
  const form = new FormData();
  const blob = new Blob([yamlText], { type: "application/x-yaml" });
  form.append("file", blob, "contract.yaml");
  return handle<UploadContractResult>(
    await fetch(`${API_BASE}/contracts`, { method: "POST", body: form })
  );
}

export interface ReconcileParams {
  contractName: string;
  baseFile: File;
  newFile: File;
  jiraTicketId?: string;
  diffText?: string;
}

export async function reconcile(
  params: ReconcileParams
): Promise<ReconciliationReport> {
  const form = new FormData();
  form.append("contract_name", params.contractName);
  if (params.jiraTicketId) form.append("jira_ticket_id", params.jiraTicketId);
  if (params.diffText) form.append("diff_text", params.diffText);
  form.append("base_file", params.baseFile, params.baseFile.name);
  form.append("new_file", params.newFile, params.newFile.name);
  return handle<ReconciliationReport>(
    await fetch(`${API_BASE}/reconcile`, { method: "POST", body: form })
  );
}

export async function getSnapshots(): Promise<Snapshot[]> {
  return handle<Snapshot[]>(await fetch(`${API_BASE}/snapshots`));
}

export interface SnapshotDetail {
  deployment_id: string;
  report: ReconciliationReport;
  base_text: string;
  decisions: Record<string, { finding_id: string; action: string; at: string }>;
}

export async function getSnapshot(
  deploymentId: string
): Promise<SnapshotDetail> {
  return handle<SnapshotDetail>(
    await fetch(`${API_BASE}/snapshots/${encodeURIComponent(deploymentId)}`)
  );
}

export async function applyDecision(
  deploymentId: string,
  findingId: string,
  action: ApplyActionValue
): Promise<{ deployment_id: string; finding_id: string; action: string; at: string }> {
  return handle(
    await fetch(
      `${API_BASE}/apply/${encodeURIComponent(deploymentId)}/${encodeURIComponent(
        findingId
      )}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      }
    )
  );
}

export interface AnalyzeCreationParams {
  contractName: string;
  oldFile: File;
  newFile: File;
  jiraTicketId?: string;
  diffText?: string;
}

export async function analyzeCreation(
  params: AnalyzeCreationParams
): Promise<CreationSession> {
  const form = new FormData();
  form.append("contract_name", params.contractName);
  if (params.jiraTicketId) form.append("jira_ticket_id", params.jiraTicketId);
  if (params.diffText) form.append("diff_text", params.diffText);
  form.append("old_file", params.oldFile, params.oldFile.name);
  form.append("new_file", params.newFile, params.newFile.name);
  return handle<CreationSession>(
    await fetch(`${API_BASE}/create/analyze`, { method: "POST", body: form })
  );
}

export async function submitInputs(
  sessionId: string,
  inputs: Record<string, Record<string, string>>
): Promise<CreationSession> {
  return handle<CreationSession>(
    await fetch(`${API_BASE}/create/${encodeURIComponent(sessionId)}/inputs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ inputs }),
    })
  );
}

export async function finalizeCreation(
  sessionId: string,
  approvals: string[]
): Promise<CreationResult> {
  return handle<CreationResult>(
    await fetch(
      `${API_BASE}/create/${encodeURIComponent(sessionId)}/finalize`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approvals }),
      }
    )
  );
}

export async function downloadMerged(sessionId: string): Promise<Blob> {
  const res = await fetch(
    `${API_BASE}/create/${encodeURIComponent(sessionId)}/download`
  );
  if (!res.ok) {
    let code = "INTERNAL_ERROR";
    let detail = res.statusText || "Download failed";
    let error = "Download failed";
    try {
      const body = await res.json();
      code = body.code ?? code;
      detail = body.detail ?? detail;
      error = body.error ?? error;
    } catch {
      // ignore
    }
    throw new ApiError(error, code, detail, res.status);
  }
  return res.blob();
}
