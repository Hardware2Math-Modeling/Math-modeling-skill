# Modeling Handoff Contract

This contract is the structured model output exchanged between the orchestrator and every stage skill. It is not a required database or on-disk state file; a handoff may remain in the conversation. When materialized, artifact paths are relative to the user's active project.

Preserve exact equations, variable definitions, units, data provenance, assumptions, decisions, accepted and rejected alternatives, validation evidence, and artifact paths between updates. Do not replace a known value with a less specific summary.

## Canonical schema

```yaml
schema_version: "1"
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

- The required top-level fields are `schema_version`, `state`, `result`, and `next`; the canonical task, state, quality, and next keys above must retain their meanings.
- `state.status` is one of `pending`, `in_progress`, `complete`, `needs_revision`, or `skipped`.
- Use an empty array for any inapplicable collection. Never invent measurements, provenance, citations, computed values, or artifacts.
- A skipped stage records why it was unnecessary in `result.summary` and records the consequence in `next.rationale`.
- A `needs_revision` result names every failed check in `next.failed_checks` and recommends model construction for structural or assumption failures, or model solving for implementation, parameter, convergence, or reproducibility failures. Put alternatives in `next.alternatives` when more than one bounded path remains.
- Every stage result states what was completed in `result.details`, where its evidence lives in `artifacts` or `result.evidence`, and what the next stage still requires through `next.rationale` and `next.alternatives`.
- Preserve equations, variables, units, provenance, assumptions, accepted and rejected models, warnings, confidence, and validation evidence even when a stage is revised.

## Stage update expectations

| Stage | Mark complete when | Preserve as evidence | Canonical handoff update |
| --- | --- | --- | --- |
| Problem analysis | Objectives, subproblems, variables, constraints, metrics, units, facts, assumptions, and material ambiguities are explicit. | Mappings to the problem statement and unresolved information needs. | Set `state.current_stage`; put completed work in `result.details`, uncertainty in `quality.warnings`, and routing rationale in `next.rationale`. |
| Data analysis | Sources, fields, units, time and sampling scope, provenance, quality findings, transformations, uncertainty, and leakage checks are recorded, or the stage is skipped with a rationale. | Reproducible summaries, transformation rationale, and paths to data-derived artifacts. | Preserve `quality.confidence`, data evidence, and bounded alternatives in `next.alternatives`. |
| Model construction | Candidate formulations are compared by explicit criteria and one is accepted with equations, domains, assumptions, feasibility checks, solution interface, and planned validation tests. | Dimensional, boundary, identifiability, feasibility, and rejected-alternative evidence. | Record accepted and rejected models in `result`, warnings and confidence in `quality`, and the solving rationale in `next.rationale`. |
| Model solving | The accepted specification is executed reproducibly and convergence, feasibility, stability, and sanity checks are recorded. | Commands, algorithms, software assumptions, parameter sources, initialization, boundaries, tolerance, seed, stopping rules, results, and failed runs. | Keep execution evidence in `artifacts`/`result.evidence`; use `next.alternatives` for bounded revision paths. |
| Validation | Prespecified checks and thresholds support an explicit pass, or failures support `needs_revision` with the smallest evidence-backed rollback. | Fit, residual, holdout, sensitivity, uncertainty, robustness, feasibility, dimensional, boundary, and baseline evidence as applicable. | Set `state.validation_status`, `quality.confidence`, `next.failed_checks`, and a construction-or-solving `next.rationale`. |
| Paper writing | A requested deliverable uses only validation-passed evidence and is internally traceable and consistent. | Relative document and figure paths, citations, equations, units, precision choices, assumptions, limitations, and explicitly reported evidence gaps. | Set `state.current_stage`, preserve editorial warnings, and set `next.recommended_stage: complete` only when supported. |
