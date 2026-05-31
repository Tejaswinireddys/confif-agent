import { useEffect, useRef, useState } from "react";
import {
  analyzeCreation,
  finalizeCreation,
  submitInputs,
} from "../api/client";
import {
  CreationResult,
  CreationSession,
  SchemaContract,
} from "../types";
import ErrorBanner from "../components/ErrorBanner";
import MergePlanView from "../components/MergePlanView";
import HumanInputForm, {
  humanInputOpId,
  humanInputsValid,
} from "../components/HumanInputForm";
import RereviewResult from "../components/RereviewResult";

type Step = "analyze" | "plan" | "approve" | "result";

interface Props {
  contract: SchemaContract;
  onBack: () => void;
}

const STEPS: { id: Step; label: string }[] = [
  { id: "analyze", label: "Analyze" },
  { id: "plan", label: "Review plan" },
  { id: "approve", label: "Approve" },
  { id: "result", label: "Re-review" },
];

function DropZone({
  label,
  file,
  onFile,
}: {
  label: string;
  file: File | null;
  onFile: (f: File) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div
      onClick={() => inputRef.current?.click()}
      className={`cursor-pointer rounded-xl border-2 border-dashed p-6 text-center ${
        file
          ? "border-emerald-300 bg-emerald-50"
          : "border-slate-300 bg-slate-50 hover:border-slate-400"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        onChange={(e) => {
          const picked = e.target.files?.[0];
          if (picked) onFile(picked);
        }}
      />
      <div className="text-sm font-medium text-slate-700">{label}</div>
      {file ? (
        <div className="mt-1 text-sm text-emerald-700">✓ {file.name}</div>
      ) : (
        <div className="mt-1 text-xs text-slate-500">Click to choose file</div>
      )}
    </div>
  );
}

function buildInputPayload(
  session: CreationSession,
  humanValues: Record<string, Record<string, string>>
): Record<string, Record<string, string>> {
  const missingRows =
    (session.gap_report as { missing_rows?: Array<Record<string, unknown>> })
      .missing_rows ?? [];
  const payload: Record<string, Record<string, string>> = {};

  for (const item of session.human_inputs_needed) {
    const opId = humanInputOpId(item);
    if (payload[opId]) continue;
    const missing = missingRows.find(
      (row) =>
        row.section === item.section &&
        String(row.row_id ?? "") === String(item.row_id ?? "")
    );
    const source = (missing?.source_values as Record<string, string>) ?? {};
    payload[opId] = { ...source };
  }

  for (const [opId, fields] of Object.entries(humanValues)) {
    payload[opId] = { ...(payload[opId] ?? {}), ...fields };
  }
  return payload;
}

function requiredApprovals(plan: CreationSession["plan"]): string[] {
  return plan.operations
    .filter((op) => op.op_type === "ADD_ROW" || op.op_type === "ADD_COLUMN")
    .map((op) => op.op_id);
}

export default function CreatePage({ contract, onBack }: Props) {
  const [step, setStep] = useState<Step>("analyze");
  const [oldFile, setOldFile] = useState<File | null>(null);
  const [newFile, setNewFile] = useState<File | null>(null);
  const [session, setSession] = useState<CreationSession | null>(null);
  const [result, setResult] = useState<CreationResult | null>(null);
  const [humanValues, setHumanValues] = useState<
    Record<string, Record<string, string>>
  >({});
  const [approvals, setApprovals] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!session) return;
    setApprovals(new Set(requiredApprovals(session.plan)));
  }, [session]);

  const stepIndex = STEPS.findIndex((s) => s.id === step);

  async function handleAnalyze() {
    if (!oldFile || !newFile) return;
    setBusy(true);
    setError(null);
    try {
      const created = await analyzeCreation({
        contractName: contract.contract_name,
        oldFile,
        newFile,
      });
      setSession(created);
      if (created.state === "BLOCKED") {
        setStep("plan");
      } else {
        setStep("plan");
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmitInputs() {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      const payload = buildInputPayload(session, humanValues);
      const updated = await submitInputs(session.session_id, payload);
      setSession(updated);
      setStep("approve");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  function handleContinueFromPlan() {
    if (!session) return;
    if (
      session.human_inputs_needed.length > 0 &&
      !humanInputsValid(session.human_inputs_needed, humanValues, contract)
    ) {
      return;
    }
    if (session.human_inputs_needed.length > 0) {
      handleSubmitInputs();
      return;
    }
    setStep("approve");
  }

  async function handleFinalize() {
    if (!session) return;
    const required = requiredApprovals(session.plan);
    if (!required.every((id) => approvals.has(id))) return;
    setBusy(true);
    setError(null);
    try {
      const finalized = await finalizeCreation(
        session.session_id,
        Array.from(approvals)
      );
      setResult(finalized);
      setStep("result");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  function toggleApproval(opId: string) {
    setApprovals((prev) => {
      const next = new Set(prev);
      if (next.has(opId)) next.delete(opId);
      else next.add(opId);
      return next;
    });
  }

  const inputsReady =
    !session?.human_inputs_needed.length ||
    humanInputsValid(session.human_inputs_needed, humanValues, contract);

  const allApproved =
    session &&
    requiredApprovals(session.plan).every((id) => approvals.has(id));

  return (
    <div className="mx-auto max-w-4xl pb-16">
      <button
        onClick={onBack}
        className="text-sm text-slate-500 hover:text-slate-700"
      >
        ← Back to contracts
      </button>

      <h1 className="mt-2 text-2xl font-semibold text-slate-800">
        Create merged config
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        {contract.contract_name}{" "}
        <span className="text-slate-400">v{contract.version}</span>
      </p>

      {/* Progress */}
      <ol className="mt-6 flex items-center gap-2">
        {STEPS.map((s, i) => (
          <li key={s.id} className="flex flex-1 items-center gap-2">
            <div
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                i <= stepIndex
                  ? "bg-blue-600 text-white"
                  : "bg-slate-200 text-slate-500"
              }`}
            >
              {i + 1}
            </div>
            <span
              className={`hidden text-xs sm:inline ${
                i === stepIndex
                  ? "font-semibold text-slate-800"
                  : "text-slate-500"
              }`}
            >
              {s.label}
            </span>
            {i < STEPS.length - 1 ? (
              <div className="mx-1 hidden h-px flex-1 bg-slate-200 sm:block" />
            ) : null}
          </li>
        ))}
      </ol>

      {error ? (
        <div className="mt-4">
          <ErrorBanner error={error} onDismiss={() => setError(null)} />
        </div>
      ) : null}

      {step === "analyze" ? (
        <div className="mt-6 space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <DropZone label="Old config (baseline)" file={oldFile} onFile={setOldFile} />
            <DropZone label="New config (source)" file={newFile} onFile={setNewFile} />
          </div>
          <div className="flex justify-end">
            <button
              onClick={handleAnalyze}
              disabled={!oldFile || !newFile || busy}
              className="rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:bg-slate-300"
            >
              {busy ? "Analyzing..." : "Analyze gaps"}
            </button>
          </div>
        </div>
      ) : null}

      {step === "plan" && session ? (
        <div className="mt-6 space-y-5">
          {session.state === "BLOCKED" ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              This session is blocked due to broken references. Review blocked
              items below — they cannot be applied.
            </div>
          ) : null}

          {session.plan_issues.length > 0 ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              <div className="font-medium">Plan validation warnings</div>
              <ul className="mt-1 list-disc pl-5">
                {session.plan_issues.map((issue, i) => (
                  <li key={i}>{issue.message}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <MergePlanView
            plan={session.plan}
            approvals={approvals}
            onToggleApproval={toggleApproval}
          />

          <HumanInputForm
            items={session.human_inputs_needed}
            contract={contract}
            values={humanValues}
            onChange={setHumanValues}
          />

          <div className="flex justify-between">
            <button
              onClick={() => setStep("analyze")}
              className="text-sm text-slate-500 hover:text-slate-700"
            >
              ← Re-analyze
            </button>
            <button
              onClick={handleContinueFromPlan}
              disabled={
                busy ||
                session.state === "BLOCKED" ||
                !inputsReady
              }
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-slate-300"
            >
              {busy ? "Saving..." : "Continue to approve →"}
            </button>
          </div>
        </div>
      ) : null}

      {step === "approve" && session ? (
        <div className="mt-6 space-y-5">
          <MergePlanView
            plan={session.plan}
            approvals={approvals}
            onToggleApproval={toggleApproval}
          />

          <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-4 py-3">
            <span className="text-sm text-slate-600">
              {approvals.size} of {requiredApprovals(session.plan).length}{" "}
              operations approved
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setStep("plan")}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
              >
                ← Back
              </button>
              <button
                onClick={handleFinalize}
                disabled={busy || !allApproved || session.state === "BLOCKED"}
                className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:bg-slate-300"
              >
                {busy ? "Finalizing..." : "Finalize & re-review"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {step === "result" && result ? (
        <div className="mt-6">
          <RereviewResult
            result={result}
            onBack={() => {
              setResult(null);
              setStep("plan");
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
