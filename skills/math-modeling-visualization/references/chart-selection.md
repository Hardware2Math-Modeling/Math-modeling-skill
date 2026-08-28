# Chart selection

Choose from the claim and the registered data shape, not from decoration.

| Claim task | Prefer | Evidence to show |
| --- | --- | --- |
| Compare named cases | aligned dot, interval, slope, or restrained bar chart | common baseline, units, uncertainty or sample scope |
| Show a distribution | ECDF, histogram, box/violin plus observed points as scale allows | sample size, missingness, interval definition |
| Show change over ordered time | line or step plot | time unit, observed/model distinction, uncertainty |
| Show association | scatter/hexbin with a justified fit | units, data scope, uncertainty; no causal wording from association alone |
| Show ranking or sensitivity | ordered dot/interval or tornado plot | baseline, perturbation range, ties and interval overlap |
| Show validation | prediction-versus-observation, residual, calibration, or error distribution | split/scope, threshold, baseline and failure cases |

Keep diagnostic plots separate from the C-A claim figure. Avoid 3D perspective, rainbow scales, dual axes, truncated quantitative axes, and smoothing that hides observations. Use spatial maps only with registered boundaries and coverage. Preserve missing values as missing unless the registered result explicitly records an imputation method and flags imputed values.

Precision cannot exceed the source result. Put units on axes and in captions when the encoded quantity is not dimensionless; state normalized, indexed, log, percentage, or transformed scales explicitly.
