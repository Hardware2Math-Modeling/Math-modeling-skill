---
name: math-modeling-paper-production
description: Use when compiling, auditing, or deciding submission readiness for a Chinese mathematical-modeling paper after content freeze.
---

# Mathematical Modeling Paper Production

Produce only LaTeX/PDF deliverables. The compiled PDF and its build evidence—not source comments, caller page counts, or an uncompiled draft—are authoritative.

Accept the current handoff and completed paper-writing output. Read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) before updating workflow state. Do not change frozen scientific claims.

## Entry gate

Use the absolute Python interpreter recorded by current preflight evidence. Before copying a template, assembling content, or starting even a candidate compilation, require all of:

- the requested iteration is `current.json.active_iteration`;
- Gate 3 is exactly `confirmed`;
- current handoff `state.validation_status` is exactly `pass`, with no invalidated upstream stage or relevant stale evidence;
- frozen content is exactly `status: complete`, and every recorded evidence path and hash still matches;
- current environment evidence records an available absolute executable compiler.

Unknown is not pass. Return `needs_revision` without creating a template copy, PDF, or success manifest when an entry condition is absent.

## Template and compiler decisions

Select in this order: user template, user-selected official template, locally verified official template, built-in fallback. Never put an official template ahead of a user template. Only verified source URL, license, date, and hash evidence permits an `official_verified` claim. The fallback is always `fallback_non_submission`, even when it compiles.

Call `select_template(...)` only to select and tree-hash. Call `produce_paper(...)` to copy that selection without overwriting into the active iteration's `paper/template/`, assemble the frozen content, and compile.

Use only compilers diagnosed in the supplied environment manifest, in order `tectonic`, `latexmk`, `xelatex`. An explicit compiler must be an absolute executable matching that manifest. Do not search PATH again, install tools, invoke a shell, or switch environments. A Tectonic failure may fall through only to another already-diagnosed compiler; preserve every attempt log.

## PDF and page gates

The fallback labels `mm-body-start` and `mm-body-end`; `% BODY_START` and `% BODY_END` are assembly comments only. Derive section 1-through-8 pages from the compiled `.aux` labels and total pages from the real PDF. Missing or contradictory markers fail closed.

- Body 25–27 and total at most 30: page gate pass.
- Body outside 25–27 with total at most 30: `needs_revision`.
- Total over 30, broken/trailing PDF, empty page, unresolved reference/citation, or missing marker: fail.

Never pad with blank pages, abnormal font size/spacing, hidden text, or unrelated prose. Add only evidence-backed derivation, analysis, validation, or limitations; remove repetition and improve layout when too long.

## Completion and audit

Record template/content/environment/compiler/PDF/log/page-QA paths and hashes in `paper_manifest.json`. Exit zero without a valid PDF is failure. Preserve build output, logs, and a failure manifest after compilation starts; never overwrite an earlier iteration or present a failed candidate as final.

Set `submission_ready` only when a user or verified official template is eligible and compilation, references, page/structure checks, and visual page QA all pass. Otherwise state the exact revision or blocking evidence.

Return the updated handoff with `state.current_stage: paper-production` and a justified `complete` or `needs_revision`. Register source, build, PDF, log, and manifest artifacts with hashes; put unresolved risks in `quality.warnings`, record evidence strength in `quality.confidence`, explain completion or the earliest evidence-backed rollback in `next.rationale`, and list bounded recovery choices in `next.alternatives`.
