---
name: math-modeling-model-solving
description: Use when an accepted mathematical model specification needs analytical, numerical, optimization, simulation, or estimation results; do not use to silently redefine the model.
---

# Mathematical Model Solving

Execute the accepted specification reproducibly while exposing numerical decisions, failures, and fitness for later validation.

## Input

Accept the current handoff with an accepted model, defined interfaces, parameter sources, prespecified baselines and acceptance thresholds, fixed seeds, planned checks, and confirmed Gate 2 evidence for every question being solved. When invoked independently, first read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) and normalize the handoff before solving.

## Responsibilities

- Choose a proportionate analytical, numerical, optimization, simulation, or estimation method based on the accepted model rather than on tool preference.
- Record the algorithm, software assumptions, parameter sources, initialization, boundary treatment, tolerance, random seed, stopping criteria, and computational environment needed to reproduce the run.
- Preserve relative paths and exact commands for inputs, code, logs, tables, figures, and result artifacts. Record failed or unstable runs as well as successful ones.
- Check convergence, constraint feasibility, stability, and basic sanity against known boundaries, units, conservation relationships, or limiting cases.
- Keep scientific parameters tied to their stated evidence. Do not repurpose them as numerical tuning knobs; label solver controls separately.
- Emit one result contract per `Qn` plus machine-readable JSON and, for tabular results, CSV. Each contract records `question_id`, `model_id`, assumptions, the prespecified baseline, parameters, metrics, units, a run manifest with `status: success`, validation plan, explicit `validation_history`, explicit `validation_manifest`, explicit `figure_manifests`, claims, and `freeze_status: draft`. Every metric must have a finite numeric value, unit, project-relative source path, and SHA-256 source hash; use the Gate 2 seed and retain the exact structured-output paths and hashes. An explicit empty figure list represents the no-figure case; omission never does. Validation must supply `validation_manifest.status: pass` for the current `validation_cycle_id` before the contract is eligible for Gate 3.
- Prepare one structured Gate 3 handoff object per question in `result.computed_values`, with `gate_id: gate3`, `status: pending`, `question_id`, result-contract path and hash, run-manifest path, claim identifiers, figure-manifest identifiers and statuses (or an explicit empty list), validation-cycle identifier and status, and `freeze_status`. Leave Gate 3 pending until validation is current and the orchestrator obtains confirmation.
- If execution exposes a structural or assumption defect, return `needs_revision` with the evidence and recommend model construction. If the problem is implementation, parameters, initialization, convergence, or reproducibility, return `needs_revision` and identify that narrower solving revision. Any unmet or unevidenced prespecified convergence, feasibility, stability, sanity, or acceptable-solution condition requires `needs_revision`; failed exploratory runs may coexist with `complete` only when a final accepted run meets every required condition and all failures remain recorded.

## Boundaries

Do not silently alter equations, objectives, constraints, units, scientific assumptions, baselines, thresholds, or seeds; hide failed runs; or invent computed results. Do not solve without confirmed Gate 2 evidence or freeze a result/confirm Gate 3. Do not invoke another skill. This stage may mark only its own stage complete; it never marks the whole project complete.

## Output

Return an updated handoff that preserves `task.statement`, `task.objectives`, and `task.constraints`, and set `state.current_stage` to `model-solving` with a justified `complete` or `needs_revision` status. Put structured per-question Gate 3 objects only in `result.computed_values`; preserve results, units, unsuccessful attempts, commands, and evidence in the other canonical result fields. Register every JSON/CSV result, result contract, run manifest, figure manifest, validation manifest, and Gate manifest in `artifacts` with its project-relative `path`, `kind`, `description`, and SHA-256 `sha256`; keep Gate 3 pending in `result.details` and `next.rationale`. Do not add a `gate3`, `gate_evidence`, or other property to the strict-v2 `result` object. Put convergence, feasibility, stability, and sanity checks in `quality.checks`, numerical or reproducibility concerns in `quality.warnings`, and the strength of the run evidence in `quality.confidence`. Set `next.recommended_stage`, explain validation readiness or precise revision needs in `next.rationale`, and list bounded solution or rollback paths in `next.alternatives`; the orchestrator decides the route and gate status.
