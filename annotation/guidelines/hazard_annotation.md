# Hazard Annotation Guideline v1.0

## Purpose

Classify clinically meaningful differences between a blinded candidate report and the reference report, then assign potential harm severity.

## Error Types

- `omission_finding`: reference finding absent from candidate.
- `false_finding`: candidate asserts a finding unsupported by reference.
- `incorrect_location`: observation matches but anatomy or laterality is wrong.
- `incorrect_severity`: observation matches but severity is materially wrong.
- `mismatched_finding`: clinically relevant measurement or attribute mismatch.
- `contradiction`: candidate reverses presence, absence or key conclusion.
- `other`: use only with a clear rationale.

## Hazard Levels

1. No meaningful expected clinical impact.
2. Minor impact; unlikely to alter management.
3. Moderate impact; may cause additional workup or delayed clarification.
4. High impact; likely to alter treatment, triage or follow-up.
5. Critical impact; plausible immediate threat to life or major irreversible harm.

## Required Fields

Every hazard label must identify the candidate, error type, hazard level, clinical significance, evidence finding IDs and a short clinical rationale. Do not write private chain-of-thought; record only the concise adjudicable rationale.

## Adjudication

The adjudicator resolves error type and hazard level disagreements. Original reader labels remain immutable and are retained for inter-rater agreement analysis.
