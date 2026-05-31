import { useState } from "react";
import { IntegrityViolation } from "../types";

interface Props {
  violations: IntegrityViolation[];
}

export default function IntegrityViolationPanel({ violations }: Props) {
  const [open, setOpen] = useState(true);
  if (violations.length === 0) return null;

  return (
    <div className="overflow-hidden rounded-xl border border-red-200 bg-white shadow-sm">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between bg-red-600 px-4 py-2.5 text-left text-sm font-semibold text-white"
      >
        <span>Integrity violations ({violations.length})</span>
        <span className="text-red-100">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <ul className="divide-y divide-red-50">
          {violations.map((v, i) => (
            <li key={i} className="px-4 py-2.5 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                  {v.violation_type}
                </span>
                <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                  {v.section}
                </span>
                {v.row_id != null && (
                  <span className="font-mono text-xs text-slate-500">
                    #{v.row_id}
                  </span>
                )}
                <span className="ml-auto text-xs font-medium text-red-600">
                  Always blocked
                </span>
              </div>
              <div className="mt-1 text-slate-700">{v.message}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
