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
        <div className="bg-[#06203b]/40 border border-[rgba(7,242,219,0.08)] rounded-xl p-6 space-y-4">
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
                                    "w-7 h-7 transition-colors duration-150",
                                    s <= score ? "fill-amber-400 text-amber-400" : "text-white/20 hover:text-white/40"
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
                className="w-full bg-[#06203b] border border-[rgba(7,242,219,0.12)] rounded-lg p-3 text-sm text-white/80 placeholder-white/25 focus:ring-1 focus:ring-cyan-400/50 focus:border-cyan-400/30 outline-none h-32 resize-none transition-colors duration-200"
            />

            <button
                onClick={handleSubmit}
                disabled={score === 0 || submitting}
                className={cn(
                    "w-full py-2 rounded-lg font-bold flex items-center justify-center gap-2 transition-all duration-200",
                    score > 0 && !submitting
                        ? "bg-cyan-400 hover:bg-cyan-300 text-gray-950"
                        : "bg-white/5 text-white/30 cursor-not-allowed"
                )}
            >
                {submitting ? "Submitting..." : <><Send className="w-4 h-4" /> Submit Feedback</>}
            </button>
        </div>
    )
}
