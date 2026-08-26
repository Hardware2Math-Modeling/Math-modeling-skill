---
name: math-modeling-validation
description: Use when a mathematical model or its results need evidence-based checks of fit, feasibility, sensitivity, uncertainty, robustness, dimensions, boundaries, or baselines; do not use to draft a paper.
---

# Mathematical Modeling Validation

Decide explicitly whether the model's supported claims pass prespecified checks, and identify the smallest evidence-backed rollback when they do not.

## Input

Accept the current handoff with the model specification, solution evidence, artifacts, and prespecified tests. When invoked independently, first read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) and normalize the handoff before validation.

## Responsibilities

- Apply the checks appropriate to the claim and available evidence: fit, residual diagnostics, holdout performance, sensitivity, uncertainty, robustness, feasibility, dimensional consistency, boundary behavior, and comparison with a meaningful baseline.
- Use acceptance thresholds specified before seeing validation outcomes. If a threshold must change, record why, treat the prior check as failed or inconclusive, and rerun the affected validation; never move a threshold merely to pass.
- Trace every check to the exact result, command, dataset scope, seed where relevant, and relative artifact path. Training fit alone cannot substitute for available holdout, boundary, sensitivity, or robustness evidence.
- State limitations, failure domains, extrapolation boundaries, data scope, and uncertainty without hiding contradictory evidence.
- Return an explicit pass only when all required checks meet their thresholds. Otherwise return `needs_revision`, name the failed checks, and recommend the earliest evidence-supported rollback: problem analysis for objective, constraint, or scope defects; data analysis for provenance, leakage, sampling, transformation, quality, or data-scope defects; model construction for structural or assumption defects; or model solving for implementation, parameter, convergence, numerical, or reproducibility defects. If the cause is not yet supportable, preserve the failure and request diagnosis rather than guessing.

## Boundaries

Never recommend or begin paper writing after a validation failure. Do not create missing evidence, retune the model without recording a new validation cycle, or convert an inconclusive result into a pass. Do not invoke another skill. This stage does not announce that the full modeling task is complete.

## Output

Return an updated handoff that preserves `task.statement`, `task.objectives`, and `task.constraints`, sets `state.current_stage` to `validation`, and sets `state.validation_status` explicitly to `pass` or `needs_revision` with a matching stage status. A current pass removes validation from `state.invalidated_stages`; a failure does not. In `result`, preserve thresholds, evidence, validated claims, limitations, failure and extrapolation domains, and relative artifact paths. Put check outcomes in `quality.checks`, adverse or inconclusive findings in `quality.warnings`, and an evidence-based validation level in `quality.confidence`. On failure, populate `next.failed_checks`, set the earliest evidence-supported rollback in `next.recommended_stage`, explain it in `next.rationale`, and put other bounded rollback options in `next.alternatives`. On pass, use the same canonical next fields to recommend completion or optional paper writing; the orchestrator decides.
