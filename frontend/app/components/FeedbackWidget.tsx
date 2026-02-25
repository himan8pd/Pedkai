import React, { useState } from 'react'
import { Star, Send } from 'lucide-react'
import { cn } from '@/lib/utils'

interface FeedbackWidgetProps {
    decisionId: string
    onFeedbackSubmitted?: () => void
}

export default function FeedbackWidget({ decisionId, onFeedbackSubmitted }: FeedbackWidgetProps) {
    const [score, setScore] = useState(0)
    const [comment, setComment] = useState('')
    const [submitting, setSubmitting] = useState(false)
    const [submitted, setSubmitted] = useState(false)

    const handleSubmit = async () => {
        if (score === 0) return

        setSubmitting(true)
        try {
            const resp = await fetch(`/api/v1/decisions/${decisionId}/feedback`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ score, comment })
            })

            if (resp.ok) {
                setSubmitted(true)
                if (onFeedbackSubmitted) onFeedbackSubmitted()
            }
        } catch (err) {
            console.error('Failed to submit feedback', err)
        } finally {
            setSubmitting(false)
        }
    }

    if (submitted) {
        return (
            <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-4 text-center">
                <p className="text-emerald-400 text-sm font-bold">Thank you for your feedback!</p>
            </div>
        )
    }

    return (
        <div className="bg-slate-900/40 border border-slate-800/60 rounded-xl p-6 space-y-4">
            <div className="flex items-center justify-between">
                <h4 className="text-white text-sm font-bold uppercase tracking-wider">Rate this analysis</h4>
                <div className="flex gap-1">
                    {[1, 2, 3, 4, 5].map((s) => (
                        <button
                            key={s}
                            onClick={() => setScore(s)}
                            className="focus:outline-none transition-transform active:scale-90"
                        >
                            <Star
                                className={cn(
                                    "w-5 h-5",
                                    s <= score ? "fill-amber-400 text-amber-400" : "text-slate-600 hover:text-slate-400"
                                )}
                            />
                        </button>
                    ))}
                </div>
            </div>

            <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Optional comment..."
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-sm text-slate-300 focus:ring-1 focus:ring-cyan-500 outline-none h-20 resize-none"
            />

            <button
                onClick={handleSubmit}
                disabled={score === 0 || submitting}
                className={cn(
                    "w-full py-2 rounded-lg font-bold flex items-center justify-center gap-2 transition-all",
                    score > 0 && !submitting
                        ? "bg-cyan-600 hover:bg-cyan-500 text-white"
                        : "bg-slate-800 text-slate-500 cursor-not-allowed"
                )}
            >
                {submitting ? "Submitting..." : <><Send className="w-4 h-4" /> Submit Feedback</>}
            </button>
        </div>
    )
}
