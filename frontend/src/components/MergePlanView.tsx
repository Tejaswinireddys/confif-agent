import { MergeOperation, MergePlan } from "../types";
import { PROVENANCE_LABELS, PROVENANCE_STYLES } from "../lib/ui";

interface Props {
  plan: MergePlan;
  approvals: Set<string>;
  onToggleApproval: (opId: string) => void;
}

const OP_BADGE: Record<string, string> = {
  ADD_ROW: "bg-emerald-100 text-emerald-800",
  ADD_COLUMN: "bg-blue-100 text-blue-800",
  ALLOCATE_ID: "bg-teal-100 text-teal-800",
  RESOLVE_FK: "bg-indigo-100 text-indigo-800",
  FILL_DEFAULT: "bg-slate-100 text-slate-700",
  REQUIRE_HUMAN_INPUT: "bg-amber-100 text-amber-800",
};

function approvable(op: MergeOperation): boolean {
  return op.op_type === "ADD_ROW" || op.op_type === "ADD_COLUMN";
}

function groupBySection(ops: MergeOperation[]): Map<string, MergeOperation[]> {
  const map = new Map<string, MergeOperation[]>();
  for (const op of ops) {
    const list = map.get(op.section) ?? [];
    list.push(op);
    map.set(op.section, list);
  }
  return map;
}

function OperationCard({
  op,
  approved,
  onToggle,
}: {
  op: MergeOperation;
  approved: boolean;
  onToggle: () => void;
}) {
  const fields = Object.keys(op.values);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded px-2 py-0.5 text-xs font-semibold ${
                OP_BADGE[op.op_type] ?? "bg-slate-100 text-slate-700"
              }`}
            >
              {op.op_type}
            </span>
            <span className="font-mono text-sm text-slate-800">
              {op.section}
              {op.target_id ? `#${op.target_id}` : ""}
            </span>
          </div>
          <p className="mt-1 text-xs text-slate-500">{op.reason}</p>
        </div>
        {approvable(op) ? (
          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={approved}
              onChange={onToggle}
              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            Approve
          </label>
        ) : null}
      </div>

      {fields.length > 0 ? (
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-100 text-slate-500">
                <th className="py-1 pr-4 font-medium">Field</th>
                <th className="py-1 pr-4 font-medium">Value</th>
                <th className="py-1 font-medium">Provenance</th>
              </tr>
            </thead>
            <tbody>
              {fields.map((field) => {
                const prov = op.provenance[field] ?? "from_new_file";
                return (
                  <tr key={field} className="border-b border-slate-50">
                    <td className="py-1.5 pr-4 font-mono text-slate-700">
                      {field}
                    </td>
                    <td className="py-1.5 pr-4 text-slate-800">
                      {op.values[field]}
                    </td>
                    <td className="py-1.5">
                      <span
                        className={`rounded border px-1.5 py-0.5 text-[11px] font-medium ${
                          PROVENANCE_STYLES[prov] ??
                          "bg-slate-100 text-slate-600 border-slate-200"
                        }`}
                      >
                        {PROVENANCE_LABELS[prov] ?? prov}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

export default function MergePlanView({
  plan,
  approvals,
  onToggleApproval,
}: Props) {
  const grouped = groupBySection(plan.operations);

  return (
    <div className="space-y-6">
      {plan.blocked.length > 0 ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4">
          <h3 className="text-sm font-semibold text-red-800">
            Blocked operations
          </h3>
          <p className="mt-1 text-xs text-red-600">
            These cannot be approved or applied.
          </p>
          <ul className="mt-3 space-y-2">
            {plan.blocked.map((item, index) => (
              <li
                key={`${item.section}-${item.target_id}-${index}`}
                className="rounded-lg border border-red-200 bg-white px-3 py-2 text-sm text-red-800"
              >
                <span className="font-mono">
                  {item.section}
                  {item.target_id ? `#${item.target_id}` : ""}
                </span>
                <div className="mt-0.5 text-xs text-red-600">{item.reason}</div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {Array.from(grouped.entries()).map(([section, ops]) => (
        <div key={section}>
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
            {section}
          </h3>
          <div className="space-y-3">
            {ops.map((op) => (
              <OperationCard
                key={op.op_id}
                op={op}
                approved={approvals.has(op.op_id)}
                onToggle={() => onToggleApproval(op.op_id)}
              />
            ))}
          </div>
        </div>
      ))}

      {plan.operations.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
          No merge operations in this plan.
        </div>
      ) : null}
    </div>
  );
}
