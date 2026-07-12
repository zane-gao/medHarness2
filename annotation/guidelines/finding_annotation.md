# Finding Annotation Guideline v1.0

## Purpose

Annotate clinically meaningful findings independently in the reference and each blinded candidate report. Do not infer findings from expected disease prevalence or model identity.

## Unit Of Annotation

One finding is one observation with its anatomy, laterality, certainty, severity and measurements. Split findings when they have different observations, locations or certainty.

## Required Fields

- `finding_id`: unique within the report, such as `ref-f01` or `candidate-01-f01`.
- `observation_text`: concise canonical clinical concept.
- `location_text`: anatomy as stated in the report; do not guess missing anatomy.
- `laterality`: left, right, bilateral, midline or unknown.
- `certainty`: present, absent or uncertain.
- `severity`: copy the stated grade or leave null.
- `measurements`: value and unit exactly supported by the report.
- `source`: reference or candidate.

## Rules

1. Record pertinent negatives as `certainty=absent` when clinically meaningful.
2. Do not turn recommendations, history or differential diagnosis into present findings.
3. Preserve uncertainty words such as possible, suspicious for and cannot exclude.
4. Do not use information from another report while annotating the current report.
5. Use `notes` only for ambiguity that requires adjudication.

## Pilot Process

Reader A and Reader B annotate independently. They must not inspect each other's labels. The adjudicator reviews only disagreement cases after both readers mark the case complete.
