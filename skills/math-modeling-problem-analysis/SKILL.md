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

Return an updated handoff with `state.stage` set to `problem-analysis` and a justified `complete` or `needs_revision` status. In `result`, record the structured objectives, subproblems, variables, constraints, metrics, units, fact classifications, assumptions, evidence, and critical ambiguities. In `next`, state the information the next stage needs and provide only a routing recommendation for the orchestrator to decide.
