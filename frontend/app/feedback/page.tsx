"use client";

import React, { useState } from "react";
import { cn } from "@/lib/utils";

type Tab = "assessment" | "history";

interface FeedbackForm {
  decisionId: string;
  accuracy: number;
  relevance: number;
  actionability: number;
  timeliness: number;
  wouldFollow: boolean | null;
  notes: string;
}

interface HistoryRow {
  decisionId: string;
  accuracy: number;
  relevance: number;
  actionability: number;
  compositeScore: number;
  submitted: string;
}

const HISTORY_ROWS: HistoryRow[] = [
  {
    decisionId: "DEC-20260310-0042",
    accuracy: 4,
    relevance: 5,
    actionability: 4,
    compositeScore: 4.3,
    submitted: "2026-03-10 14:22:05",
  },
  {
    decisionId: "DEC-20260309-0031",
    accuracy: 3,
    relevance: 4,
    actionability: 3,
    compositeScore: 3.3,
    submitted: "2026-03-09 09:47:18",
  },
  {
    decisionId: "DEC-20260307-0019",
    accuracy: 5,
    relevance: 5,
    actionability: 5,
    compositeScore: 5.0,
    submitted: "2026-03-07 17:03:44",
  },
];

const INITIAL_FORM: FeedbackForm = {
  decisionId: "",
  accuracy: 3,
  relevance: 3,
  actionability: 3,
  timeliness: 3,
  wouldFollow: null,
  notes: "",
};

function RatingSelector({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-sm text-white/80 w-32 shrink-0">{label}</span>
      <div className="flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            className={cn(
              "w-9 h-9 rounded-lg text-sm font-bold border transition-colors",
              value === n
                ? "bg-cyan-400 text-gray-950 border-cyan-400"
                : "bg-[#06203b] text-white/60 border-cyan-900/40 hover:border-cyan-400/60 hover:text-white",
            )}
          >
            {n}
          </button>
        ))}
      </div>
    </div>
  );
}

function scoreColor(score: number) {
  if (score >= 4.5) return "text-emerald-400";
  if (score >= 3.5) return "text-cyan-400";
  if (score >= 2.5) return "text-amber-300";
  return "text-red-400";
}

