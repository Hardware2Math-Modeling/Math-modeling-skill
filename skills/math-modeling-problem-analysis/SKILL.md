---
name: math-modeling-problem-analysis
description: Use when a mathematical modeling task needs its statement clarified into objectives, variables, constraints, metrics, units, or information needs; do not use to select or solve a model.
---

# Mathematical Modeling Problem Analysis

Turn the stated problem into a precise, auditable modeling brief without committing to a formulation.

## Input

Accept the current handoff and the original problem materials. When invoked independently, first read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) and construct the missing handoff fields before analysis.

## Responsibilities

- Separate the overall objective into answerable subproblems and identify the decision, prediction, explanation, or evaluation requested by each.
- Define candidate variables, known parameters, constraints, performance metrics, scopes, time horizons, populations, and units using the problem's language. Mark symbols as provisional because model selection belongs elsewhere.
- Classify every material statement as supplied fact, derived fact, assumption, or unknown. Preserve its provenance and do not turn a provisional assumption into a fact.
- Check for conflicting objectives, incompatible units, hidden boundary conditions, ambiguous quantifiers, and missing definitions.
- Identify only information needs and user questions whose answers could change the objective, constraints, or later model choice. Record lesser ambiguities as explicit assumptions.

## Boundaries

Do not select a mathematical model, solve equations, optimize parameters, or create data. Do not invoke another skill. This stage does not announce that the full modeling task is complete.

## Output

Return an updated handoff that preserves the faithful prompt in `task.statement` and records the clarified goals and limits in `task.objectives` and `task.constraints`. Set `state.current_stage` to `problem-analysis` with a justified `complete` or `needs_revision` status. In `result`, record subproblems, variables, metrics, units, fact classifications, assumptions, evidence, and critical ambiguities. Put uncertainty and unresolved material questions in `quality.warnings`, and set `quality.confidence` from the available evidence. Set `next.recommended_stage`, explain the recommendation and required information in `next.rationale`, and list other defensible routes in `next.alternatives`; the orchestrator decides the route.
