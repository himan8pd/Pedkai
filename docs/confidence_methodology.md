# Confidence Calibration Methodology

This document outlines the methodology used by Pedkai to calculate the confidence scores for its Large Language Model (LLM) generated SITREPs and decision recommendations.

## Overview

Confidence scoring in Pedkai is empirical and calibrated against real-world performance. It moves away from relying on the LLM's own self-reported confidence, which is known to be unreliable and prone to hallucination. Instead, it utilizes two primary evidence sources: **Decision Memory** and **Expert Causal Evidence**, calibrated by **Operator Feedback**.

## Scoring Components

The confidence score is calculated using the following components:

### 1. Decision Memory (Base Confidence)
The most significant factor in confidence is the presence of similar past decisions in the database. 
- **Minimum:** 0.3 (Baseline for any generated analysis)
- **Increment:** +0.1 per similar decision found (cosine similarity > 0.7)
- **Maximum:** 0.8 from memory alone.

### 2. Expert Causal Evidence (Multiplier)
Expert-defined causal templates provide a strong heuristic for the validity of the analysis.
- **Increment:** +0.1 per matching expert causal template (e.g., Fiber Cut, PRB Congestion).
- **Maximum:** +0.2 total bonus from causal evidence.

### 3. Aggregate Heuristic Score
The heuristic score is the sum of Base Confidence and Expert Multiplier:
`Heuristic = Base + Expert Multiplier` (Capped at 0.95)

## Calibrated Calibration

To ensure alignment with operator expectations, Pedkai implements a "Calibrated Lookup" phase.

### Calibration Bins
Historical performance is tracked in "bins" defined by `(memory_hits, causal_evidence_count)`. For example, a bin might represent all decisions that had 2 memory hits and 1 expert causal match.

### Historical Lookup
If a specific bin has accumulated **50 or more operator feedback scores**, the system bypasses the heuristic calculation and uses the historical average operator rating.

### Scaling
Operator ratings (1-5 stars) are scaled to the confidence range [0.0, 1.0]:
`Confidence = (Avg Rating - 1) / 4`

## Thresholds

- **Standard Threshold (0.7):** SITREPs with confidence >= 0.7 are presented normally.
- **Low Confidence Fallback:** SITREPs with confidence < 0.7 are flagged with a `[LOW CONFIDENCE]` warning and revert to a template-based summary, recommending manual investigation.

## Feedback Loop

Operators provide the ground truth for calibration by submitting 1-5 star ratings for SITREPs. This feedback is persisted and used to update the calibration bins in near real-time, allowing the system to "learn" its own accuracy across different scenarios.
