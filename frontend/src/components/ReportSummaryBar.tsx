import { Decision, Filter, ReconciliationReport } from "../types";
import { DECISION_ORDER, DECISION_STYLES } from "../lib/ui";

interface Props {
  report: ReconciliationReport;
  filter: Filter;
  onFilter: (filter: Filter) => void;
}

interface BadgeProps {
  label: string;
  count: number;
  solid: string;
  active: boolean;
  onClick: () => void;
}

function Badge({ label, count, solid, active, onClick }: BadgeProps) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium transition ${solid} ${
        active ? "ring-2 ring-offset-2 ring-slate-400" : "opacity-90 hover:opacity-100"
      }`}
    >
      <span>{label}</span>
      <span className="rounded-full bg-white/25 px-1.5 text-xs font-semibold">
        {count}
      </span>
    </button>
  );
}

export default function ReportSummaryBar({ report, filter, onFilter }: Props) {
  const decisions = report.summary.decisions;

  function toggle(next: Filter) {
    onFilter(filter === next ? null : next);
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        onClick={() => onFilter(null)}
        className={`rounded-full border px-3 py-1.5 text-sm font-medium transition ${
          filter === null
            ? "border-slate-800 bg-slate-800 text-white"
            : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
        }`}
      >
        All
      </button>

      {DECISION_ORDER.map((d: Decision) => (
        <Badge
          key={d}
          label={DECISION_STYLES[d].label}
          count={decisions[d] ?? 0}
          solid={DECISION_STYLES[d].badge}
          active={filter === d}
          onClick={() => toggle(d)}
        />
      ))}

      <Badge
        label="Schema changes"
        count={report.summary.schema_changes}
        solid="bg-purple-600 text-white"
        active={filter === "SCHEMA"}
        onClick={() => toggle("SCHEMA")}
      />
      <Badge
        label="Violations"
        count={report.summary.integrity_violations}
        solid="bg-red-600 text-white"
        active={filter === "VIOLATIONS"}
        onClick={() => toggle("VIOLATIONS")}
      />
    </div>
  );
}
