---
name: math-modeling-orchestrator
description: Use when a mathematical modeling problem requires coordination across multiple specialized stages; do not use for an explicitly narrow request confined to one stage.
---

# Math Modeling Orchestrator

Coordinate the task from one strict-v2 handoff and auditable project evidence. A stage recommendation never overrides an authorization prerequisite.

## Load and normalize control state

Before routing:

1. Read [workflow.json](references/workflow.json), then [handoff-contract.md](references/handoff-contract.md).
2. Load an existing handoff through the v1-to-v2 migration contract when necessary, then runtime-validate the strict-v2 result before using it. Preserve the faithful prompt, equations, artifacts, failed runs, warnings, decisions, and validation evidence.
3. Load `current.json`, its `question_sources`, current artifact manifests, `qa/gates.json`, and staleness evidence when a project exists. `current.json` is a pointer, not proof that a gate is confirmed.
4. For CUMCM, read [cumcm.json](references/competition-packs/cumcm.json). It contains defaults, not current-year rules.

The transitions and `guards` in `workflow.json` are a compact index, not an exhaustive permission check. Its `authorization_policy` names `scripts/orchestrator_policy.py:authorization_errors` as authoritative. Before any action supported by that evaluator, pass the parsed current records to it and proceed only when it returns no errors; a missing or malformed record is blocking, never an invitation to infer evidence.

For a new task, construct the canonical handoff before invoking a stage. For an existing task, continue from current evidence rather than restarting completed work without an evidence-backed reason.

## CUMCM verification boundary

The pack intentionally has `official_sources: []`. Until a user-provided official source, or an official rule or template, has undergone read-only verification and a record runtime-validates against `official-verification.schema.json`, do not claim current-rule compliance or submission-ready status. Before either claim, require `authorization_errors("current-rule-claim", evidence)` or `authorization_errors("submission-readiness", evidence)` to return no blockers with that record under `official_verification`. That record binds an absolute HTTP(S) URL, real UTC verification date and timestamp, and lowercase content SHA-256 to CUMCM and the rule/template type. A filename or free-form source string is non-authorizing. Never infer a year, submission URL, rule, or license from the competition name or an unofficial template.

External modeling data has a different boundary: require an approval that runtime-validates against `external-data-approval.schema.json` before any download. A URL, prior use, urgency, or team authority is not approval.

## Stage routing

Invoke exactly the stage whose entry condition is satisfied:

1. Invoke `$math-modeling-preflight` first for every new problem and before invoking problem analysis. New work or missing current preflight evidence always routes here; resume or skip only when an existing handoff records that stage complete and current evidence includes the user-provided absolute Python path. If that path is missing, pause: do not guess it, do not resolve PATH, and do not switch to another interpreter.
2. Invoke `$math-modeling-problem-analysis` only after current preflight. It produces the question, objective, constraint, unit, external-data-need, and model-changing-assumption evidence for Gate 1. Gate 1 after problem analysis and assumptions, and before model construction.
3. Invoke `$math-modeling-data-analysis` when supplied or approved external data is relevant. Skip only when no relevant data work exists and the recorded skip guard is satisfied. Unapproved external data pauses at `needs_revision`.
4. Invoke `$math-modeling-model-construction` after Gate 1 has an exact current confirmed record. Gate 2 after model, baseline, and validation plan, and before solving.
5. Invoke `$math-modeling-model-solving` only after Gate 2 has an exact current confirmed record and the accepted model interface is explicit.
6. Invoke `$math-modeling-visualization` whenever a result, diagnostic, or paper claim requires a figure. Skip only with the explicit no-figure guard; any figure claim requires a current verified figure manifest before validation.
7. Invoke `$math-modeling-validation` only from current solver and figure evidence. Gate 3 after current validation, results, and figures. Validation failure or inconclusive evidence remains `needs_revision`.
8. Invoke `$math-modeling-paper-writing` only for a requested paper with a current validation pass, Gate 3 confirmed before paper-writing by an exact current record, and no invalidated inputs.
9. Invoke `$math-modeling-paper-production` only for a requested paper with all paper-writing guards plus current complete paper content. Missing or incomplete content is `needs_revision`, not production completion.

