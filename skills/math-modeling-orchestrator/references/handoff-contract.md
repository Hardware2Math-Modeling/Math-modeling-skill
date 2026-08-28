# Modeling Handoff Contract

This contract is the strict-v2 structured output exchanged between the orchestrator and every stage skill. It is not a required database or on-disk state file; a handoff may remain in the conversation. When materialized, artifact paths are relative to the user's active project.

Preserve exact equations, variable definitions, units, data provenance, assumptions, decisions, accepted and rejected alternatives, validation evidence, and artifact paths between updates. Do not replace a known value with a less specific summary.

## Load, migrate, validate

Runtime routing accepts only a handoff that validates as schema version `"2"`. If a chat or file handoff declares schema version `"1"`, pass it through the existing migration logic in `scripts/handoff_schema.py` / `scripts/migrate_handoff.py`; do not manually reshape it. For a file, create a new output with `scripts/migrate_handoff.py --input OLD.json --output NEW.json --pretty`, then run `scripts/validate_handoff.py --input NEW.json --mode runtime`.

Migration preserves recognized task text, objectives, constraints, equations, artifacts, result evidence (including failed runs), decisions, warnings, and other canonical evidence. If migration or runtime validation rejects an unrecognized or malformed value, pause instead of dropping it. Never use legacy validation mode as permission to route a v1 object downstream.

## Canonical schema

```yaml
schema_version: "2"
task:
  statement: "Original problem or a faithful summary"
  objectives:
    - "Minimize stated cost while meeting the service requirement."
  constraints:
    - "Use only supplied constraints or assumptions explicitly marked below."
state:
  current_stage: "model-construction"
  status: "complete"
  validation_status: "pending"
  completed_stages:
    - "problem-analysis"
    - "model-construction"
  invalidated_stages: []
context:
  assumptions:
    - statement: "Decision variables are continuous in the first candidate formulation."
      status: "provisional"
      provenance: "Analyst assumption pending user confirmation"
  variables:
    - symbol: "x_i"
      meaning: "Allocation to option i"
      unit: "allocation unit"
      domain: "x_i >= 0"
  data: []
  methods: []
  decisions:
    - statement: "A linear formulation is retained for its transparent constraints."
      provenance: "Model comparison recorded in result.details"
  equations:
    - id: "objective-1"
      expression: "minimize sum_i(c_i * x_i)"
  parameters:
    - symbol: "c_i"
      meaning: "Stated cost per allocation unit"
      unit: "currency / allocation unit"
      provenance: "Problem statement"
artifacts:
  - path: "artifacts/model-specification.md"
    kind: "report"
    description: "Accepted equations, domains, and planned checks"
quality:
  checks:
    - name: "dimensional consistency"
      status: "complete"
      evidence: "Each objective term has units of currency."
  warnings:
    - "Integrality has not yet been established from the problem statement."
  confidence: "medium"
  limitations:
    - "The formulation remains provisional until the integrality question is resolved."
result:
  summary: "A continuous constrained optimization formulation is ready for solution."
  details:
    - "Objectives, domains, constraints, and units map to the analyzed requirements."
  accepted_model: "Linear allocation formulation"
  rejected_alternatives:
    - model: "Unconstrained allocation"
      rationale: "It cannot represent the stated service requirement."
  evidence:
    - "Dimensional check recorded in quality.checks."
  computed_values: []
  citations: []
next:
  recommended_stage: "model-solving"
  rationale: "The selected formulation and solution interface are explicit."
  alternatives:
    - "Resolve integrality before solving if the user confirms discrete allocations."
  failed_checks: []
```

## Required semantics

