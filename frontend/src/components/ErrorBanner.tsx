import { ApiError } from "../api/client";

interface Props {
  error: unknown;
  onDismiss?: () => void;
}

const FRIENDLY: Record<string, string> = {
  CONTRACT_INVALID:
    "That schema contract isn't valid. Check the YAML structure and required fields.",
  CONTRACT_NOT_FOUND:
    "The selected contract could not be found. It may have been removed.",
  JIRA_FETCH_FAILED:
    "Couldn't reach Jira or fetch that ticket. Verify the ticket ID and Jira credentials.",
  PARSE_ERROR:
    "A config file couldn't be parsed against this contract's file format.",
  AI_EXTRACTION_FAILED:
    "The AI intent extraction step failed. You can retry, or run without a Jira ticket.",
  DIFF_PARSE_ERROR: "The provided diff couldn't be parsed.",
  RECONCILE_FAILED: "Reconciliation failed while processing the configs.",
  GAP_ANALYSIS_FAILED: "Gap analysis failed while comparing the configs.",
  PLAN_INVALID: "The merge plan is invalid or blocked.",
  HUMAN_INPUT_INVALID: "One or more human-supplied values failed validation.",
  REREVIEW_REJECTED: "Re-review rejected the merged output.",
  CREATION_SESSION_NOT_FOUND: "That creation session was not found or expired.",
};

function describe(error: unknown): { message: string; code?: string; detail?: string } {
  if (error instanceof ApiError) {
    return {
      message: FRIENDLY[error.code] ?? error.message,
      code: error.code,
      detail: error.detail,
    };
  }
  if (error instanceof Error) {
    return { message: error.message };
  }
  return { message: String(error) };
}

export default function ErrorBanner({ error, onDismiss }: Props) {
  if (!error) return null;
  const { message, code, detail } = describe(error);

  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
    >
      <span className="mt-0.5 text-red-500">&#9888;</span>
      <div className="flex-1">
        <div className="font-medium">{message}</div>
        {detail && message !== detail && (
          <div className="mt-0.5 text-red-600/80">{detail}</div>
        )}
        {code && (
          <div className="mt-1">
            <span className="rounded bg-red-100 px-1.5 py-0.5 font-mono text-[11px] text-red-700">
              {code}
            </span>
          </div>
        )}
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="rounded p-1 text-red-500 hover:bg-red-100"
          aria-label="Dismiss error"
        >
          &#10005;
        </button>
      )}
    </div>
  );
}