After each return, merge the updated handoff without discarding `task.statement`, `task.objectives`, `task.constraints`, equations, variable definitions, units, provenance, assumptions, accepted or rejected model alternatives, artifact paths, failed runs, `quality.warnings`, `quality.confidence`, or validation evidence. Treat `next.rationale` and `next.alternatives` as recommendations, then apply the workflow guards yourself.

## Exact gates and pauses

A confirmed Gate 1, Gate 2, or Gate 3 is the latest applicable record in `qa/gates.json` that runtime-validates against `references/schemas/gate.schema.json`: exact gate id and `confirmed` status, confirmer, UTC timestamp, one or more artifact hashes, notes, rollback field, schema version, and explicit user confirmation provenance validated against `gate-confirmation.schema.json`. The nested provenance must say `actor_type: user` and `confirmation_method: explicit` and bind the exact same artifact hashes; agent/stage output, an arbitrary confirmer string, Oral approval, or a `current.json` gate status never satisfies a gate.

| Evidence state | Required action |
| --- | --- |
| Missing user-provided absolute Python path | `pause` in preflight; do not guess, resolve PATH, or switch interpreters. |
| Model-changing ambiguity | `pause` at problem analysis or the earliest affected stage for user confirmation. |
| Missing/false external-data approval | `needs_revision`; no download. |
| Missing, rejected, or stale gate record | `needs_revision`; stay or roll back to that gate's owning stage. |
| Template conflict | `pause` paper production at `needs_revision`; do not silently choose a conflicting template. |
| Page-gate failure | `pause` paper production at `needs_revision`; never mark the project complete. |

Unknown, failure, `needs_revision`, rejected, pending, or stale evidence cannot authorize a forward route or `complete`.

## Iterations and revision control

Workflow transitions apply after a stage returns `complete`, or after an optional stage returns `skipped` with its guard and rationale satisfied. A required stage cannot be skipped. A `needs_revision` result never advances to a downstream stage.

- When the failed check belongs to the current stage and upstream evidence remains valid, record it and retry the current stage.
- Any input, code, parameter, or method change affecting a `Qn` first creates a `scripts/project_state.py new-iteration`. Update only affected `question_sources`; preserve unaffected question sources and their earlier `vNNN` evidence.
- Call the `project_state.mark_stale` contract (CLI `scripts/project_state.py stale`) for affected run, figure, validation, and paper artifacts before rerouting. Preserve prior output as audit evidence, move affected stages from `state.completed_stages` to `state.invalidated_stages`, and set an affected prior validation pass to `stale`.
- Roll back to the earliest invalidated upstream stage. Do not erase evidence or widen invalidation to unrelated questions.
- After the correction is complete, rerun every invalidated downstream stage in normal workflow order, including validation. A prior validation result cannot authorize paper writing after its inputs have been invalidated.

The stage's `next` fields describe a proposed recovery, not permission to bypass these rules. Pause for genuinely model-changing user input when neither a same-stage retry nor an evidence-backed rollback is possible.

## Validation gate and rollback

Validation failure can never route to paper writing. When validation returns `needs_revision`:

- route to problem analysis for misunderstood objectives, constraints, scope, or problem-statement failures;
- route to data analysis for provenance, leakage, sampling, transformation, data-quality, or data-scope failures;
- route to model construction for structural, assumption, dimensional, boundary, identifiability, or formulation failures;
- route to model solving for implementation, parameter, convergence, numerical, or reproducibility failures.

Choose the earliest stage invalidated by the evidence; if the cause is not yet supportable, keep validation at `needs_revision` and pause rather than guessing. Record the failed checks, rollback decision in `next.rationale`, and any bounded fallback in `next.alternatives` before invoking the selected stage. Do not claim that the full modeling task is complete until validation passes.

## Completion

The final response must summarize the accepted model, supporting evidence, validation result and thresholds, limitations, artifact paths, and unresolved questions. Paper production can be complete only with current complete paper content and its production checks; a template conflict, page-gate failure, missing content, or any invalidated input remains `needs_revision`. If paper writing was not requested, state that it was intentionally omitted; if evidence remains missing, report the gap rather than filling it with a plausible value.