- The required top-level fields are exactly `schema_version`, `task`, `state`, `context`, `artifacts`, `quality`, `result`, and `next`; validate them with `references/schemas/handoff.schema.json` or the runtime validator.
- `state.status` is one of `pending`, `in_progress`, `complete`, `needs_revision`, or `skipped`.
- `state.validation_status` is `pending` before current validation, `pass` only for a current passing result, `needs_revision` for a current failed or inconclusive validation, and `stale` when previously completed validation has invalidated inputs.
- `state.completed_stages` contains only stages whose latest terminal outcome remains current: `complete`, or a guard-satisfied `skipped` outcome for an optional stage. This preserves a deliberate skip across resume. `state.invalidated_stages` lists stages whose preserved outputs are audit-only and must be rerun before they can be treated as current again.
- Use an empty array for any inapplicable collection. Never invent measurements, provenance, citations, computed values, or artifacts.
- Only an optional stage may use `skipped`, and only when its workflow guard is satisfied. It records why it was unnecessary in `result.summary` and records the consequence in `next.rationale`.
- `next.recommended_stage` is a recommendation, not permission. A `needs_revision` result never authorizes a forward transition. It names every failed check in `next.failed_checks`; `next.recommended_stage` proposes a same-stage retry or the earliest invalidated upstream stage, while `next.rationale` explains the evidence and `next.alternatives` records other bounded recovery paths.
- Any unknown, failure, pending, rejected, stale, or `needs_revision` prerequisite cannot authorize a forward transition or `complete`. Record the gap and pause or roll back.
- Preserve earlier results as audit evidence during revision. Move affected stages out of `state.completed_stages` and into `state.invalidated_stages`, record why in `context.decisions` and `quality.warnings`, and set `state.validation_status` to `stale` whenever a prior validation pass depends on invalidated inputs. Rerun every invalidated downstream stage before treating validation as current; remove a stage from `state.invalidated_stages` only after its replacement output is complete.
- Every stage result states what was completed in `result.details`, where its evidence lives in `artifacts` or `result.evidence`, and what the next stage still requires through `next.rationale` and `next.alternatives`.
- Preserve equations, variables, units, provenance, assumptions, accepted and rejected models, warnings, confidence, and validation evidence even when a stage is revised.

## Project iterations and staleness

`current.json` is a strict-v2 iteration pointer, not the handoff and not gate evidence. `question_sources` may deliberately mix `vNNN` versions:

```json
{
  "schema_version": "2",
  "project_id": "example-project",
  "active_iteration": "v002",
  "question_sources": {"Q1": "v001", "Q2": "v002"},
  "gates": {"gate1": "stale", "gate2": "stale", "gate3": "stale"},
  "status": "stale",
  "updated_at": "2000-01-01T00:00:00Z"
}
```

An input, code, parameter, or method change affecting a question creates a new immutable iteration before further work. Update only that question's source version. Mark its dependent run, figure, validation, and paper evidence stale before rerouting; preserve unaffected `question_sources` and all older evidence. A pointer status never substitutes for current artifact hashes or a gate record.

## Confirmation gate records

`qa/gates.json` preserves an append-only record history. For a gate to authorize a route, use the latest applicable record and runtime-validate it with `references/schemas/gate.schema.json`. A confirmed record has exactly the shape below: schema version, gate id/status, confirmer, real UTC confirmation time, at least one current artifact SHA-256, notes, and rollback field. The values below demonstrate shape only and never assert a real confirmation.

### gate1 confirmed record

```json
{
  "schema_version": "2",
  "gate_id": "gate1",
  "status": "confirmed",
  "confirmed_by": "example-reviewer",
  "confirmed_at": "2000-01-01T00:00:00Z",
  "artifact_hashes": ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
  "notes": "Shape-only example for problem and assumption evidence.",
  "rollback_stage": null
}
```

### gate2 confirmed record

```json
{
  "schema_version": "2",
  "gate_id": "gate2",
  "status": "confirmed",
  "confirmed_by": "example-reviewer",
  "confirmed_at": "2000-01-01T00:00:00Z",
  "artifact_hashes": ["bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"],
  "notes": "Shape-only example for model, baseline, and validation-plan evidence.",
  "rollback_stage": null
}
```

### gate3 confirmed record

```json
{
  "schema_version": "2",
  "gate_id": "gate3",
  "status": "confirmed",
  "confirmed_by": "example-reviewer",
  "confirmed_at": "2000-01-01T00:00:00Z",
  "artifact_hashes": ["cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"],
  "notes": "Shape-only example for current validation, result, and figure evidence.",
  "rollback_stage": null
}
```

