---
name: math-modeling-visualization
description: Use when validated or diagnostic modeling results need evidence-backed figures, or when a claimed figure must be registered and checked before validation.
---

# Mathematical Modeling Visualization

Turn registered model outputs into publication-ready figures without weakening evidence traceability.

## Input

Accept the current handoff, intended claim, result paths, and paper width. Read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) before updating workflow state.

## Required workflow

1. Choose the claim-facing chart with [chart-selection.md](references/chart-selection.md), then assign the closed role and C-A/C-B treatment with [figure-roles.md](references/figure-roles.md).
2. Register the manifest before drawing. Use safe relative paths and SHA-256 for every source; record `claim_id`, role, outputs, axes with units, legend decision, caption, paper reference and width, accessibility/render outcomes, and `status: draft`.
3. Draw only registered result values. Apply [modeling.mplstyle](assets/styles/modeling.mplstyle) and [visual-style.md](references/visual-style.md). Do not synthesize a missing observation or use unregistered random example data.
4. Export PDF plus PNG or SVG through `scripts/export_figure.py`. If any registered source hash changed, stop and mark the figure `stale`; never refresh the expected hash as an implicit acceptance.
5. Follow [render-qa.md](references/render-qa.md). Run deterministic manifest/format checks, render at `paper_width_mm`, and inspect the actual output for clipping, overlap, glyph failures, legibility, grayscale, and color-blind readability. Missing `pdftoppm` means `needs_review`, not pass.
6. Use `scripts/figure_qa.py` to persist `verified` only after source, output, metadata, render, grayscale, and color-blind checks all pass. Close figure id → caption → `claim_id` → paper reference before handoff.

## Figure classes

- **C-A 正文图:** restrained white-background evidence or validation figure, vector-first and readable in grayscale at final paper size.
- **C-B 诊断图:** visibly diagnostic/exploratory, with useful residual, interval, mechanism, or error annotation; it cannot substitute for claim evidence.
- A `conceptual` figure must say “示意图” in its caption and cannot support a data claim.

## Boundaries

Do not manufacture values, silently redraw stale results, validate the mathematical model, or write paper prose. Request the explicit no-figure skip only when the handoff has no figure claim and no diagnostic figure is required for a stated validation check; record that reason for the orchestrator’s `visualization-skip` guard. A missing renderer, stale source, or inconvenient chart is not a skip.

## Output

Return an updated handoff with `state.current_stage` set to `visualization` and a justified `complete`, `needs_revision`, or guard-satisfied `skipped` status. Record manifests, safe relative figure paths, roles, `claim_id` links, and QA evidence in `result`; put unresolved visual/evidence limits in `quality.warnings`, preserve `quality.confidence`, and populate `next.rationale` and `next.alternatives`. Only a current `verified` manifest can advance to validation.
