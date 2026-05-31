import { useEffect, useState } from "react";
import {
  getContract,
  listContracts,
  uploadContract,
} from "../api/client";
import { ContractSummary, SchemaContract } from "../types";
import ErrorBanner from "./ErrorBanner";

interface Props {
  onSelect: (contract: SchemaContract) => void;
}

export default function ContractPicker({ onSelect }: Props) {
  const [contracts, setContracts] = useState<ContractSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const [showUpload, setShowUpload] = useState(false);
  const [yamlText, setYamlText] = useState("");
  const [uploading, setUploading] = useState(false);
  const [warnings, setWarnings] = useState<string[] | null>(null);

  async function refresh() {
    try {
      const list = await listContracts();
      setContracts(list);
    } catch (e) {
      setError(e);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleContinue() {
    if (!selected) return;
    setLoading(true);
    setError(null);
    try {
      const contract = await getContract(selected);
      onSelect(contract);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }

  async function handleUpload() {
    if (!yamlText.trim()) return;
    setUploading(true);
    setError(null);
    setWarnings(null);
    try {
      const result = await uploadContract(yamlText);
      setWarnings(result.warnings);
      await refresh();
      setSelected(result.name);
      setShowUpload(false);
    } catch (e) {
      setError(e);
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-2xl font-semibold text-slate-800">
        Choose a schema contract
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        Every step downstream is driven by the contract you select.
      </p>

      {error ? (
        <div className="mt-4">
          <ErrorBanner error={error} onDismiss={() => setError(null)} />
        </div>
      ) : null}

      <div className="mt-6 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <label className="block text-sm font-medium text-slate-700">
          Registered contracts
        </label>
        <div className="mt-2 flex gap-3">
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="">
              {contracts.length ? "Select a contract..." : "No contracts yet"}
            </option>
            {contracts.map((c) => (
              <option key={`${c.name}_${c.version}`} value={c.name}>
                {c.name} (v{c.version}) — {c.section_count} sections
              </option>
            ))}
          </select>
          <button
            onClick={handleContinue}
            disabled={!selected || loading}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {loading ? "Loading..." : "Continue"}
          </button>
        </div>

        {warnings && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            {warnings.length === 0 ? (
              <span>Contract saved with no validation warnings.</span>
            ) : (
              <>
                <div className="font-medium">
                  Saved with {warnings.length} validation warning
                  {warnings.length > 1 ? "s" : ""}:
                </div>
                <ul className="mt-1 list-disc pl-5">
                  {warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}

        <div className="mt-5 border-t border-slate-100 pt-4">
          <button
            onClick={() => setShowUpload((v) => !v)}
            className="text-sm font-medium text-blue-600 hover:text-blue-700"
          >
            {showUpload ? "− Hide upload" : "+ Upload new contract"}
          </button>

          {showUpload && (
            <div className="mt-3">
              <textarea
                value={yamlText}
                onChange={(e) => setYamlText(e.target.value)}
                placeholder="Paste schema contract YAML here..."
                spellCheck={false}
                className="h-64 w-full resize-y rounded-lg border border-slate-300 p-3 font-mono text-xs text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <div className="mt-2 flex justify-end">
                <button
                  onClick={handleUpload}
                  disabled={!yamlText.trim() || uploading}
                  className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-900 disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                  {uploading ? "Validating..." : "Validate & save"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
