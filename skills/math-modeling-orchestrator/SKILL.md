---
name: math-modeling-orchestrator
description: Use when a mathematical modeling problem requires coordination across multiple specialized stages; do not use for an explicitly narrow request confined to one stage.
---

# Math Modeling Orchestrator

Coordinate the modeling task while keeping one traceable handoff as the source of truth.

## Shared control files

Before routing, read [references/workflow.json](references/workflow.json) for the allowed stages, transitions, and guards, and read [references/handoff-contract.md](references/handoff-contract.md) for the handoff schema and evidence rules.

- For a new task, construct the canonical handoff before invoking a stage: preserve the faithful prompt in `task.statement`, explicit goals in `task.objectives`, explicit limits in `task.constraints`, and set `state.current_stage` to the stage being entered.
- For a task with an existing handoff, continue from its recorded `state.current_stage`, `state.status`, evidence, failures, and `next.recommended_stage`; do not restart completed work without a rationale.
- Ask the user only for missing information that would change the objective, constraints, or model selection. Record ordinary working assumptions as provisional assumptions with provenance, surface their consequences in `quality.warnings`, and set an evidence-based `quality.confidence`.
- Treat every stage response as an updated handoff plus a recommendation. The stage does not decide cross-stage routing; this orchestrator applies the workflow and guards.

## Stage routing

Invoke exactly the stage whose entry condition is satisfied:

1. Invoke `$math-modeling-problem-analysis` first for every new problem; resume or skip only when an existing handoff records that stage complete. Use its result to make objectives, constraints, variables, metrics, and units explicit before later stages.
2. Invoke `$math-modeling-data-analysis` when relevant observational or supplied data exists and the problem definition is stable enough to assess it. Data analysis may be skipped only with a recorded reason when no relevant data work is needed.
3. Invoke `$math-modeling-model-construction` when the analyzed problem and any relevant data implications are ready to be expressed as candidate mathematical formulations.
4. Invoke `$math-modeling-model-solving` only when an accepted model, its parameters or parameter sources, domains, constraints, and solution interface are explicit.
5. Invoke `$math-modeling-validation` when solver results and reproducible evidence are available for the prespecified checks.
6. Invoke `$math-modeling-paper-writing` only after validation explicitly passes and the user requests a paper or revision of validated material. Otherwise finish after validation without entering this optional stage.

After each return, merge the updated handoff without discarding `task.statement`, `task.objectives`, `task.constraints`, equations, variable definitions, units, provenance, assumptions, accepted or rejected model alternatives, artifact paths, failed runs, `quality.warnings`, `quality.confidence`, or validation evidence. Treat `next.rationale` and `next.alternatives` as recommendations, then apply the workflow guards yourself.

## Revision control

Workflow transitions apply only after a stage returns `complete` or `skipped`. A `needs_revision` result never advances to a downstream stage.

- When the failed check belongs to the current stage and its upstream handoff is still valid, record the evidence and retry the current stage.
- When new evidence invalidates upstream work, roll back to the earliest invalidated upstream stage. Preserve the prior result as audit evidence and mark later completed work as invalidated rather than erasing it.
- After the correction is complete, rerun every invalidated downstream stage in normal workflow order, including validation. A prior validation result cannot authorize paper writing after its inputs have been invalidated.

The stage's `next` fields describe a proposed recovery, not permission to bypass these rules. Pause for genuinely model-changing user input when neither a same-stage retry nor an evidence-backed rollback is possible.

## Validation gate and rollback

Validation failure can never route to paper writing. When validation returns `needs_revision`:

- route to model construction for structural, assumption, dimensional, boundary, identifiability, or formulation failures;
- route to model solving for implementation, parameter, convergence, numerical, or reproducibility failures.

Record the failed checks, rollback decision in `next.rationale`, and any bounded fallback in `next.alternatives` before invoking the selected stage. Do not claim that the full modeling task is complete until validation passes.

## Completion

The final response must summarize the accepted model, supporting evidence, validation result and thresholds, limitations, artifact paths, and unresolved questions. If paper writing was not requested, state that it was intentionally omitted; if any evidence remains missing, report the gap rather than filling it with a plausible value.
