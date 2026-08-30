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

## Authoritative authorization evaluator

`workflow.json` transitions and `guards` are a compact routing index and explicitly set `workflow_guards_exhaustive: false`. They never authorize an action by themselves. `scripts/orchestrator_policy.py:authorization_errors(action, evidence, project_root=..., host_capability=...)` is the machine-readable authority over the parsed records for its supported actions. `project_root` is one normalized existing directory; `host_capability` is an opaque handle installed in this process by the embedding host, not an object whose verifier-shaped methods are trusted:

- model construction and solving require current preflight/initialization evidence, exact current question-version/dependency bindings, and the exact applicable confirmed gate;
- model solving additionally requires a strict accepted-model interface bound to the handoff's accepted model and exact current model-specification artifact;
- paper writing additionally requires current passing validation with no invalidated inputs;
- paper writing and production require a strict paper-request record whose exact request challenge is reverified by the host; production additionally requires the `paper-production` deliverable, complete frozen content, and a passing conflict-free template check;
- accepting the paper page gate additionally requires the exact passing page-gate evaluator record; project completion remains subject to every later production/finalization check;
- submission readiness and paper-requested project completion delegate to Task 9's project-backed finalization-authority validator, which loads canonical `paper_finalization.json` and every subordinate candidate/PDF/request/render/page/review/renderer file; an explicitly no-paper completion omits only that paper authority and still requires current model/interface/dependency/validation evidence and no invalidation;
- external-data download requires the strict external-data approval record.

The evaluator runtime-validates the handoff, current iteration, initialization, gate provenance, accepted-model interface, paper request, question-version evidence, official source record, approvals, and Task 9 authority. It reloads canonical `current.json` and `iterations/<active>/state/handoff.json`, requires exact agreement with the supplied records, and rejects every non-current pointer or handoff status. It binds the diagnosed Python path to initialization, opens and hashes every dependency/model/gate authorization artifact below `project_root`, and delegates finalization file loading to Task 9. User-event and official-source records authorize only through the registered process-local host capability and its exact required result. Any returned error blocks the action. Callers must not treat an omitted workflow JSON boolean, caller-supplied status, self-authored receipt/file, arbitrary echo/`True` verifier object, or stage recommendation as substitute authorization.

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

## Official rule and template verification

The CUMCM pack's empty `official_sources` is non-authorizing. A current-rule, current-template, compliance, submission-readiness, or project-complete claim requires a separately materialized record that runtime-validates against `references/schemas/official-verification.schema.json` and successful verification through the sealed process-local host capability. `current-rule-claim`, `submission-readiness`, and `project-complete` require `source_type: rule`; `current-template-claim` requires `source_type: template`. The registered host callback receives the exact competition/type/URL/time/content-hash fields and must return literal `true`. A local filename, `.invalid` host, free-form source, search summary, schema shape alone, missing capability, caller-created object returning `true`, or malformed field pauses the claim. The example URL and values below demonstrate shape only; they do not identify or verify a real official source.

### Official verification record

```json
{
  "schema_version": "2",
  "competition": "CUMCM",
  "source_type": "rule",
  "source_url": "https://example.invalid/shape-only/rules.pdf",
  "verified_at": "2026-08-27T00:00:00Z",
  "content_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
}
```

## Confirmation gate records

`qa/gates.json` preserves an append-only record history. For a gate to authorize a route, use the latest applicable record and runtime-validate it with `references/schemas/gate.schema.json`. A confirmed record contains the exact canonical set of every current gate-relevant artifact; `artifact_hashes` follows that scope in canonical kind/path order. Its `gate-confirmation.schema.json` receipt is returned by a host-owned verifier for an opaque event id and a challenge SHA-256 over the exact gate id and scope. A caller-authored dictionary or file is self-attestation even if its labels say “user.” The shape-only values below never assert a real confirmation.

### gate1 confirmed record

```json
{
  "schema_version": "2",
  "gate_id": "gate1",
  "status": "confirmed",
  "confirmed_by": "example-reviewer",
  "confirmed_at": "2000-01-01T00:00:00Z",
  "artifact_scope": [
    {
      "path": "artifacts/problem-analysis.json",
      "kind": "problem-analysis",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ],
  "artifact_hashes": ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
  "confirmation": {
    "schema_version": "2",
    "provenance_type": "trusted_user_event",
    "provider": "shape-only-host-boundary",
    "event_id": "shape-only-gate1-event",
    "event_type": "gate-confirmation",
    "actor_id": "example-reviewer",
    "occurred_at": "2000-01-01T00:00:00Z",
  "challenge_sha256": "e1666a241148992948f1194de6c2c89ac1219fb30e2cc76eeeb79e4dc2a2f0c9"
  },
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
  "artifact_scope": [
    {
      "path": "artifacts/model-specification.json",
      "kind": "model-specification",
      "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  ],
  "artifact_hashes": ["bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"],
  "confirmation": {
    "schema_version": "2",
    "provenance_type": "trusted_user_event",
    "provider": "shape-only-host-boundary",
    "event_id": "shape-only-gate2-event",
    "event_type": "gate-confirmation",
    "actor_id": "example-reviewer",
    "occurred_at": "2000-01-01T00:00:00Z",
  "challenge_sha256": "d40f6b93a0e4dab0f1576e63f5d97a2f4ae0d7edcb6a56735421ffc7a22c9e6e"
  },
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
  "artifact_scope": [
    {
      "path": "artifacts/q1-figure-manifest.json",
      "kind": "figure-manifest",
      "sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    },
    {
      "path": "artifacts/q1-result-contract.json",
      "kind": "result-contract",
      "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    },
    {
      "path": "artifacts/q1-run-manifest.json",
      "kind": "run-manifest",
      "sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
    },
    {
      "path": "artifacts/q1-validation-manifest.json",
      "kind": "validation-manifest",
      "sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    }
  ],
  "artifact_hashes": [
    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
  ],
  "confirmation": {
    "schema_version": "2",
    "provenance_type": "trusted_user_event",
    "provider": "shape-only-host-boundary",
    "event_id": "shape-only-gate3-event",
    "event_type": "gate-confirmation",
    "actor_id": "example-reviewer",
    "occurred_at": "2000-01-01T00:00:00Z",
    "challenge_sha256": "c09c02cca90c7931faa5d9e96c7761cc211bdbab97344e8f83cd66ddf5bd1479"
  },
  "notes": "Shape-only example for current validation, result, and figure evidence.",
  "rollback_stage": null
}
```

