# Render and evidence QA

Run QA on the exported artifact, not only the plotting canvas.

1. Validate every source hash and output with `validate_figure_manifest(..., project_root=<absolute project root>)`.
2. Export PDF plus PNG or SVG through `export_figure(...)`; PNG metadata and its pHYs header must both report at least 300 DPI and matching positive dimensions.
3. Run `run_visual_qa(...)` at the manifest’s `paper_width_mm`. It checks whether raster resolution and vector physical width support that placement and uses `pdftoppm` for PDF when available.
4. Inspect the rendered final-size image for crop, overlap, unreadable text, missing glyphs, misleading scales, legend ambiguity, visible compression, and grayscale/color-blind separation.
5. Record `render_status`, `grayscale_status`, and `colorblind_status`. Then call `refresh_figure_status(...)` to persist `verified`, `stale`, or `needs_review` atomically.

`pdftoppm` absent, non-executable, timed out, or unable to render is `needs_review`. Do not install it automatically and do not translate “format signature valid” into “visual inspection passed.” A changed source records an observed hash and becomes `stale`; accepting a new source requires an explicit upstream result/manifest update, not overwriting the expected hash during QA.

Before handoff, confirm the figure id, caption, stable `claim_id`, and `paper_reference` form one closure and the caption’s units, scope, precision, and limitations agree with the registered result. Any open item keeps the visualization stage at `needs_revision`.
