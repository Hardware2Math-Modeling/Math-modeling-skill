---
name: math-modeling-preflight
description: Use when a mathematical modeling task must verify its inputs, project location, requested deliverables, and available Python or LaTeX environment before analysis begins.
---

# Mathematical Modeling Preflight

Establish whether the task can start reproducibly without installing software or changing the supplied evidence.

## Input

Accept the original task materials and any user-specified project, interpreter, template, or output paths. Read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) before returning workflow state.

## Responsibilities

- Inventory the supplied problem statement, attachments, data, templates, requested deliverables, and explicit constraints.
- Record absolute project and tool paths when supplied, and distinguish verified availability from user assertions or untested assumptions.
- Check whether the requested work depends on Python, packages, or a LaTeX toolchain and report missing prerequisites with concrete next actions.
- Preserve all inputs as evidence; do not modify them, install dependencies, or invent substitute data or templates.

## Boundaries

Do not analyze the modeling problem, choose methods, execute a model, create figures, or draft a paper. Environment readiness is not evidence that later modeling stages are valid.

## Output

Return an updated handoff with `state.current_stage` set to `preflight` and a justified `complete` or `needs_revision` status. Record the inventory, checked paths, environment findings, deliverable request, and blockers in `result`. Put uncertainty in `quality.warnings`, set `quality.confidence` from observed evidence, explain the next route in `next.rationale`, and list viable alternatives in `next.alternatives`.
