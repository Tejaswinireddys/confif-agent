import { useMemo, useState } from "react";
import { HumanInputItem, SchemaContract } from "../types";

interface Props {
  items: HumanInputItem[];
  contract: SchemaContract;
  values: Record<string, Record<string, string>>;
  onChange: (values: Record<string, Record<string, string>>) => void;
}

function opId(item: HumanInputItem): string {
  return `add-row-${item.section}-${item.row_id ?? ""}`;
}

function columnDef(contract: SchemaContract, item: HumanInputItem) {
  const section = contract.sections.find((s) => s.name === item.section);
  return section?.columns.find((c) => c.name === item.column);
}

function validateValue(
  value: string,
  item: HumanInputItem,
  contract: SchemaContract
): string | null {
  const text = value.trim();
  if (!text) return "Required";

  const col = columnDef(contract, item);
  const dataType = col?.data_type ?? item.data_type;

  if (dataType === "int") {
    if (!/^-?\d+$/.test(text)) return "Must be an integer";
    return null;
  }
  if (dataType === "ip") {
    const parts = text.split(".");
    if (parts.length !== 4 || parts.some((p) => !/^\d+$/.test(p))) {
      return "Must be a valid IPv4 address";
    }
    return null;
  }
  if (dataType === "port") {
    const n = Number(text);
    if (!Number.isInteger(n) || n < 1 || n > 65535) {
      return "Port must be 1–65535";
    }
    return null;
  }
  if (dataType === "enum") {
    const allowed = col?.enum_values ?? [];
    if (allowed.length && !allowed.includes(text)) {
      return `Must be one of: ${allowed.join(" | ")}`;
    }
    return null;
  }
  if (dataType === "bool") {
    if (!/^(true|false|1|0|yes|no)$/i.test(text)) {
      return "Must be true or false";
    }
    return null;
  }
  return null;
}

function typeHint(item: HumanInputItem, contract: SchemaContract): string {
  const col = columnDef(contract, item);
  const dataType = col?.data_type ?? item.data_type;
  if (dataType === "ip") return "IPv4 address";
  if (dataType === "port") return "Port 1–65535";
  if (dataType === "enum" && col?.enum_values?.length) {
    return col.enum_values.join(" | ");
  }
  if (dataType === "int") return "Integer";
  if (dataType === "bool") return "true / false";
  return "Text";
}

export default function HumanInputForm({
  items,
  contract,
  values,
  onChange,
}: Props) {
  const [touched, setTouched] = useState<Record<string, boolean>>({});

  const grouped = useMemo(() => {
    const map = new Map<string, HumanInputItem[]>();
    for (const item of items) {
      const id = opId(item);
      const list = map.get(id) ?? [];
      list.push(item);
      map.set(id, list);
    }
    return map;
  }, [items]);

  const allValid = useMemo(() => {
    return items.every((item) => {
      const id = opId(item);
      const val = values[id]?.[item.column] ?? "";
      return validateValue(val, item, contract) === null;
    });
  }, [items, values, contract]);

  if (items.length === 0) return null;

  function setField(op: string, field: string, value: string) {
    onChange({
      ...values,
      [op]: { ...(values[op] ?? {}), [field]: value },
    });
  }

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-5">
      <h3 className="text-sm font-semibold text-amber-900">
        Human input required
      </h3>
      <p className="mt-1 text-xs text-amber-800">
        Provide values for required fields before approving the plan.
      </p>

      <div className="mt-4 space-y-4">
        {Array.from(grouped.entries()).map(([id, groupItems]) => (
          <div
            key={id}
            className="rounded-lg border border-amber-200 bg-white p-4"
          >
            <div className="text-xs font-medium text-slate-500">
              Operation{" "}
              <span className="font-mono text-slate-700">{id}</span>
            </div>
            <div className="mt-3 space-y-3">
              {groupItems.map((item) => {
                const val = values[id]?.[item.column] ?? "";
                const error =
                  touched[`${id}.${item.column}`]
                    ? validateValue(val, item, contract)
                    : null;
                return (
                  <div key={`${id}-${item.column}`}>
                    <label className="block text-sm font-medium text-slate-700">
                      {item.section}.{item.column}
                      <span className="ml-2 text-xs font-normal text-slate-400">
                        ({typeHint(item, contract)})
                      </span>
                    </label>
                    <input
                      value={val}
                      onChange={(e) =>
                        setField(id, item.column, e.target.value)
                      }
                      onBlur={() =>
                        setTouched((t) => ({
                          ...t,
                          [`${id}.${item.column}`]: true,
                        }))
                      }
                      className={`mt-1 w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-1 ${
                        error
                          ? "border-red-300 focus:border-red-500 focus:ring-red-500"
                          : "border-slate-300 focus:border-blue-500 focus:ring-blue-500"
                      }`}
                    />
                    {error ? (
                      <div className="mt-1 text-xs text-red-600">{error}</div>
                    ) : (
                      <div className="mt-1 text-xs text-slate-500">
                        {item.why_needed}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 text-xs text-amber-800">
        {allValid ? (
          <span className="text-emerald-700">✓ All required inputs valid</span>
        ) : (
          <span>Complete all fields with valid values to continue.</span>
        )}
      </div>
    </div>
  );
}

export function humanInputsValid(
  items: HumanInputItem[],
  values: Record<string, Record<string, string>>,
  contract: SchemaContract
): boolean {
  return items.every((item) => {
    const id = opId(item);
    const val = values[id]?.[item.column] ?? "";
    return validateValue(val, item, contract) === null;
  });
}

export { opId as humanInputOpId };
