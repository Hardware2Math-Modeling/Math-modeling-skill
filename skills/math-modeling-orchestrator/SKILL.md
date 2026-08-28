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
3. Load `current.json`, its `question_sources`, current artifact manifests, `qa/gates.json`, the accepted-model interface, paper-request event, question-version evidence, and staleness evidence when a project exists. `current.json` is a pointer, not proof that a gate is confirmed. Every current `question_sources` entry needs one `question-version-evidence.schema.json` record bound to its canonical current `question-dependency-manifest` path and hash.
4. For CUMCM, read [cumcm.json](references/competition-packs/cumcm.json). It contains defaults, not current-year rules.

The transitions and `guards` in `workflow.json` are a compact index, not an exhaustive permission check. Its `authorization_policy` names `scripts/orchestrator_policy.py:authorization_errors` as authoritative. Before any action supported by that evaluator, pass the normalized existing `project_root`, parsed current records, and the host's opaque process-local capability; proceed only when it returns no errors. The evaluator reloads canonical `current.json` and the active handoff, then opens and hashes every gate, model-interface, question-dependency, and finalization file it consumes. A missing or malformed record/file is blocking, never an invitation to infer evidence. The capability keeps trusted-user-event and official-source verification outside caller objects. A caller-created dictionary, file, boolean, echo/`True` verifier, or lookalike capability is non-authorizing.

For a new task, construct the canonical handoff before invoking a stage. For an existing task, continue from current evidence rather than restarting completed work without an evidence-backed reason.

## CUMCM verification boundary

The pack intentionally has `official_sources: []`. Until an official rule or template has undergone read-only verification and a record runtime-validates against `official-verification.schema.json`, do not claim current-rule, current-template, submission-ready, or project-complete status. `current-rule-claim`, `submission-readiness`, and `project-complete` require `source_type: rule`; `current-template-claim` requires `source_type: template`. Through the sealed host capability, the policy must verify the exact CUMCM/type/URL/UTC verification date/content SHA-256 fields and receive literal `true`; schema shape, a `.invalid` host, a filename, a free-form source, or a caller object returning `true` is non-authorizing. Never infer a year, submission URL, rule, or license from the competition name or an unofficial template.

External modeling data has a different boundary: require an approval that runtime-validates against `external-data-approval.schema.json` before any download. A URL, prior use, urgency, or team authority is not approval.

## Stage routing

Invoke exactly the stage whose entry condition is satisfied:

1. Invoke `$math-modeling-preflight` first for every new problem and before invoking problem analysis. New work or missing current preflight evidence always routes here; resume or skip only when an existing handoff records that stage complete and current evidence includes the user-provided absolute Python path. If that path is missing, pause: do not guess it, do not resolve PATH, and do not switch to another interpreter.
2. Invoke `$math-modeling-problem-analysis` only after current preflight. It produces the question, objective, constraint, unit, external-data-need, and model-changing-assumption evidence for Gate 1. Gate 1 after problem analysis and assumptions, and before model construction.
3. Invoke `$math-modeling-data-analysis` when supplied or approved external data is relevant. Skip only when no relevant data work exists and the recorded skip guard is satisfied. Unapproved external data pauses at `needs_revision`.
4. Invoke `$math-modeling-model-construction` after Gate 1 has an exact current confirmed record and strict question-version evidence covers every current question source. Gate 2 after model, baseline, and validation plan, and before solving.
5. Invoke `$math-modeling-model-solving` only after Gate 2 has an exact current confirmed record, the iteration and model construction remain current, and `accepted-model-interface.schema.json` binds the accepted model id and exact current model-specification artifact.
6. Invoke `$math-modeling-visualization` whenever a result, diagnostic, or paper claim requires a figure. Skip only with the explicit no-figure guard; any figure claim requires a current verified figure manifest before validation.
7. Invoke `$math-modeling-validation` only from current solver and figure evidence. Gate 3 after current validation, results, and figures. Validation failure or inconclusive evidence remains `needs_revision`.
8. Invoke `$math-modeling-paper-writing` only when `paper-request.schema.json` records the deliverable and its exact request payload is reverified through the host user-event boundary, with a current validation pass, Gate 3 confirmed before paper-writing by an exact current record, and no invalidated inputs.
9. Invoke `$math-modeling-paper-production` only when that trusted request includes `paper-production`, all paper-writing guards hold, and current complete paper content is available. Missing or incomplete content is `needs_revision`, not production completion.

After each return, merge the updated handoff without discarding `task.statement`, `task.objectives`, `task.constraints`, equations, variable definitions, units, provenance, assumptions, accepted or rejected model alternatives, artifact paths, failed runs, `quality.warnings`, `quality.confidence`, or validation evidence. Treat `next.rationale` and `next.alternatives` as recommendations, then apply the workflow guards yourself.

## Exact gates and pauses

A confirmed Gate 1, Gate 2, or Gate 3 is the latest applicable record in `qa/gates.json` that runtime-validates against `references/schemas/gate.schema.json`. Its canonical `artifact_scope` is the exact complete set of current artifacts relevant to that gate, and `artifact_hashes` exactly follows that scope. Every scoped path must be a regular non-symlink file below the normalized project root whose bytes match its SHA-256. Its `confirmation` is a `gate-confirmation.schema.json` trusted-user-event receipt whose challenge hash binds the gate id and canonical scope. Both recording and authorization must use the sealed process-local host capability to resolve the opaque event id and exact challenge; agent/stage output, a caller-authored receipt/file, arbitrary confirmer or verifier-shaped object, Oral approval, or `current.json.gates` never satisfies a gate. Gate 3 ignores unrelated paper artifacts created after its confirmation.

| Evidence state | Required action |
| --- | --- |
| Missing user-provided absolute Python path | `pause` in preflight; do not guess, resolve PATH, or switch interpreters. |
| Model-changing ambiguity | `pause` at problem analysis or the earliest affected stage for user confirmation. |
| Missing/false external-data approval | `needs_revision`; no download. |
| Missing, rejected, or stale gate record | `needs_revision`; stay or roll back to that gate's owning stage. |
| template conflict | `pause` paper production at `needs_revision`; do not silently choose a conflicting template. |
| page-gate failure | `pause` paper production at `needs_revision`; never mark the project complete. |

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

The final response must summarize the accepted model, supporting evidence, validation result and thresholds, limitations, artifact paths, and unresolved questions. Before submission readiness or project completion, require `authorization_errors(..., project_root=..., host_capability=...)` to return no blockers. Both branches require a canonical current pointer and active handoff, completed current model construction/solving/validation, the accepted interface and its real specification file, real per-question dependency files, a validation pass, and no invalidation. If paper was requested, completion and submission readiness additionally require current Gate 3 and consume Task 9's project-backed `validate_paper_finalization_authority` result: the canonical active-iteration finalization plus every hash-verified subordinate file—not one caller-supplied URL, hash, record, or readiness boolean. If the trusted request explicitly says no paper, state that paper was intentionally omitted. Missing evidence is reported, never plausibly filled.
