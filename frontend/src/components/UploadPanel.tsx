import { useEffect, useRef, useState } from "react";
import { reconcile } from "../api/client";
import { ReconciliationReport, SchemaContract } from "../types";
import ErrorBanner from "./ErrorBanner";

interface Props {
  contract: SchemaContract;
  onComplete: (report: ReconciliationReport) => void;
  onBack: () => void;
}

const STATUS_MESSAGES = [
  "Parsing config files against the contract...",
  "Diffing rows by identity columns...",
  "Checking foreign keys and companions...",
  "Mapping declared intent to sections...",
  "Scoring blast radius and deciding...",
];

interface DropZoneProps {
  label: string;
  hint: string;
  file: File | null;
  onFile: (file: File) => void;
}

function DropZone({ label, hint, file, onFile }: DropZoneProps) {
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const dropped = e.dataTransfer.files?.[0];
        if (dropped) onFile(dropped);
      }}
      onClick={() => inputRef.current?.click()}
      className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center transition ${
        over
          ? "border-blue-500 bg-blue-50"
          : file
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
        <div className="mt-1 text-xs text-slate-500">
          Drag &amp; drop or click — {hint}
        </div>
      )}
    </div>
  );
}

export default function UploadPanel({ contract, onComplete, onBack }: Props) {
  const [jiraTicketId, setJiraTicketId] = useState("");
  const [jiraAttached, setJiraAttached] = useState(false);
  const [diffText, setDiffText] = useState("");
  const [diffFileName, setDiffFileName] = useState<string | null>(null);
  const [baseFile, setBaseFile] = useState<File | null>(null);
  const [newFile, setNewFile] = useState<File | null>(null);

  const [running, setRunning] = useState(false);
  const [statusIndex, setStatusIndex] = useState(0);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(
      () => setStatusIndex((i) => (i + 1) % STATUS_MESSAGES.length),
      1500
    );
    return () => window.clearInterval(id);
  }, [running]);

  const pattern = contract.file_format.file_pattern;
  const hasIntent = jiraAttached && jiraTicketId.trim().length > 0;
  const hasDiff = diffText.trim().length > 0;
  const diffOnly = !hasIntent && !hasDiff;
  const canRun = Boolean(baseFile && newFile) && !running;

  async function handleDiffFile(file: File) {
    const text = await file.text();
    setDiffText(text);
    setDiffFileName(file.name);
  }

  async function handleRun() {
    if (!baseFile || !newFile) return;
    setRunning(true);
    setStatusIndex(0);
    setError(null);
    try {
      const report = await reconcile({
        contractName: contract.contract_name,
        baseFile,
        newFile,
        jiraTicketId: hasIntent ? jiraTicketId.trim() : undefined,
        diffText: hasDiff ? diffText : undefined,
      });
      onComplete(report);
    } catch (e) {
      setError(e);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <button
        onClick={onBack}
        className="text-sm text-slate-500 hover:text-slate-700"
      >
        ← Back to contracts
      </button>

      <h1 className="mt-2 text-2xl font-semibold text-slate-800">
        Run reconciliation
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        Contract:{" "}
        <span className="font-medium text-slate-700">
          {contract.contract_name}
        </span>{" "}
        <span className="text-slate-400">v{contract.version}</span>
      </p>

      {error ? (
        <div className="mt-4">
          <ErrorBanner error={error} onDismiss={() => setError(null)} />
        </div>
      ) : null}

      {/* Intent: Jira ticket */}
      <div className="mt-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="text-sm font-medium text-slate-700">
          Jira ticket <span className="font-normal text-slate-400">(optional)</span>
        </div>
        <div className="mt-2 flex gap-2">
          <input
            value={jiraTicketId}
            onChange={(e) => {
              setJiraTicketId(e.target.value);
              setJiraAttached(false);
            }}
            placeholder="e.g. NET-1234"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <button
            onClick={() => setJiraAttached(true)}
            disabled={!jiraTicketId.trim()}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Fetch
          </button>
        </div>
        {hasIntent && (
          <div className="mt-2 text-xs text-emerald-700">
            ✓ {jiraTicketId.trim()} will be used for AI intent extraction.
          </div>
        )}
      </div>

      {/* Intent: diff */}
      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="text-sm font-medium text-slate-700">
            Git diff <span className="font-normal text-slate-400">(optional)</span>
          </div>
          <label className="cursor-pointer text-xs font-medium text-blue-600 hover:text-blue-700">
            Load from file
            <input
              type="file"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleDiffFile(f);
              }}
            />
          </label>
        </div>
        <textarea
          value={diffText}
          onChange={(e) => {
            setDiffText(e.target.value);
            setDiffFileName(null);
          }}
          placeholder="Paste a unified git diff (optional)..."
          spellCheck={false}
          className="mt-2 h-32 w-full resize-y rounded-lg border border-slate-300 p-3 font-mono text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        {diffFileName && (
          <div className="mt-1 text-xs text-slate-500">Loaded from {diffFileName}</div>
        )}
      </div>

      {diffOnly && (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <span className="font-medium">Diff-only mode.</span> No Jira ticket or
          diff provided — every change will be treated as undeclared and will
          escalate or block rather than auto-apply.
        </div>
      )}

      {/* Config files */}
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <DropZone
          label="Base config"
          hint={pattern}
          file={baseFile}
          onFile={setBaseFile}
        />
        <DropZone
          label="New config"
          hint={pattern}
          file={newFile}
          onFile={setNewFile}
        />
      </div>

      <div className="mt-6 flex items-center justify-between">
        <div className="text-sm text-slate-500">
          {running && (
            <span className="inline-flex items-center gap-2">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-blue-600" />
              {STATUS_MESSAGES[statusIndex]}
            </span>
          )}
        </div>
        <button
          onClick={handleRun}
          disabled={!canRun}
          className="rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {running ? "Reconciling..." : "Run reconciliation"}
        </button>
      </div>
    </div>
  );
}
