---
name: math-modeling-data-analysis
description: Use when supplied or discoverable modeling data needs quality, provenance, transformation, exploratory, leakage, or uncertainty analysis; do not use to choose the final model.
---

# Mathematical Modeling Data Analysis

Establish what the available data can support and leave a reproducible record of every consequential data decision.

## Input

Accept the current handoff plus available datasets, schemas, and source notes. When invoked independently, first read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) and construct or normalize the handoff before analysis.

## Responsibilities

- Inventory each source, field, unit, time range, population, sampling process, version, access condition, and provenance. Distinguish observed, supplied, joined, derived, and externally sourced values.
- Check missingness, duplicates, impossible values, anomalies, target or temporal leakage, inconsistent units, sampling bias, and join integrity. Preserve counts and examples as evidence where available.
- Propose and, when authorized, apply reasonable transformations with their rationale, order, affected fields, uncertainty implications, and reproducible artifact paths. Preserve raw values or a reversible mapping.
- Perform exploratory summaries and visual or statistical checks that are relevant to the stated subproblems. Distinguish association from causation and do not claim causal support from correlation alone.
- Translate findings into bounded modeling implications, including supported scales, features, response definitions, uncertainty, and data limitations.

## Boundaries

Do not fabricate observations or provenance, silently repair data, hide excluded records, or choose the final model. Do not invoke another skill. This stage does not announce that the full modeling task is complete.

## Output

Return an updated handoff with `state.stage` set to `data-analysis` and a justified `complete`, `needs_revision`, or `skipped` status. A skip must state why data analysis is unnecessary. In `result`, record the inventory, quality checks, transformations, exploratory evidence, uncertainty, leakage findings, and modeling implications. Preserve relative artifact paths and source provenance. In `next`, list what later formulation work may rely on and what remains unsupported; routing remains the orchestrator's decision.
