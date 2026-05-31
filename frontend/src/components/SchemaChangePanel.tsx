import { SchemaChange } from "../types";
import { schemaChangeStyle } from "../lib/ui";

interface Props {
  changes: SchemaChange[];
}

const TYPE_LABEL: Record<SchemaChange["change_type"], string> = {
  COLUMN_ADDED: "added",
  COLUMN_REMOVED: "removed",
  COLUMN_REORDERED: "reordered",
  UNDECLARED_COLUMN: "undeclared",
};

export default function SchemaChangePanel({ changes }: Props) {
  if (changes.length === 0) return null;

  const bySection = changes.reduce<Record<string, SchemaChange[]>>(
    (acc, change) => {
      (acc[change.section] ??= []).push(change);
      return acc;
    },
    {}
  );

  return (
    <div className="rounded-xl border border-purple-200 bg-white shadow-sm">
      <div className="border-b border-purple-100 bg-purple-50 px-4 py-2.5 text-sm font-semibold text-purple-800">
        Schema changes ({changes.length})
      </div>
      <div className="space-y-3 p-4">
        {Object.entries(bySection).map(([section, items]) => (
          <div key={section}>
            <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
              {section}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-2">
              {items.map((change, i) => (
                <span
                  key={`${change.column_name}-${i}`}
                  className={`rounded-md border px-2 py-1 text-xs ${schemaChangeStyle(
                    change.change_type
                  )}`}
                  title={
                    change.base_index != null || change.new_index != null
                      ? `base #${change.base_index ?? "—"} → new #${
                          change.new_index ?? "—"
                        }`
                      : undefined
                  }
                >
                  <span className="font-mono font-semibold">
                    {change.column_name}
                  </span>{" "}
                  {TYPE_LABEL[change.change_type]}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
