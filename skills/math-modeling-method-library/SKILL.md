---
name: math-modeling-method-library
description: Use when a modeling stage needs a bounded comparison of candidate method families, assumptions, applicability, limitations, or implementation references without advancing workflow state.
---

# Mathematical Modeling Method Library

Provide bounded method comparisons to a modeling stage. The calling stage remains responsible for evidence, selection, implementation, and workflow status.

## Responsibilities

- Compare only methods relevant to the stated objective, data regime, constraints, assumptions, and evaluation criteria.
- State each candidate's applicability, required inputs, identifiable parameters, expected outputs, failure modes, and validation needs.
- Separate established method properties from task-specific judgments and expose any missing evidence that would change the comparison.
- Return references or bounded recommendations to the caller without presenting a catalog entry as a selected or validated model.

## Resource boundary

Catalog/reference resources are read-only. This skill may inspect them but must not edit, replace, or extend them during a modeling task.

## State boundary

Must not write project state. This skill must not mutate a handoff, advance a workflow stage, execute project code, or create competition artifacts. It does not replace problem analysis, model construction, solving, validation, or user judgment.
