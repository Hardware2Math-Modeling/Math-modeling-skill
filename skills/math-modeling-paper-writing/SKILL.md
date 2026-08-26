---
name: math-modeling-paper-writing
description: Use when validated mathematical modeling results need a paper or when already validated modeling material needs editorial revision; do not use when validation has not passed.
---

# Mathematical Modeling Paper Writing

Turn validation-passed modeling evidence into the requested deliverable without improving apparent completeness by inventing support.

## Input gate

Accept the current handoff and requested deliverable. When invoked independently, first read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) and normalize the handoff. Proceed only if the handoff records an explicit validation pass, unless the request is limited to editing already validated material. If the gate is not satisfied, return `needs_revision` and identify the missing validation evidence.

## Responsibilities

- Confirm the deliverable type, language, length, format, audience, and required sections before drafting when those constraints are not already supplied.
- Build a traceable narrative from the problem, assumptions, model choice, solution, evidence, and validation. Keep claims within validated scope.
- Keep notation, equations, variable definitions, units, numerical precision, table and figure references, citations, and artifact paths mutually consistent.
- Include assumptions, limitations, uncertainty, failure domains, extrapolation boundaries, and rejected alternatives when they matter to interpretation.
- Report a missing citation, figure, calculation, or validation item directly. Preserve evidence gaps as gaps rather than inserting a plausible placeholder or unsupported number.

## Boundaries

Do not fabricate citations, data, equations, figures, computed values, artifacts, or validation results. Do not disguise an unvalidated draft as final. Do not invoke another skill. This stage does not independently announce completion of the full modeling task.

## Output

Return an updated handoff with `state.stage` set to `paper-writing`. Record the deliverable and all relative document, table, and figure paths in `artifacts`; record traceability and consistency checks in `quality` and `result`. When the requested, evidence-supported deliverable is ready, set the stage status to `complete` and `next.recommended_stage` to `complete`, while listing any remaining editorial or evidence gaps for the orchestrator's final summary.
