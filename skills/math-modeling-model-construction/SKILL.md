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
- Before any execution, prespecify for every `Qn` a named accepted model, a credible baseline and baseline metric, parameter sources, acceptance thresholds, validation split and scope, fixed integer seed, validation method, and acceptable failure conditions. These choices are immutable within one validation cycle.
- Prepare one structured Gate 2 handoff object per question in `result.computed_values`, with `gate_id: gate2`, `status: pending`, `question_id`, `model_id`, `baseline`, `parameter_sources`, `validation_plan` (`validation_cycle_id`, `threshold`, `split`, `scope`, `seed`, and `method`), `acceptable_failure_conditions`, and the project-relative specification artifact path and SHA-256 hash.

## Boundaries

Do not fabricate parameter values, perform the full solution, conceal identifiability or feasibility problems, or prefer complexity without evidence. Do not execute a question before its baseline, threshold, and fixed seed are explicit. Do not confirm Gate 2: expose its handoff evidence with status `pending` for the orchestrator and user to decide. Do not invoke another skill. This stage may mark only its own stage complete; it never marks the whole project complete.

## Output

Return an updated handoff that preserves `task.statement`, `task.objectives`, and `task.constraints`, and set `state.current_stage` to `model-construction` with a justified `complete` or `needs_revision` status. Preserve equations, symbols, units, domains, assumptions, candidate comparison, accepted and rejected models, and the solution interface in the canonical result fields; put the structured per-question Gate 2 objects only in `result.computed_values`. Register every supporting specification or Gate manifest in `artifacts` with its project-relative `path`, `kind`, `description`, and SHA-256 `sha256`; describe the still-pending confirmation in `result.details` and `next.rationale`. Do not add a `gate2`, `gate_evidence`, or other property to the strict-v2 `result` object. Put construction checks in `quality.checks`, unresolved risks in `quality.warnings`, and the strength of support in `quality.confidence`. Set `next.recommended_stage` only when justified, explain executable inputs or revision needs in `next.rationale`, and preserve other defensible formulations or rollback paths in `next.alternatives`; the orchestrator owns routing and Gate 2 confirmation.
