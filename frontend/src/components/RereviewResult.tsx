import { API_BASE, downloadMerged } from "../api/client";
import { ChangelogEntry, CreationResult } from "../types";
import { PROVENANCE_LABELS, PROVENANCE_STYLES } from "../lib/ui";

interface Props {
  result: CreationResult;
  onBack: () => void;
}

function ChangelogTable({ entries }: { entries: ChangelogEntry[] }) {
  const applied = entries.filter(
    (e) => e.action === "ADD_ROW" || e.action === "ADD_COLUMN"
  );

  if (applied.length === 0) {
    return (
      <p className="text-sm text-slate-500">No applied changes recorded.</p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-xs text-slate-500">
            <th className="py-2 pr-4">Action</th>
            <th className="py-2 pr-4">Target</th>
            <th className="py-2 pr-4">Provenance</th>
            <th className="py-2">Reason</th>
          </tr>
        </thead>
        <tbody>
          {applied.map((entry) => (
            <tr key={entry.op_id} className="border-b border-slate-100">
              <td className="py-2 pr-4 font-mono text-xs">{entry.action}</td>
              <td className="py-2 pr-4">
                {entry.section}
                {entry.target_id ? `#${entry.target_id}` : ""}
              </td>
              <td className="py-2 pr-4">
                <div className="flex flex-wrap gap-1">
                  {Object.entries(entry.field_provenance).map(([field, prov]) => (
                    <span
                      key={field}
                      title={field}
                      className={`rounded border px-1 py-0.5 text-[10px] ${
                        PROVENANCE_STYLES[prov] ??
                        "bg-slate-100 text-slate-600 border-slate-200"
                      }`}
                    >
                      {field}: {PROVENANCE_LABELS[prov] ?? prov}
                    </span>
                  ))}
                </div>
              </td>
              <td className="py-2 text-xs text-slate-600">{entry.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function RereviewResult({ result, onBack }: Props) {
  const accepted = result.verdict === "ACCEPTED";

  async function handleDownload() {
    const blob = await downloadMerged(result.session_id);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${result.session_id}-merged.cfg`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (accepted) {
    return (
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-6">
        <h2 className="text-lg font-semibold text-emerald-800">Accepted</h2>
        <p className="mt-1 text-sm text-emerald-700">
          Re-review passed. The merged file is ready for deployment.
        </p>

        <div className="mt-5 rounded-lg border border-emerald-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-800">Changelog</h3>
          <div className="mt-3">
            <ChangelogTable entries={result.changelog} />
          </div>
        </div>

        <div className="mt-5 flex gap-3">
          {result.download_url ? (
            <button
              onClick={handleDownload}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
            >
              Download merged file
            </button>
          ) : null}
          <a
            href={`${API_BASE}${result.download_url ?? ""}`}
            className="hidden"
            download
          >
            direct
          </a>
        </div>
      </div>
    );
  }

  const rereview = result.rereview;

  return (
    <div className="rounded-xl border border-red-200 bg-red-50 p-6">
      <h2 className="text-lg font-semibold text-red-800">Rejected</h2>
      <p className="mt-1 text-sm text-red-700">
        Re-review failed. No merged file was produced.
      </p>

      {result.rejection_reasons.length > 0 ? (
        <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-red-800">
          {result.rejection_reasons.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
      ) : null}

      {rereview?.unexpected_mutations.length ? (
        <div className="mt-4 rounded-lg border border-red-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-red-800">
            Unexpected mutations
          </h3>
          <ul className="mt-2 space-y-1 text-sm text-red-700">
            {rereview.unexpected_mutations.map((m, i) => (
              <li key={i}>{m.message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {rereview?.orphan_rows.length ? (
        <div className="mt-4 rounded-lg border border-red-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-red-800">Orphan rows</h3>
          <ul className="mt-2 space-y-1 text-sm text-red-700">
            {rereview.orphan_rows.map((o, i) => (
              <li key={i}>{o.message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <button
        onClick={onBack}
        className="mt-5 rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50"
      >
        ← Back to plan
      </button>
    </div>
  );
}
