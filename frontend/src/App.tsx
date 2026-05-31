import { useState } from "react";
import ContractPicker from "./components/ContractPicker";
import UploadPanel from "./components/UploadPanel";
import ReviewPage from "./pages/ReviewPage";
import CreatePage from "./pages/CreatePage";
import { ReconciliationReport, SchemaContract } from "./types";

type AppMode = "review" | "create";
type Step = "pick" | "upload" | "review" | "create";

export default function App() {
  const [mode, setMode] = useState<AppMode>("review");
  const [step, setStep] = useState<Step>("pick");
  const [contract, setContract] = useState<SchemaContract | null>(null);
  const [report, setReport] = useState<ReconciliationReport | null>(null);

  function handleModeChange(next: AppMode) {
    setMode(next);
    setStep("pick");
    setContract(null);
    setReport(null);
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-4 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-lg font-semibold text-slate-800">
              Config Reconciler
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
              schema-driven
            </span>
          </div>
          <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-sm">
            <button
              onClick={() => handleModeChange("review")}
              className={`rounded-md px-3 py-1.5 font-medium ${
                mode === "review"
                  ? "bg-white text-slate-800 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              Review
            </button>
            <button
              onClick={() => handleModeChange("create")}
              className={`rounded-md px-3 py-1.5 font-medium ${
                mode === "create"
                  ? "bg-white text-slate-800 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              Create
            </button>
          </div>
        </div>
      </header>

      <main className="px-4 py-8">
        {step === "pick" && (
          <ContractPicker
            onSelect={(c) => {
              setContract(c);
              setStep(mode === "create" ? "create" : "upload");
            }}
          />
        )}

        {step === "upload" && contract && mode === "review" && (
          <UploadPanel
            contract={contract}
            onBack={() => setStep("pick")}
            onComplete={(r) => {
              setReport(r);
              setStep("review");
            }}
          />
        )}

        {step === "create" && contract && mode === "create" && (
          <CreatePage contract={contract} onBack={() => setStep("pick")} />
        )}

        {step === "review" && report && (
          <ReviewPage report={report} onBack={() => setStep("upload")} />
        )}
      </main>
    </div>
  );
}
