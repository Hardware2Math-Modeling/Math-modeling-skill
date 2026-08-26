# Modeling Handoff Contract

The handoff is the structured model output exchanged between the orchestrator and a stage skill. It is a logical contract, not a database schema: it may remain in the conversation and does not have to be written to disk. When a handoff is materialized, keep its artifact path relative to the user's active project.

Preserve equations, variable definitions, units, provenance, assumptions, accepted and rejected alternatives, validation evidence, and relative artifact paths across updates. Never replace a known value with a less specific summary.

## Required fields and statuses

Every handoff must contain `schema_version`, `state`, `result`, and `next`. Other top-level sections carry shared context and traceability. `state.status` must be one of:

- `pending`
- `in_progress`
- `complete`
- `needs_revision`
- `skipped`

Use an empty array when an array-valued field does not apply. Do not invent measurements, provenance, citations, computed values, or artifacts to make a handoff look complete. A `skipped` stage must state why it was unnecessary. A `needs_revision` result must identify each failed check and recommend rollback to model construction for structural or assumption failures, or model solving for implementation, parameter, or convergence failures.

## Complete YAML example

```yaml
schema_version: "1"
task:
  title: "Illustrative constrained allocation problem"
  source: "User-provided problem statement"
state:
  stage: "model-construction"
  status: "complete"
  validation_status: "pending"
  completed_stages:
    - "problem-analysis"
    - "model-construction"
  skipped_stages:
    - stage: "data-analysis"
      reason: "The task supplies no observational data and requires a symbolic formulation."
context:
  objectives:
    - "Minimize total stated cost subject to the stated service requirement."
  constraints:
    - "Use only constraints present in the problem statement or explicitly labeled assumptions."
  assumptions:
    - statement: "Decision variables are continuous in the first candidate formulation."
      status: "provisional"
      provenance: "Analyst assumption pending user confirmation"
  equations:
    - id: "objective-1"
      expression: "minimize sum_i(c_i * x_i)"
  variables:
    - symbol: "x_i"
      meaning: "Allocation to option i"
      unit: "allocation unit"
      domain: "x_i >= 0"
  parameters:
    - symbol: "c_i"
      meaning: "Stated cost per allocation unit"
      unit: "currency / allocation unit"
      provenance: "Problem statement"
artifacts: []
quality:
  checks:
    - name: "dimensional consistency"
      status: "complete"
      evidence: "Each objective term has units of currency."
  limitations:
    - "Integrality has not yet been established from the problem statement."
result:
  summary: "A continuous constrained optimization formulation is ready for solution."
  accepted_model: "Linear allocation formulation"
  rejected_alternatives:
    - model: "Unconstrained allocation"
      reason: "It cannot represent the stated service requirement."
  evidence:
    - "Objective, domains, and constraints map to the analyzed requirements."
  computed_values: []
  citations: []
next:
  recommended_stage: "model-solving"
  reason: "The selected formulation and solution interface are explicit."
  needs:
    - "Confirm whether allocations must be integral before final computation."
  failed_checks: []
```

## Stage update expectations

| Stage | Mark complete when | Preserve as evidence | State what the next stage needs |
| --- | --- | --- | --- |
| Problem analysis | Objectives, subproblems, variables, constraints, metrics, units, facts, assumptions, and material ambiguities are explicit. | Mappings to the problem statement and unresolved information needs. | A bounded formulation target and any user decisions that affect model choice. |
| Data analysis | Sources, fields, units, time and sampling scope, provenance, quality findings, transformations, uncertainty, and leakage checks are recorded, or the stage is skipped with a reason. | Reproducible summaries, transformation rationale, and paths to data-derived artifacts. | Supported modeling implications without causal overclaiming. |
| Model construction | Candidate formulations are compared by explicit criteria and one is accepted with equations, domains, assumptions, feasibility checks, solution interface, and planned validation tests. | Dimensional, boundary, identifiability, feasibility, and rejected-alternative evidence. | A complete specification plus parameter sources and unresolved assumptions. |
| Model solving | The accepted specification is executed reproducibly and convergence, feasibility, stability, and sanity checks are recorded. | Commands, algorithms, software assumptions, parameter sources, initialization, boundaries, tolerance, seed, stopping rules, results, and failed runs. | Results and artifacts ready for independent validation, or precise revision targets. |
| Validation | Prespecified checks and thresholds support an explicit pass, or failures support `needs_revision` with the smallest rollback. | Fit, residual, holdout, sensitivity, uncertainty, robustness, feasibility, dimensional, boundary, and baseline evidence as applicable. | On pass, limitations and validated claims; on failure, failed checks and a construction-or-solving rollback. |
| Paper writing | A requested deliverable uses only validation-passed evidence and is internally traceable and consistent. | Relative document and figure paths, citations, equations, units, precision choices, assumptions, limitations, and explicitly reported evidence gaps. | `complete`, with remaining editorial or evidence gaps listed rather than filled in. |
