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
- the current handoff registers the exact project-relative environment-manifest path and SHA-256;
- every available compiler has an absolute executable path and diagnosed SHA-256 that still matches that executable.

Unknown is not pass. Return `needs_revision` without creating a template copy, PDF, or success manifest when an entry condition is absent.

## Template and compiler decisions

Select in this order: user template, user-selected official template, locally verified official template, built-in fallback. Never put an official template ahead of a user template. Only verified status plus nonempty source URL, license, date, and SHA-256 evidence permits an `official_verified` claim. The fallback is always `fallback_non_submission`, even when supplied through the user slot or copied to another path.

Call `select_template(...)` only to select and tree-hash. Call `produce_paper(...)` to copy that selection without overwriting into the active iteration's `paper/template/`, assemble the frozen content, and compile.

Require a custom main entry to consume `paper-frontmatter.tex`, `paper-body.tex`, and `paper-appendices.tex` exactly once and in that order, ignoring commented-out inputs. Generated body content owns `mm-body-start` immediately before section 1 and `mm-body-end` after section 8. Preserve any authorized English abstract and English keywords in generated frontmatter. Reject integration conflicts before invoking a compiler.

Use only compilers diagnosed in the supplied environment manifest. A `tectonic` template permits diagnosed Tectonic only; an `xelatex` template permits diagnosed `latexmk -xelatex` and direct XeLaTeX, in that order. An explicit compiler must be an absolute executable matching both the manifest and template engine. Do not search PATH again, install tools, invoke a shell, or switch environments.

Treat `latexmk` as its own multi-pass driver. Run direct XeLaTeX at least twice and at most three times, stopping only when the auxiliary-file hash stabilizes; retain the command and process/build logs for every pass. Non-convergence is an audited failure. Tectonic may run once unless diagnosed evidence requires otherwise.

## PDF and page gates

The generated body labels `mm-body-start` and `mm-body-end`; source comments are never compiled-page evidence. Derive section 1-through-8 pages from the final compiled `.aux` labels and total pages from the real PDF. Missing or contradictory markers, invalid classic/xref-stream entries, or a non-converged build fail closed.

- Body 25–27 and total at most 30: page gate pass.
- Body outside 25–27 with total at most 30: `needs_revision`.
- Total over 30, broken/trailing PDF, empty page, unresolved reference/citation, or missing marker: fail.

Never pad with blank pages, abnormal font size/spacing, hidden text, or unrelated prose. Add only evidence-backed derivation, analysis, validation, or limitations; remove repetition and improve layout when too long.

Automatic structure/content-stream checks never authorize visual pass. Without a project-contained regular `visual_review_path`, set visual status to `needs_review`. A verified review must be strict JSON with exactly `status`, `pdf_sha256`, `page_coverage`, `render_evidence`, and `reviewer`; bind it to the exact compiled PDF hash, cover every page, name a nonempty reviewer, and hash every regular rendered artifact. Invalid or stale review evidence fails.

## Completion and audit

Record template/content/environment/compiler/PDF/log/page-QA paths and hashes in `paper_manifest.json`. Exit zero without a valid PDF is failure. Publish directories and files with create-new/no-follow semantics, re-hash the selected/assembled template tree after compilation, and preserve build output, per-pass logs, and a failure manifest after compilation starts. Never overwrite an earlier iteration or present a failed candidate as final.

Set `submission_ready` only when a user or verified official template is eligible and compilation, references, page/structure checks, and visual page QA all pass. Otherwise state the exact revision or blocking evidence.

Return the updated handoff with `state.current_stage: paper-production` and a justified `complete` or `needs_revision`. Register source, build, PDF, log, and manifest artifacts with hashes; put unresolved risks in `quality.warnings`, record evidence strength in `quality.confidence`, explain completion or the earliest evidence-backed rollback in `next.rationale`, and list bounded recovery choices in `next.alternatives`.
