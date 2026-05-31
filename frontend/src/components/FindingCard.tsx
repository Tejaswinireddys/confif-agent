import { AgentFinding, ApplyActionValue, RowValue } from "../types";
import { DECISION_STYLES, changeTypeStyle } from "../lib/ui";

interface Props {
  finding: AgentFinding;
  decision?: ApplyActionValue;
  onDecision: (findingId: string, action: ApplyActionValue) => void;
}

function isDict(value: RowValue): value is Record<string, string> {
  return typeof value === "object" && value !== null;
}

function ChecklistItem({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={ok ? "text-emerald-600" : "text-red-500"}>
        {ok ? "✓" : "✗"}
      </span>
      <span className="text-slate-600">{label}</span>
    </div>
  );
}

function RowValues({ value }: { value: RowValue }) {
  if (!isDict(value)) return null;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs text-slate-600">
      {Object.entries(value).map(([k, v]) => (
        <span key={k}>
          <span className="text-slate-400">{k}=</span>
          {v}
        </span>
      ))}
    </div>
  );
}

export default function FindingCard({ finding, decision, onDecision }: Props) {
  const style = DECISION_STYLES[finding.decision];
  const isSchema =
    finding.change_type === "COLUMN_ADDED" ||
    finding.change_type === "COLUMN_REMOVED";
  const actionable =
    finding.decision === "SUGGEST" || finding.decision === "ESCALATE";

  const base = isDict(finding.base_value) ? finding.base_value : {};
  const next = isDict(finding.new_value) ? finding.new_value : {};
  const changedFields = Object.keys(base).filter(
    (k) => k in next && base[k] !== next[k]
  );

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
        <span
          className={`rounded-md px-2 py-0.5 text-xs font-semibold ${style.badge}`}
        >
          {style.label}
        </span>
        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
          {finding.section}
        </span>
        {finding.row_id != null && (
          <span className="font-mono text-xs text-slate-500">
            #{finding.row_id}
          </span>
        )}
        <span
          className={`ml-auto rounded-md px-2 py-0.5 text-xs font-medium ${changeTypeStyle(
            finding.change_type
          )}`}
        >
          {finding.change_type}
        </span>
      </div>

      {/* Body */}
      <div className="space-y-3 px-4 py-3">
        <p className="text-sm text-slate-700">{finding.reason}</p>

        {!isSchema && (
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs">
            <ChecklistItem label="In Jira" ok={finding.in_jira_ticket} />
            <ChecklistItem label="In diff" ok={finding.in_code_diff} />
            <ChecklistItem label="FK valid" ok={finding.fk_valid} />
            <ChecklistItem
              label="Companions"
              ok={finding.companion_rows_present}
            />
          </div>
        )}

        <div className="text-xs text-slate-500">
          Blast radius:{" "}
          <span className="font-semibold text-slate-700">
            {finding.blast_radius}
          </span>
        </div>

        {/* MODIFIED two-column diff on changed fields */}
        {finding.change_type === "MODIFIED" && changedFields.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-slate-200">
            <div className="grid grid-cols-[auto_1fr_1fr] text-xs">
              <div className="bg-slate-50 px-3 py-1.5 font-medium text-slate-500">
                Field
              </div>
              <div className="bg-red-50 px-3 py-1.5 font-medium text-red-600">
                Base
              </div>
              <div className="bg-emerald-50 px-3 py-1.5 font-medium text-emerald-600">
                New
              </div>
              {changedFields.map((field) => (
                <div key={field} className="contents">
                  <div className="border-t border-slate-100 px-3 py-1.5 font-mono text-slate-600">
                    {field}
                  </div>
                  <div className="border-t border-slate-100 bg-red-50/40 px-3 py-1.5 font-mono text-red-700">
                    {base[field]}
                  </div>
                  <div className="border-t border-slate-100 bg-emerald-50/40 px-3 py-1.5 font-mono text-emerald-700">
                    {next[field]}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ADDED / REMOVED row snapshot */}
        {finding.change_type === "ADDED" && <RowValues value={finding.new_value} />}
        {finding.change_type === "REMOVED" && (
          <RowValues value={finding.base_value} />
        )}

        {/* Schema-change note */}
        {isSchema && (
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
            Column{" "}
            <span className="font-mono font-semibold">
              {finding.change_type === "COLUMN_ADDED"
                ? String(finding.new_value)
                : String(finding.base_value)}
            </span>{" "}
            {finding.change_type === "COLUMN_ADDED" ? "added to" : "removed from"}{" "}
            section <span className="font-medium">{finding.section}</span>.
          </div>
        )}

        {/* AI validator note */}
        {finding.validator_note && (
          <div className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-800">
            <div className="font-medium">
              AI validator ({finding.validator_note.confidence})
            </div>
            <div className="mt-0.5">{finding.validator_note.note}</div>
            {finding.validator_note.flags.length > 0 && (
              <ul className="mt-1 list-disc pl-4">
                {finding.validator_note.flags.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2.5">
        {actionable ? (
          <div className="flex items-center gap-2">
            <button
              onClick={() => onDecision(finding.finding_id, "approve")}
              className={`rounded-md px-3 py-1 text-xs font-medium ${
                decision === "approve"
                  ? "bg-emerald-600 text-white"
                  : "border border-emerald-300 text-emerald-700 hover:bg-emerald-50"
              }`}
            >
              {decision === "approve" ? "Approved" : "Approve"}
            </button>
            <button
              onClick={() => onDecision(finding.finding_id, "reject")}
              className={`rounded-md px-3 py-1 text-xs font-medium ${
                decision === "reject"
                  ? "bg-red-600 text-white"
                  : "border border-red-300 text-red-700 hover:bg-red-50"
              }`}
            >
              {decision === "reject" ? "Rejected" : "Reject"}
            </button>
          </div>
        ) : (
          <div className="text-xs">
            {finding.decision === "BLOCK" ? (
              <span className="font-medium text-red-600">
                Blocked — cannot be applied
              </span>
            ) : (
              <span className="font-medium text-emerald-600">
                Will be auto-applied
              </span>
            )}
          </div>
        )}
        <span className="font-mono text-[11px] text-slate-300">
          {finding.finding_id}
        </span>
      </div>
    </div>
  );
}