Oral permission and `current.json.gates` alone do not confirm a gate. Gate 1 follows problem/assumption review; Gate 2 follows model, baseline, parameter-source, and validation-plan review; Gate 3 follows current validation, result, and figure review. Pending, rejected, stale, malformed, hashless, or superseded records do not authorize the next stage.

## External-data approval

External modeling data requires a structured record before any download. All fields are required, `fields` is the exact requested field list, and `user_confirmation` must be exactly `true` for that stated purpose/source/license/risk scope.

### External-data approval record

```json
{
  "purpose": "Estimate the response required by Q2.",
  "fields": ["timestamp", "response"],
  "source": "User-identified external dataset",
  "license": "License identifier verified by the user",
  "risk": "Selection bias and license-scope mismatch",
  "user_confirmation": true
}
```

Store the record as structured evidence in `context.data` and preserve it in later handoffs. A bare URL, inferred consent, an earlier approval for different fields, or missing license/risk evidence is not approval; use `needs_revision` and do not download.

## Stage update expectations

| Stage | Mark complete when | Preserve as evidence | Canonical handoff update |
| --- | --- | --- | --- |
| Problem analysis | Objectives, subproblems, variables, constraints, metrics, units, facts, assumptions, external-data needs, and material ambiguities are explicit; Gate 1 remains pending for the orchestrator. | Mappings to the problem statement and unresolved information needs. | Set `state.current_stage`; put completed work in `result.details`, uncertainty in `quality.warnings`, and routing rationale in `next.rationale`. |
| Data analysis | Sources, fields, units, time and sampling scope, provenance, approvals, quality findings, transformations, uncertainty, and leakage checks are recorded, or the stage is skipped with a rationale. | Reproducible summaries, approval records, transformation rationale, and paths to data-derived artifacts. | Preserve `quality.confidence`, data evidence, and bounded alternatives in `next.alternatives`. |
| Model construction | Candidate formulations are compared by explicit criteria and one is accepted with equations, domains, assumptions, feasibility checks, baseline, parameter sources, solution interface, and planned validation tests; Gate 2 remains pending for the orchestrator. | Dimensional, boundary, identifiability, feasibility, baseline, and rejected-alternative evidence. | Record accepted and rejected models in `result`, warnings and confidence in `quality`, and the solving rationale in `next.rationale`. |
| Model solving | The accepted specification is executed reproducibly and convergence, feasibility, stability, and sanity checks are recorded. | Commands, algorithms, software assumptions, parameter sources, initialization, boundaries, tolerance, seed, stopping rules, results, and failed runs. | Keep execution evidence in `artifacts`/`result.evidence`; use `next.alternatives` for bounded revision paths. |
| Validation | Prespecified checks and thresholds support an explicit current pass, or failures support `needs_revision` with the earliest evidence-backed rollback; Gate 3 remains pending for the orchestrator. | Fit, residual, holdout, sensitivity, uncertainty, robustness, feasibility, dimensional, boundary, data-scope, baseline, current result, and figure evidence as applicable. | Set `state.validation_status`, clear validation from `state.invalidated_stages` only after a current pass, preserve `quality.confidence`, populate `next.failed_checks`, and explain the earliest affected stage in `next.rationale`. |
| Paper writing | A requested deliverable uses only a current validation pass, current Gate 3 confirmation, and no invalidated input, and produces complete current paper content. | Relative document and figure paths, citations, equations, units, precision choices, assumptions, limitations, and explicitly reported evidence gaps. | Set `state.current_stage`, preserve editorial warnings, and set `next.recommended_stage: paper-production` only when content is complete and supported. |
| Paper production | Current complete paper content compiles and all template, structure, reference, page, render, and human-review gates pass. | Template/content/environment/compiler/PDF/page/render/review paths and hashes. | Template conflict, missing content, or page-gate failure remains `needs_revision`; only current complete evidence can support completion. |
