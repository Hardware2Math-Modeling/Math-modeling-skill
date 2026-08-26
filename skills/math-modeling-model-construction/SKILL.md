---
name: math-modeling-model-construction
description: Use when a clarified mathematical modeling problem needs a formal model specification or comparison among candidate formulations; do not use for a full numerical or analytical solution.
---

# Mathematical Model Construction

Produce a defensible model specification whose assumptions, alternatives, interfaces, and planned checks are explicit before solution begins.

## Input

Accept the current handoff containing the analyzed problem and any data-supported implications. When invoked independently, first read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) and normalize the input to it.

## Responsibilities

- Define every symbol, unit, domain, decision or state variable, parameter, objective, constraint, and relationship. Trace parameters to supplied sources or label them unresolved; never fill a missing value because it seems plausible.
- Form a small set of materially different candidate models when alternatives are useful. State assumptions and provenance for each without prematurely anchoring on an algorithm.
- Check dimensional consistency, boundary behavior, identifiability, feasibility, and compatibility with the problem and data scope.
- Compare candidates using explicit criteria such as fidelity to objectives, assumption burden, data support, interpretability, tractability, and validation potential. Preserve the accepted model and every rejected alternative with its reason.
- Specify the solution interface: required inputs, outputs, parameter sources, acceptable solution conditions, and failure signals.
- Prespecify validation tests and acceptance thresholds that can distinguish an adequate result from a failed model.

## Boundaries

Do not fabricate parameter values, perform the full solution, conceal identifiability or feasibility problems, or prefer complexity without evidence. Do not invoke another skill. This stage does not announce that the full modeling task is complete.

## Output

Return an updated handoff that preserves `task.statement`, `task.objectives`, and `task.constraints`, and set `state.current_stage` to `model-construction` with a justified `complete` or `needs_revision` status. In `result`, preserve equations, symbols, units, domains, assumptions, candidate comparison, accepted and rejected models, solution interface, and planned validation tests. Put construction checks in `quality.checks`, unresolved risks in `quality.warnings`, and the strength of support in `quality.confidence`. Set `next.recommended_stage` only when justified, explain executable inputs or revision needs in `next.rationale`, and preserve other defensible formulations or rollback paths in `next.alternatives`; the orchestrator owns routing.
