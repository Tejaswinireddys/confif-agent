import { useMemo, useState } from "react";
import { applyDecision } from "../api/client";
import {
  ApplyActionValue,
  Filter,
  ReconciliationReport,
} from "../types";
import ReportSummaryBar from "../components/ReportSummaryBar";
import SchemaChangePanel from "../components/SchemaChangePanel";
import IntegrityViolationPanel from "../components/IntegrityViolationPanel";
import FindingsList from "../components/FindingsList";
import ErrorBanner from "../components/ErrorBanner";

interface Props {
  report: ReconciliationReport;
  onBack: () => void;
}

export default function ReviewPage({ report, onBack }: Props) {
  const [filter, setFilter] = useState<Filter>(null);
  const [decisions, setDecisions] = useState<Record<string, ApplyActionValue>>(
    {}
  );
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const actionable = useMemo(
    () =>
      report.findings.filter(
        (f) => f.decision === "SUGGEST" || f.decision === "ESCALATE"
      ),
    [report.findings]
  );
  const reviewedCount = actionable.filter((f) => decisions[f.finding_id]).length;

  async function handleDecision(findingId: string, action: ApplyActionValue) {
    setError(null);
    // Optimistic update; revert on failure.
    const previous = decisions[findingId];
    setDecisions((d) => ({ ...d, [findingId]: action }));
    try {
      await applyDecision(report.deployment_id, findingId, action);
    } catch (e) {
      setError(e);
      setDecisions((d) => {
        const copy = { ...d };
        if (previous) copy[findingId] = previous;
        else delete copy[findingId];
        return copy;
      });
    }
  }

  async function approveAllSuggest() {
    const pending = report.findings.filter(
      (f) => f.decision === "SUGGEST" && decisions[f.finding_id] !== "approve"
    );
    if (pending.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      for (const finding of pending) {
        await applyDecision(report.deployment_id, finding.finding_id, "approve");
        setDecisions((d) => ({ ...d, [finding.finding_id]: "approve" }));
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  function exportJson() {
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${report.deployment_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mx-auto max-w-4xl pb-28">
      <button
        onClick={onBack}
        className="text-sm text-slate-500 hover:text-slate-700"
      >
        ← New reconciliation
      </button>

      <div className="mt-2 flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold text-slate-800">Review</h1>
        <div className="text-xs text-slate-400">
          <span className="font-mono">{report.deployment_id}</span>
          <span className="mx-2">·</span>
          {report.contract_name} v{report.contract_version}
        </div>
      </div>

      {error ? (
        <div className="mt-4">
          <ErrorBanner error={error} onDismiss={() => setError(null)} />
        </div>
      ) : null}

      <div className="mt-5">
        <ReportSummaryBar report={report} filter={filter} onFilter={setFilter} />
      </div>

      <div className="mt-5 space-y-5">
        {filter === null || filter === "SCHEMA" ? (
          <SchemaChangePanel changes={report.schema_changes} />
        ) : null}
        {filter === null || filter === "VIOLATIONS" ? (
          <IntegrityViolationPanel violations={report.integrity_violations} />
        ) : null}

        <FindingsList
          findings={report.findings}
          filter={filter}
          decisions={decisions}
          onDecision={handleDecision}
        />
      </div>

      {/* Sticky action bar */}
      <div className="fixed inset-x-0 bottom-0 border-t border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-4 px-4 py-3">
          <div className="text-sm text-slate-600">
            <span className="font-semibold text-slate-800">{reviewedCount}</span>{" "}
            of {actionable.length} actionable findings reviewed
            <div className="mt-1 h-1.5 w-48 overflow-hidden rounded-full bg-slate-200">
              <div
                className="h-full rounded-full bg-blue-600 transition-all"
                style={{
                  width: `${
                    actionable.length
                      ? (reviewedCount / actionable.length) * 100
                      : 0
                  }%`,
                }}
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={approveAllSuggest}
              disabled={busy}
              className="rounded-lg border border-blue-300 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50"
            >
              {busy ? "Approving..." : "Approve all SUGGEST"}
            </button>
            <button
              onClick={exportJson}
              className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-900"
            >
              Export JSON
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
