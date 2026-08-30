---
name: math-modeling-data-analysis
description: Use when supplied or discoverable modeling data needs quality, provenance, transformation, exploratory, leakage, or uncertainty analysis; do not use to choose the final model.
---

# Mathematical Modeling Data Analysis

Establish what the available data can support and leave a reproducible record of every consequential data decision.

## Input

Accept the current handoff plus available datasets, schemas, and source notes. When invoked independently, first read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) and construct or normalize the handoff before analysis.

## External-data approval gate

Require an exact approval record that runtime-validates against the shared `external-data-approval.schema.json` before any download of external modeling data. It contains `purpose`, `fields`, `source`, `license`, `risk`, and `user_confirmation: true`, recording 用途、字段、来源、许可证、风险和用户确认 for this exact acquisition scope. A URL, teammate instruction, prior approval for different fields, added agent field, or vague authorization is not a substitute.

If the record is missing, incomplete, stale, or has `user_confirmation` other than `true`, pause without downloading and return `needs_revision` with the missing fields in `next.failed_checks`. Official-rule or template read-only verification is not external modeling data; its source, SHA-256, and verification date remain governed by the orchestrator.

## Responsibilities

- Inventory each source, field, unit, time range, population, sampling process, version, access condition, approval record, and provenance. Distinguish observed, supplied, joined, derived, and externally sourced values.
- Check missingness, duplicates, impossible values, anomalies, target or temporal leakage, inconsistent units, sampling bias, and join integrity. Preserve counts and examples as evidence where available.
- Propose and, when authorized, apply reasonable transformations with their rationale, order, affected fields, uncertainty implications, and reproducible artifact paths. Preserve raw values or a reversible mapping.
- Perform exploratory summaries and visual or statistical checks that are relevant to the stated subproblems. Distinguish association from causation and do not claim causal support from correlation alone.
- Translate findings into bounded modeling implications, including supported scales, features, response definitions, uncertainty, and data limitations.

## Boundaries

Do not fabricate observations or provenance, silently repair data, hide excluded records, download unapproved external data, or choose the final model. Do not invoke another skill. This stage does not announce that the full modeling task is complete.

## Output

Return an updated handoff that preserves `task.statement`, `task.objectives`, and `task.constraints`, and set `state.current_stage` to `data-analysis` with a justified `complete`, `needs_revision`, or `skipped` status. In `context.data` preserve any external-data approval; in `result`, record the inventory, transformations, exploratory evidence, leakage findings, and modeling implications, with relative artifact paths and source provenance. Put data-quality checks in `quality.checks`, limitations and uncertainty in `quality.warnings`, and an evidence-based level in `quality.confidence`. Set `next.recommended_stage`, explain supported inputs, unsupported claims, or a skip in `next.rationale`, and list bounded alternatives in `next.alternatives`; routing remains the orchestrator's decision.
