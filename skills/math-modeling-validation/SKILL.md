---
name: math-modeling-validation
description: Use when a mathematical model or its results need evidence-based checks of fit, feasibility, sensitivity, uncertainty, robustness, dimensions, boundaries, or baselines; do not use to draft a paper.
---

# Mathematical Modeling Validation

Decide explicitly whether the model's supported claims pass prespecified checks, and identify the smallest evidence-backed rollback when they do not.

## Input

Accept the current handoff with confirmed Gate 2 evidence, the model specification, one draft result contract per `Qn`, structured JSON/CSV results, run and figure manifests, and prespecified tests with baseline, threshold, split/scope, fixed seed, and method. When invoked independently, first read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) and normalize the handoff before validation.

## Responsibilities

- Apply the checks appropriate to the claim and available evidence: fit, residual diagnostics, holdout performance, sensitivity, uncertainty, robustness, feasibility, dimensional consistency, boundary behavior, and comparison with a meaningful baseline.
- Use acceptance thresholds specified before seeing validation outcomes. If a threshold must change, record why, treat the prior check as failed or inconclusive, and rerun the affected validation; never move a threshold merely to pass.
- A threshold change always starts a new `validation_cycle_id`. Preserve the previous cycle's threshold, outcome, evidence paths, and hashes in validation history; never rewrite a completed cycle in place.
- Trace every check to the exact result, command, dataset scope, seed where relevant, and relative artifact path. Training fit alone cannot substitute for available holdout, boundary, sensitivity, or robustness evidence.
- State limitations, failure domains, extrapolation boundaries, data scope, and uncertainty without hiding contradictory evidence.
- Update each question's result contract with explicit validation history, a validation manifest whose `status` is exactly `pass` for the current `validation_cycle_id`, an explicit list of figure manifests whose registered entries have `status` exactly `verified`, and claim evidence. Require run status exactly `success`; reject missing baselines, non-finite metrics, hashless sources, absent audit containers, reused cycle IDs, or stale/cross-vocabulary statuses. Use an explicit empty figure list when the workflow requires no figure. Invalid evidence may not be frozen or offered for Gate 3.
- Return an explicit pass only when all required checks meet their thresholds. Otherwise return `needs_revision`, name the failed checks, and recommend the earliest evidence-supported rollback: problem analysis for objective, constraint, or scope defects; data analysis for provenance, leakage, sampling, transformation, quality, or data-scope defects; model construction for structural or assumption defects; or model solving for implementation, parameter, convergence, numerical, or reproducibility defects. If the cause is not yet supportable, preserve the failure and request diagnosis rather than guessing.

## Boundaries

Never recommend or begin paper writing after a validation failure. Do not create missing evidence, retune the model without recording a new validation cycle, convert an inconclusive result into a pass, freeze results, or confirm Gate 3. Do not invoke another skill. This stage may mark only its own stage complete; it never marks the whole project complete.

## Output

Return an updated handoff that preserves `task.statement`, `task.objectives`, and `task.constraints`, sets `state.current_stage` to `validation`, and sets `state.validation_status` explicitly to `pass` or `needs_revision` with a matching stage status. A current pass removes validation from `state.invalidated_stages`; a failure does not. Preserve thresholds, validation-cycle history, evidence, validated claims, limitations, and failure/extrapolation domains in the canonical result fields. Put one structured Gate 3 object per question only in `result.computed_values`, with `gate_id: gate3`, `status: pending`, `question_id`, result-contract path and hash, run/figure/validation manifest paths and exact statuses, claim identifiers, source iteration, and `freeze_status: draft`. Register every result contract and run, figure, validation, or Gate manifest in `artifacts` with its project-relative `path`, `kind`, `description`, and SHA-256 `sha256`; describe the pending human decision in `result.details` and `next.rationale`. Do not add a `gate3`, `gate_evidence`, or other property to the strict-v2 `result` object. Put check outcomes in `quality.checks`, adverse or inconclusive findings in `quality.warnings`, and an evidence-based validation level in `quality.confidence`. On failure, populate `next.failed_checks`, set the earliest evidence-supported rollback in `next.recommended_stage`, explain the evidence-backed cause and affected artifact hashes in `next.rationale`, and put other bounded rollback options in `next.alternatives`. On pass, recommend a pending Gate 3 decision rather than project completion or paper writing; only the orchestrator may advance after an auditable confirmation.
