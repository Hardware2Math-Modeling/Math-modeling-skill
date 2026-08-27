---
name: math-modeling-paper-production
description: Use when requested and validated modeling paper content must be assembled with an approved template, compiled, and checked as a deliverable artifact.
---

# Mathematical Modeling Paper Production

Assemble approved paper content into a reproducible submission artifact without changing its scientific claims.

## Input

Accept the current handoff, completed paper-writing output, referenced result and figure artifacts, and the user-provided or verified template. Read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) before updating workflow state.

## Responsibilities

- Confirm that a paper was requested, paper writing is complete, validation remains current, and every referenced artifact exists before production.
- Preserve the supplied template and record the source files, compiler choice, build command, outputs, and warnings needed to reproduce the artifact.
- Check the compiled result for missing references, broken figures, layout failures, unreadable content, and applicable page or format constraints.
- Distinguish a verified submission template from a fallback layout and report readiness accordingly.

## Boundaries

Do not create unsupported claims, rewrite scientific conclusions, suppress build failures, or describe a fallback template as submission-ready. Do not proceed without both a paper request and completed paper-writing input.

## Output

Return an updated handoff with `state.current_stage` set to `paper-production` and a justified `complete` or `needs_revision` status. Record sources, build evidence, artifact paths, template status, and QA results in `result`. Put unresolved production risks in `quality.warnings`, set `quality.confidence`, explain completion or rollback in `next.rationale`, and list alternatives in `next.alternatives`.