Oral permission, stage/model self-attestation, an arbitrary `confirmed_by`, a caller-authored confirmation file, and `current.json.gates` alone do not confirm a gate. `record_gate` accepts only the sealed process-local host capability plus an opaque confirmation event id and rejects a missing/lookalike capability, unbound event, partial/reordered hash binding, or incomplete relevant scope. The standalone CLI deliberately has no host-capability integration, so it fails closed for confirmed status. Gate 1 follows problem/assumption review; Gate 2 follows model, baseline, parameter-source, and validation-plan review; Gate 3 follows current validation, result, run, and optional figure manifests. Later unrelated paper artifacts do not alter Gate 3 scope. Pending, rejected, stale, malformed, hashless, provenance-free, or superseded records do not authorize the next stage.

## Current route prerequisite records

Model and downstream routes use strict records rather than prose claims:

- `accepted-model-interface.schema.json` records `status: accepted`, the exact accepted model id, nonempty inputs/outputs, and the current model-specification path/hash. The id must equal `handoff.result.accepted_model`, exactly one current `model-specification` artifact must match, and the regular project file's bytes must hash to the binding.
- `question-version-evidence.schema.json` contains exactly one `status: current` entry for every `current.json.question_sources` key. Each source iteration must match its pointer, and its canonical `iterations/<source>/manifests/<Qn>-dependencies.json` path/hash must match exactly one current `question-dependency-manifest` handoff artifact and the real regular project file.
- `paper-request.schema.json` records the boolean request and exact requested deliverables. Its nested trusted-user-event receipt binds that payload's canonical challenge and must be returned again through the sealed host capability. Changing a deliverable, using a self-authored receipt, or omitting the capability blocks paper work.

### Accepted-model interface record

```json
{
  "schema_version": "2",
  "status": "accepted",
  "model_id": "Linear allocation model",
  "specification": {
    "path": "artifacts/model-specification.json",
    "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  },
  "inputs": ["demand"],
  "outputs": ["allocation"]
}
```

### Question-version evidence record

```json
{
  "schema_version": "2",
  "active_iteration": "v001",
  "questions": [
    {
      "question_id": "Q1",
      "source_iteration": "v001",
      "dependency_manifest": {
        "path": "iterations/v001/manifests/Q1-dependencies.json",
        "sha256": "7777777777777777777777777777777777777777777777777777777777777777"
      },
      "status": "current"
    }
  ]
}
```

### Paper-request record

```json
{
  "schema_version": "2",
  "requested": true,
  "deliverables": ["paper-writing", "paper-production"],
  "request_event": {
    "schema_version": "2",
    "provenance_type": "trusted_user_event",
    "provider": "shape-only-host-boundary",
    "event_id": "shape-only-paper-request-event",
    "event_type": "paper-request",
    "actor_id": "example-project-owner",
    "occurred_at": "2000-01-01T00:00:00Z",
    "challenge_sha256": "3ce23f65249c9008014a49d5b7e042c004d2a097e54653c9763bb8fed7b886bd"
  }
}
```

## Submission readiness and project completion

`submission-readiness` always requires a trusted requested paper, current Gate 3, current completed modeling stages, accepted interface, real dependency files, passing validation without invalidation, official-rule verification, and the Task 9 readiness authority. The caller may supply `{path, sha256, record}` only for comparison: `paper_production.validate_paper_finalization_authority(project_root, active_iteration)` independently loads the canonical `iterations/<active>/paper/paper_finalization.json`, verifies its canonical bytes, opens and hashes every subordinate file, checks current iteration/project state, and returns the authoritative envelope. The supplied envelope and exactly one current `paper-finalization` handoff artifact must match that derived result. A single `submission_ready` boolean, PDF URL/hash, partial summary, or shape-valid record with missing files never authorizes readiness.

`project-complete` requires the same official rule boundary. Both branches require canonical current project status, current model construction/solving/validation, accepted-model interface, real per-question dependency files, passing validation, and an empty invalidated-stage list. When paper was requested, it additionally requires current Gate 3 and the same Task 9 authority. When the capability-verified request explicitly has `requested: false` and no deliverables, only the paper finalization authority is omitted.

## External-data approval

External modeling data requires a record that runtime-validates against `references/schemas/external-data-approval.schema.json` before any download. The six fields below are exact and required, `fields` is a nonempty unique requested-field list, and `user_confirmation` must be exactly `true` for that stated purpose/source/license/risk scope.

### External-data approval record

```json
{
  "purpose": "Estimate the response required by Q2.",
  "fields": ["timestamp", "response"],
  "source": "https://example.invalid/data.csv",
  "license": "License identifier verified by the user",
  "risk": "Selection bias and license-scope mismatch",
  "user_confirmation": true
}
```

Store the runtime-valid record as structured evidence in `context.data` and preserve it in later handoffs. A bare URL, inferred consent, an earlier approval for different fields, an added agent override, or missing license/risk evidence is not approval; use `needs_revision` and do not download.

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
