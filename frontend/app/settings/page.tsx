"use client";

import React, { useState } from "react";
import { cn } from "@/lib/utils";

interface DetectionThresholds {
  sleepingCellInterval: number;
  decayLambda: number;
  anomalyZScore: number;
}

interface EvaluationSettings {
  benchmarkThreshold: number;
  lookbackDays: number;
}

function SectionSaveButton({
  saved,
  onClick,
}: {
  saved: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "px-5 py-2 rounded-lg text-sm font-bold transition-colors",
        saved
          ? "bg-emerald-600 text-white cursor-default"
          : "bg-cyan-400 hover:bg-cyan-300 text-gray-950",
      )}
    >
      {saved ? "Applied (session)" : "Apply"}
    </button>
  );
}

function InputRow({
  label,
  hint,
  value,
  type = "number",
  step,
  onChange,
}: {
  label: string;
  hint?: string;
  value: string | number;
  type?: string;
  step?: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-6 flex-wrap">
      <div className="flex-1 min-w-0">
        <p className="text-sm text-white font-medium">{label}</p>
        {hint && <p className="text-xs text-white/50 mt-0.5">{hint}</p>}
      </div>
      <input
        type={type}
        step={step}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-36 px-3 py-2 rounded-lg bg-[#06203b] border border-cyan-900/40 text-white text-sm focus:outline-none focus:border-cyan-400/60 text-right"
      />
    </div>
  );
}

function ReadOnlyField({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-sm text-white font-medium">{label}</p>
      <div className="w-full px-4 py-2.5 rounded-lg bg-[#06203b]/60 border border-cyan-900/30 text-white/60 text-sm select-all">
        {value || "Not Configured"}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [detection, setDetection] = useState<DetectionThresholds>({
    sleepingCellInterval: 15,
    decayLambda: 0.05,
    anomalyZScore: 2.5,
  });
  const [detectionSaved, setDetectionSaved] = useState(false);

  const [evaluation, setEvaluation] = useState<EvaluationSettings>({
    benchmarkThreshold: 0.9,
    lookbackDays: 30,
  });
  const [evaluationSaved, setEvaluationSaved] = useState(false);

  function saveDetection() {
    setDetectionSaved(true);
    setTimeout(() => setDetectionSaved(false), 2000);
  }

  function saveEvaluation() {
    setEvaluationSaved(true);
    setTimeout(() => setEvaluationSaved(false), 2000);
  }

  return (
    <div className="space-y-6 p-4 md:p-8 max-w-3xl">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-1">System Settings</h1>
        <p className="text-white/80">
          Detection thresholds, integrations, and evaluation parameters.
        </p>
      </div>

      <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 px-4 py-3 text-xs text-amber-300/80">
        Settings shown below reflect deployment defaults. Changes are applied to
        the current session only and will reset on page reload. Backend persistence
        is planned for a future release.
      </div>

      {/* Detection Thresholds */}
      <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-6 space-y-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h2 className="text-base font-bold text-white">
              Detection Thresholds
            </h2>
            <p className="text-xs text-white/50 mt-0.5">
              Controls sleeping cell and anomaly detection sensitivity.
            </p>
          </div>
          <SectionSaveButton saved={detectionSaved} onClick={saveDetection} />
        </div>
        <div className="border-t border-cyan-900/40 pt-4 space-y-4">
          <InputRow
            label="Sleeping Cell Interval"
            hint="How often to run detection (minutes)"
            value={detection.sleepingCellInterval}
            step="1"
            onChange={(v) =>
              setDetection((p) => ({
                ...p,
                sleepingCellInterval: Number(v),
              }))
            }
          />
          <InputRow
            label="Decay Lambda"
            hint="Exponential decay rate (0.01 -- 0.5)"
            value={detection.decayLambda}
            step="0.001"
            onChange={(v) =>
              setDetection((p) => ({ ...p, decayLambda: Number(v) }))
            }
          />
          <InputRow
            label="Anomaly Z-Score Threshold"
            hint="Standard deviations above mean to flag anomaly"
            value={detection.anomalyZScore}
            step="0.1"
            onChange={(v) =>
              setDetection((p) => ({ ...p, anomalyZScore: Number(v) }))
            }
          />
        </div>
      </div>

      {/* Integrations (read-only) */}
      <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-6 space-y-5">
        <div>
          <h2 className="text-base font-bold text-white">Integrations</h2>
          <p className="text-xs text-white/50 mt-0.5">
            External system endpoints for ITSM and CMDB.
          </p>
        </div>
        <div className="border-t border-cyan-900/40 pt-4 space-y-5">
          <ReadOnlyField label="ServiceNow URL" value="Not Configured" />
          <ReadOnlyField label="Datagerry URL" value="Not Configured" />
        </div>
        <p className="text-xs text-white/60 bg-[#06203b]/50 border border-cyan-900/30 rounded-lg px-4 py-3">
          Integration endpoints are configured in the deployment environment.
          Contact your administrator to modify.
        </p>
      </div>

      {/* Evaluation */}
      <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-6 space-y-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h2 className="text-base font-bold text-white">Evaluation</h2>
            <p className="text-xs text-white/50 mt-0.5">
              Scoring benchmark and analysis window for feedback evaluation.
            </p>
          </div>
          <SectionSaveButton saved={evaluationSaved} onClick={saveEvaluation} />
        </div>
        <div className="border-t border-cyan-900/40 pt-4 space-y-4">
          <InputRow
            label="Benchmark Threshold"
            hint="Minimum acceptable composite score (0.0 -- 1.0)"
            value={evaluation.benchmarkThreshold}
            step="0.01"
            onChange={(v) =>
              setEvaluation((p) => ({ ...p, benchmarkThreshold: Number(v) }))
            }
          />
          <InputRow
            label="Lookback Days"
            hint="Number of days of history used in evaluation"
            value={evaluation.lookbackDays}
            step="1"
            onChange={(v) =>
              setEvaluation((p) => ({ ...p, lookbackDays: Number(v) }))
            }
          />
        </div>
      </div>
    </div>
  );
}
