---
name: math-modeling-model-solving
description: Use when an accepted mathematical model specification needs analytical, numerical, optimization, simulation, or estimation results; do not use to silently redefine the model.
---

# Mathematical Model Solving

Execute the accepted specification reproducibly while exposing numerical decisions, failures, and fitness for later validation.

## Input

Accept the current handoff with an accepted model, defined interfaces, parameter sources, and planned checks. When invoked independently, first read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) and normalize the handoff before solving.

## Responsibilities

- Choose a proportionate analytical, numerical, optimization, simulation, or estimation method based on the accepted model rather than on tool preference.
- Record the algorithm, software assumptions, parameter sources, initialization, boundary treatment, tolerance, random seed, stopping criteria, and computational environment needed to reproduce the run.
- Preserve relative paths and exact commands for inputs, code, logs, tables, figures, and result artifacts. Record failed or unstable runs as well as successful ones.
- Check convergence, constraint feasibility, stability, and basic sanity against known boundaries, units, conservation relationships, or limiting cases.
- Keep scientific parameters tied to their stated evidence. Do not repurpose them as numerical tuning knobs; label solver controls separately.
- If execution exposes a structural or assumption defect, return `needs_revision` with the evidence and recommend model construction. If the problem is implementation, parameters, initialization, convergence, or reproducibility, identify that narrower solving revision.

## Boundaries

Do not silently alter equations, objectives, constraints, units, or scientific assumptions; hide failed runs; or invent computed results. Do not invoke another skill. This stage does not announce that the full modeling task is complete.

## Output

Return an updated handoff that preserves `task.statement`, `task.objectives`, and `task.constraints`, and set `state.current_stage` to `model-solving` with a justified `complete` or `needs_revision` status. In `result`, include results, units, unsuccessful attempts, commands, evidence, and relative artifact paths. Put convergence, feasibility, stability, and sanity checks in `quality.checks`, numerical or reproducibility concerns in `quality.warnings`, and the strength of the run evidence in `quality.confidence`. Set `next.recommended_stage`, explain validation readiness or precise revision needs in `next.rationale`, and list bounded solution or rollback paths in `next.alternatives`; the orchestrator decides the route.