export default function FeedbackPage() {
  const [activeTab, setActiveTab] = useState<Tab>("assessment");
  const [form, setForm] = useState<FeedbackForm>(INITIAL_FORM);
  const [submitted, setSubmitted] = useState(false);

  function setField<K extends keyof FeedbackForm>(key: K, value: FeedbackForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    setTimeout(() => {
      setForm(INITIAL_FORM);
      setSubmitted(false);
    }, 2500);
  }

  return (
    <div className="space-y-6 p-4 md:p-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-1">Decision Feedback</h1>
        <p className="text-white/80">
          Rate AI-generated recommendations to improve future decision quality.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-2">
        {(
          [
            { key: "assessment", label: "Structured Assessment" },
            { key: "history", label: "Feedback History" },
          ] as const
        ).map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-medium transition-colors",
              activeTab === key
                ? "bg-cyan-500 text-gray-950 font-bold"
                : "bg-[#0a2d4a] text-white/80 hover:text-white hover:bg-[#0d3b5e] border border-cyan-900/40",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "assessment" && (
        <div className="bg-[#0a2d4a] border border-cyan-900/40 rounded-lg p-6 max-w-2xl">
          {submitted ? (
            <div className="py-8 text-center">
              <p className="text-emerald-400 text-lg font-bold mb-1">
                Feedback submitted
              </p>
              <p className="text-white/60 text-sm">
                Thank you. Your assessment has been recorded.
              </p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Decision ID */}
              <div>
                <label className="block text-xs font-semibold text-white/60 uppercase tracking-wider mb-1.5">
                  Decision ID
                </label>
                <input
                  type="text"
                  value={form.decisionId}
                  onChange={(e) => setField("decisionId", e.target.value)}
                  placeholder="e.g. DEC-20260311-0051"
                  className="w-full px-4 py-2.5 rounded-lg bg-[#06203b] border border-cyan-900/40 text-white placeholder-white/30 text-sm focus:outline-none focus:border-cyan-400/60"
                />
              </div>

              {/* Rating sliders */}
              <div className="space-y-3">
                <p className="text-xs font-semibold text-white/60 uppercase tracking-wider">
                  Ratings (1 = Poor, 5 = Excellent)
                </p>
                <RatingSelector
                  label="Accuracy"
                  value={form.accuracy}
                  onChange={(v) => setField("accuracy", v)}
                />
                <RatingSelector
                  label="Relevance"
                  value={form.relevance}
                  onChange={(v) => setField("relevance", v)}
                />
                <RatingSelector
                  label="Actionability"
                  value={form.actionability}
                  onChange={(v) => setField("actionability", v)}
                />
                <RatingSelector
                  label="Timeliness"
                  value={form.timeliness}
                  onChange={(v) => setField("timeliness", v)}
                />
              </div>

              {/* Would follow toggle */}
              <div>
                <p className="text-xs font-semibold text-white/60 uppercase tracking-wider mb-2">
                  Would you follow this recommendation?
                </p>
                <div className="flex gap-3">
                  {(
                    [
                      { val: true, label: "Yes" },
                      { val: false, label: "No" },
                    ] as const
                  ).map(({ val, label }) => (
                    <button
                      key={label}
                      type="button"
                      onClick={() => setField("wouldFollow", val)}
                      className={cn(
                        "px-6 py-2 rounded-lg text-sm font-bold border transition-colors",
                        form.wouldFollow === val
                          ? val
                            ? "bg-emerald-500 text-white border-emerald-500"
                            : "bg-red-600 text-white border-red-600"
                          : "bg-[#06203b] text-white/60 border-cyan-900/40 hover:text-white",
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Notes */}
              <div>
                <label className="block text-xs font-semibold text-white/60 uppercase tracking-wider mb-1.5">
                  Notes{" "}
                  <span className="normal-case font-normal">(optional)</span>
                </label>
                <textarea
                  value={form.notes}
                  onChange={(e) => setField("notes", e.target.value)}
                  rows={3}
                  placeholder="Any additional context or observations..."
                  className="w-full px-4 py-2.5 rounded-lg bg-[#06203b] border border-cyan-900/40 text-white placeholder-white/30 text-sm focus:outline-none focus:border-cyan-400/60 resize-none"
                />
              </div>

              <button
                type="submit"
                className="px-6 py-2.5 rounded-lg text-sm font-bold bg-cyan-400 hover:bg-cyan-300 text-gray-950 transition-colors"
              >
                Submit Feedback
              </button>
            </form>
          )}
        </div>
      )}

      {activeTab === "history" && (
        <div className="bg-[#0a2d4a] rounded-lg border border-cyan-900/40 overflow-hidden">
          <table className="w-full">
            <thead className="bg-[#06203b] border-b border-cyan-900/40">
              <tr>
                {[
                  "Decision ID",
                  "Accuracy",
                  "Relevance",
                  "Actionability",
                  "Composite Score",
                  "Submitted",
                ].map((col) => (
                  <th
                    key={col}
                    className="px-4 py-3 text-left text-xs font-semibold text-white/60 uppercase tracking-wider"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {HISTORY_ROWS.map((row) => (
                <tr
                  key={row.decisionId}
                  className="border-b border-cyan-900/20 hover:bg-white/5 transition-colors"
                >
                  <td className="px-4 py-3 text-sm font-mono text-white">
                    {row.decisionId}
                  </td>
                  <td className="px-4 py-3 text-sm text-white">{row.accuracy}/5</td>
                  <td className="px-4 py-3 text-sm text-white">{row.relevance}/5</td>
                  <td className="px-4 py-3 text-sm text-white">
                    {row.actionability}/5
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span className={cn("font-bold", scoreColor(row.compositeScore))}>
                      {row.compositeScore.toFixed(1)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-white/60 font-mono">
                    {row.submitted}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
