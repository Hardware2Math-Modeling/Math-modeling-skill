# Visual style

Apply `assets/styles/modeling.mplstyle`. It fixes a Unicode-capable CJK fallback stack, white background, outward ticks, consistent lines/markers, 300-DPI saving, and the color-blind-safe Okabe–Ito palette.

## C-A main-text figures

- Use few colors, direct ordering, restrained annotation, and vector output.
- Keep typography, line widths, marker sizes, panels, and numeric precision consistent across the paper.
- Encode an important distinction with shape, line style, marker, label, or position as well as color.

## C-B diagnostic figures

- Retain the shared typography and palette, but annotate thresholds, intervals, residual structure, failure cases, and mechanism cues that aid diagnosis.
- Label the figure diagnostic/exploratory; visual emphasis does not promote it to evidence.

Review at the intended paper width. Confirm glyphs and minus signs render, thin lines and markers survive grayscale, adjacent series remain separable under common color-vision deficiencies, and annotations do not obscure data. Do not claim a palette check passed merely because the palette is nominally color-blind safe.
