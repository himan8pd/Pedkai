"use client";

import React, { useState } from "react";
import { cn } from "@/lib/utils";

interface DetectionThresholds {
  sleepingCellInterval: number;
  decayLambda: number;
  anomalyZScore: number;
}

interface Integrations {
  serviceNowUrl: string;
  datagerryUrl: string;
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
      {saved ? "Saved" : "Save"}
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

function ConnectionBadge({ connected }: { connected: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold border",
        connected
          ? "bg-emerald-900/50 text-emerald-300 border-emerald-700/60"
          : "bg-red-900/50 text-red-300 border-red-700/60",
      )}
    >
      <span
        className={cn(
          "w-1.5 h-1.5 rounded-full",
          connected ? "bg-emerald-400" : "bg-red-400",
        )}
      />
      {connected ? "Connected" : "Disconnected"}
    </span>
  );
}

export default function SettingsPage() {
  const [detection, setDetection] = useState<DetectionThresholds>({
    sleepingCellInterval: 15,
    decayLambda: 0.05,
    anomalyZScore: 2.5,
  });
  const [detectionSaved, setDetectionSaved] = useState(false);

  const [integrations, setIntegrations] = useState<Integrations>({
    serviceNowUrl: "https://instance.service-now.com",
    datagerryUrl: "http://localhost:4000",
  });
  const [integrationsSaved, setIntegrationsSaved] = useState(false);

  const [evaluation, setEvaluation] = useState<EvaluationSettings>({
    benchmarkThreshold: 0.9,
    lookbackDays: 30,
  });
  const [evaluationSaved, setEvaluationSaved] = useState(false);

  function saveDetection() {
    setDetectionSaved(true);
    setTimeout(() => setDetectionSaved(false), 2000);
  }

  function saveIntegrations() {
    setIntegrationsSaved(true);
    setTimeout(() => setIntegrationsSaved(false), 2000);
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
          Configure detection thresholds, integrations, and evaluation parameters.
        </p>
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
            hint="Exponential decay rate (0.01 – 0.5)"
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

      {/* Integrations */}
      <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-6 space-y-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h2 className="text-base font-bold text-white">Integrations</h2>
            <p className="text-xs text-white/50 mt-0.5">
              External system endpoints for ITSM and CMDB.
            </p>
          </div>
          <SectionSaveButton saved={integrationsSaved} onClick={saveIntegrations} />
        </div>
        <div className="border-t border-cyan-900/40 pt-4 space-y-5">
          {/* ServiceNow */}
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <p className="text-sm text-white font-medium flex-1">
                ServiceNow URL
              </p>
              <ConnectionBadge connected={integrations.serviceNowUrl.startsWith("https://")} />
            </div>
            <input
              type="text"
              value={integrations.serviceNowUrl}
              onChange={(e) =>
                setIntegrations((p) => ({ ...p, serviceNowUrl: e.target.value }))
              }
              placeholder="https://instance.service-now.com"
              className="w-full px-4 py-2.5 rounded-lg bg-[#06203b] border border-cyan-900/40 text-white placeholder-white/30 text-sm focus:outline-none focus:border-cyan-400/60"
            />
          </div>
          {/* Datagerry */}
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <p className="text-sm text-white font-medium flex-1">
                Datagerry URL
              </p>
              <ConnectionBadge connected={false} />
            </div>
            <input
              type="text"
              value={integrations.datagerryUrl}
              onChange={(e) =>
                setIntegrations((p) => ({ ...p, datagerryUrl: e.target.value }))
              }
              placeholder="http://localhost:4000"
              className="w-full px-4 py-2.5 rounded-lg bg-[#06203b] border border-cyan-900/40 text-white placeholder-white/30 text-sm focus:outline-none focus:border-cyan-400/60"
            />
          </div>
        </div>
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
            hint="Minimum acceptable composite score (0.0 – 1.0)"
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
