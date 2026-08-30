# Figure roles and claim closure

Use exactly one role.

| Role | Class | May support a result claim? | Required treatment |
| --- | --- | --- | --- |
| `evidence` | C-A | yes | Link a stable `claim_id` to current registered results. |
| `validation` | C-A | yes, within the stated test scope | Name the split/scope, baseline, threshold, and uncertainty as applicable. |
| `diagnostic` | C-B | no | Label diagnostic/exploratory and use it to inspect assumptions, errors, or mechanisms. |
| `conceptual` | explanatory | no | Put “示意图” in the caption; never present it as data evidence. |

Only a diagnostic manifest with `exploratory_draft: true`, `claim_type: exploratory`, and `status: draft` may temporarily omit `claim_id`. All other figures need a nonempty stable claim id.

Register before drawing. A complete entry has this shape:

```json
{
  "schema_version": "1",
  "figure_id": "q1-error-distribution",
  "question_id": "Q1",
  "claim_id": "claim-q1-03",
  "claim_type": "data",
  "role": "validation",
  "exploratory_draft": false,
  "sources": [{"path": "results/q1/metrics.json", "sha256": "<64 lowercase hex>"}],
  "outputs": [
    {"path": "figures/q1-error-distribution.pdf", "format": "pdf"},
    {"path": "figures/q1-error-distribution.png", "format": "png", "width_px": 1200, "height_px": 800, "dpi_x": 300, "dpi_y": 300}
  ],
  "axes": [
    {"id": "x", "label": "Absolute error", "unit": "model unit"},
    {"id": "y", "label": "Cumulative proportion", "unit": "1"}
  ],
  "legend": {"present": false, "reason": "single series"},
  "paper_width_mm": 85,
  "caption": "Held-out absolute-error distribution for Q1.",
  "paper_reference": "Figure 3",
  "grayscale_status": "needs_review",
  "colorblind_status": "needs_review",
  "render_status": "needs_review",
  "status": "draft"
}
```

Update a paper reference when numbering changes; do not change `figure_id` or `claim_id` merely because layout changes. The caption states what is shown, the registered scope, uncertainty/limitations, and the supported claim without adding a number absent from the source.
