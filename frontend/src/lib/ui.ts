// Shared Tailwind class maps for decisions, change types, and confidence.

import { Decision, FindingChangeType, SchemaChangeType } from "../types";

export interface Style {
  badge: string; // background + text for solid badges
  soft: string; // subtle background + text + border
  dot: string; // small indicator dot
  label: string;
}

export const DECISION_STYLES: Record<Decision, Style> = {
  AUTO_APPLY: {
    badge: "bg-emerald-600 text-white",
    soft: "bg-emerald-50 text-emerald-700 border-emerald-200",
    dot: "bg-emerald-500",
    label: "Auto-apply",
  },
  SUGGEST: {
    badge: "bg-blue-600 text-white",
    soft: "bg-blue-50 text-blue-700 border-blue-200",
    dot: "bg-blue-500",
    label: "Suggest",
  },
  ESCALATE: {
    badge: "bg-amber-500 text-white",
    soft: "bg-amber-50 text-amber-700 border-amber-200",
    dot: "bg-amber-500",
    label: "Escalate",
  },
  BLOCK: {
    badge: "bg-red-600 text-white",
    soft: "bg-red-50 text-red-700 border-red-200",
    dot: "bg-red-500",
    label: "Block",
  },
};

export const DECISION_ORDER: Decision[] = [
  "AUTO_APPLY",
  "SUGGEST",
  "ESCALATE",
  "BLOCK",
];

export function changeTypeStyle(change: FindingChangeType): string {
  switch (change) {
    case "ADDED":
    case "COLUMN_ADDED":
      return "bg-emerald-100 text-emerald-800 border border-emerald-200";
    case "REMOVED":
    case "COLUMN_REMOVED":
      return "bg-red-100 text-red-800 border border-red-200";
    case "MODIFIED":
      return "bg-indigo-100 text-indigo-800 border border-indigo-200";
    default:
      return "bg-slate-100 text-slate-700 border border-slate-200";
  }
}

export function schemaChangeStyle(change: SchemaChangeType): string {
  switch (change) {
    case "COLUMN_REMOVED":
      return "bg-red-50 text-red-700 border-red-200";
    case "COLUMN_ADDED":
      return "bg-blue-50 text-blue-700 border-blue-200";
    case "COLUMN_REORDERED":
      return "bg-slate-50 text-slate-600 border-slate-200";
    case "UNDECLARED_COLUMN":
      return "bg-amber-50 text-amber-700 border-amber-200";
    default:
      return "bg-slate-50 text-slate-600 border-slate-200";
  }
}

export const PROVENANCE_STYLES: Record<string, string> = {
  from_new_file: "bg-blue-50 text-blue-700 border-blue-200",
  auto_allocated: "bg-emerald-50 text-emerald-700 border-emerald-200",
  contract_default: "bg-slate-100 text-slate-600 border-slate-200",
  human_supplied: "bg-purple-50 text-purple-700 border-purple-200",
  needs_human: "bg-amber-50 text-amber-700 border-amber-200",
};

export const PROVENANCE_LABELS: Record<string, string> = {
  from_new_file: "From new file",
  auto_allocated: "Auto allocated",
  contract_default: "Contract default",
  human_supplied: "Human supplied",
  needs_human: "Needs human",
};
