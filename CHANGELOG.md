# Changelog

## [0.2.0] - 2026-08-30

### Added

- Completed the nine-stage routed workflow from `preflight` through `paper-production`, with guarded data/visualization/paper stages and a read-only method library.
- Added deterministic project initialization, explicit user-supplied Python preflight, immutable `v001`/`v002` iterations, mixed question-source pointers, stale propagation, gate records, manifest hashing, figure QA, and Chinese LaTeX paper production.
- Added maintained method references and executable Python templates, visualization guidance and style assets, a Chinese fallback template, and offline end-to-end fixtures.
- Added deterministic marketplace bundle build and validation checks for regular files, environment and credential boundaries, symlinks, special files, private-key suffixes, and exclusion of fixture/user project state.

### Migration

- Runtime handoffs now use schema version 2. Existing schema version 1 handoffs must be migrated with `scripts/migrate_handoff.py` and then validated with `scripts/validate_handoff.py --mode runtime` before routing.
- The plugin manifest is release `0.2.0` and retains the `./skills/` discovery root. Local cachebuster metadata remains a development-only concern.

### Compatibility

- The built-in paper template is always marked `fallback_non_submission`; it can compile for review but cannot become `submission_ready`.
- Validation and bundle commands remain offline and do not install Python packages, LaTeX, solver runtimes, MCP servers, or credentials. User projects must provide an absolute Python path and, when paper production is requested, suitable LaTeX/renderer tools.
- Older immutable iterations, templates, manifests, and evidence remain readable audit records; result-affecting changes create a new iteration and propagate stale status instead of overwriting history.

### Release verification

- Fresh deterministic verification passed suite validation, the 30-entry method catalog check, 458 of 458 unit and contract tests with zero skips, bundle build and validation, and the no-write local installer dry-run.
- The installed official `validate_plugin.py` and `quick_validate.py` files were present but unavailable under the release interpreter because the `yaml`/PyYAML dependency was missing; source and bundle invocations exited 1, and no dependency was installed.
- LaTeX doctor reported an existing usable TeX Live 2026 environment; the latexmk 4.88 smoke test passed. Bundled Tectonic 0.16.9 was detected, but its managed-environment smoke test failed with `Operation not permitted`.
