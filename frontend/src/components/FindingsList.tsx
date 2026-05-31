import { useState } from "react";
import { AgentFinding, ApplyActionValue, Filter } from "../types";
import FindingCard from "./FindingCard";

interface Props {
  findings: AgentFinding[];
  filter: Filter;
  decisions: Record<string, ApplyActionValue>;
  onDecision: (findingId: string, action: ApplyActionValue) => void;
}

function matchesFilter(finding: AgentFinding, filter: Filter): boolean {
  if (filter === null) return true;
  if (filter === "SCHEMA") {
    return (
      finding.change_type === "COLUMN_ADDED" ||
      finding.change_type === "COLUMN_REMOVED"
    );
  }
  if (filter === "VIOLATIONS") {
    return !finding.fk_valid || !finding.companion_rows_present;
  }
  return finding.decision === filter;
}

function SectionGroup({
  section,
  findings,
  decisions,
  onDecision,
}: {
  section: string;
  findings: AgentFinding[];
  decisions: Record<string, ApplyActionValue>;
  onDecision: (findingId: string, action: ApplyActionValue) => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-lg px-1 py-1.5 text-left hover:bg-slate-50"
      >
        <span className="text-slate-400">{open ? "▾" : "▸"}</span>
        <span className="text-sm font-semibold text-slate-700">{section}</span>
        <span className="rounded-full bg-slate-100 px-2 text-xs font-medium text-slate-500">
          {findings.length}
        </span>
      </button>
      {open && (
        <div className="mt-2 space-y-3">
          {findings.map((finding) => (
            <FindingCard
              key={finding.finding_id}
              finding={finding}
              decision={decisions[finding.finding_id]}
              onDecision={onDecision}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function FindingsList({
  findings,
  filter,
  decisions,
  onDecision,
}: Props) {
  const filtered = findings.filter((f) => matchesFilter(f, filter));

  if (filtered.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">
        {findings.length === 0
          ? "No findings — the two configs are equivalent under this contract."
          : "No findings match the current filter."}
      </div>
    );
  }

  const sections: string[] = [];
  const bySection: Record<string, AgentFinding[]> = {};
  for (const finding of filtered) {
    if (!bySection[finding.section]) {
      bySection[finding.section] = [];
      sections.push(finding.section);
    }
    bySection[finding.section].push(finding);
  }

  return (
    <div className="space-y-5">
      {sections.map((section) => (
        <SectionGroup
          key={section}
          section={section}
          findings={bySection[section]}
          decisions={decisions}
          onDecision={onDecision}
        />
      ))}
    </div>
  );
}
