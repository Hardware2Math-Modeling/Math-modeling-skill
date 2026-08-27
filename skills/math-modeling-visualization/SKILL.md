---
name: math-modeling-visualization
description: Use when validated or diagnostic modeling results need evidence-backed figures, or when a claimed figure must be registered and checked before validation.
---

# Mathematical Modeling Visualization

Turn reproducible model outputs into traceable figures whose role and limitations are explicit.

## Input

Accept the current handoff, model results, source artifacts, and the intended figure claims. Read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) before updating workflow state.

## Responsibilities

- Match each requested figure to a specific result, source artifact, audience, and evidence or diagnostic purpose.
- Record the data source, generating code or procedure, labels, units, legend meaning, output path, and any transformations needed to reproduce the figure.
- Inspect figures at their intended presentation size for readability, clipping, misleading scales, missing uncertainty, and unsupported visual claims.
- Mark conceptual illustrations as non-data evidence and keep diagnostic plots distinct from validated result claims.

## Boundaries

Do not manufacture values, silently redraw stale results, validate the mathematical model, or write paper prose. If no figure claim exists, return a reasoned skip request for the orchestrator to evaluate against the workflow guard.

## Output

Return an updated handoff with `state.current_stage` set to `visualization` and a justified `complete`, `needs_revision`, or `skipped` status. Record figure roles, provenance, artifact paths, and QA findings in `result`. Put visual or evidentiary limitations in `quality.warnings`, set `quality.confidence`, explain the recommendation in `next.rationale`, and list alternatives in `next.alternatives`.
