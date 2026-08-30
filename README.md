# Math Modeling Skill Suite

A Codex plugin for a persistent, staged mathematical-modeling workflow. The orchestrator routes nine independently discoverable stages—preflight, problem analysis, data analysis, model construction, model solving, visualization, validation, paper writing, and paper production—and can consult a separate read-only method library.

The suite keeps project evidence outside the installed plugin, executes modeling code only with a user-supplied Python interpreter, produces LaTeX papers only from current validated evidence, and fails closed when a required gate or artifact is missing, stale, or inconsistent.

## Workflow

```text
preflight
  -> problem-analysis
  -> data-analysis? -> model-construction
  -> model-solving -> visualization? -> validation
  -> paper-writing? -> paper-production? -> complete
```

`data-analysis` is required when relevant data exists. `visualization` is required for a figure claim or a declared figure-based validation check. Once a trusted paper request exists, both paper stages are required. `$math-modeling-orchestrator` owns routing, the three confirmation gates, rollback, resume, and completion checks; stage skills do not authorize their own downstream route.

`math-modeling-method-library` is read-only support, not a tenth workflow stage. It provides maintained method ids, references, deterministic Python templates, dependency declarations, validation guidance, and figure/paper guidance without changing project state or selecting a model.

See [docs/architecture.md](docs/architecture.md) for the exact stage registry, persistent state contract, and validation boundaries.

## Start with an explicit Python preflight

Tell the orchestrator the absolute project root, the absolute Python executable chosen for the work, the competition and deliverables, and the absolute user-template path or that no template is available. A command name such as `python3` is not an accepted interpreter identity. Preflight probes exactly the supplied executable and never creates an environment, invokes pip, or substitutes another interpreter.

For repository-level method smoke tests, `--python` is also mandatory and must point to the supplied absolute interpreter. `--work-dir` must be an empty directory outside the repository:

```bash
python3 scripts/method_catalog.py \
  --root . \
  --check \
  --smoke \
  --python /absolute/path/to/python \
  --work-dir /absolute/empty/work-directory
```

The implemented preflight API is `diagnose_environment(...)` in `scripts/preflight.py`. Project initialization is exposed as `init_project(...)` and by this CLI:

```bash
python3 scripts/project_state.py init /absolute/project/root \
  --python-executable /absolute/path/to/python \
  --input-dir /absolute/path/to/input \
  --competition CUMCM
```

Add `--template-path /absolute/path/to/main.tex` when a user template is available. The project root must not already exist; initialization copies source inputs into a read-only inventory, writes versioned manifests, and creates the first immutable iteration as `iterations/v001/`.

## Immutable iterations, gates, and stale evidence

`current.json` points to the active iteration and may deliberately mix question sources, for example Q1 from `v001` and Q2 from `v002`. A result-affecting change creates a new iteration instead of overwriting an old one:

```bash
python3 scripts/project_state.py new-iteration /absolute/project/root \
  --reason "revise Q2 parameter source" \
  --question Q2
```

Old iteration directories and templates remain audit evidence. The state layer writes strict schema-version-2 handoffs, input/environment/dependency/run/result/figure/validation/paper manifests, and append-only gate evidence. Changes to input, code, parameters, methods, results, or registered sources make dependent evidence stale. Mixed iterations are permitted only while every referenced question dependency is current and frozen; paper assembly and completion recheck the real files and hashes.

Gate 1 confirms the problem interpretation and key assumptions. Gate 2 confirms the per-question model, baseline, parameter sources, and validation plan. Gate 3 freezes the current results, validation, runs, and any figures. A label in `current.json` or a stage recommendation does not substitute for a valid host-bound confirmation record.

## Figures and figure QA

The visualization stage registers a figure manifest before drawing and binds the figure to current result-file hashes, a claim id, axes and units, legend decision, caption, paper reference, width, role, and outputs. `scripts/export_figure.py` exposes `export_figure(...)`; it publishes PDF plus PNG or SVG only from registered current sources.

Deterministic figure QA uses `validate_figure_manifest(...)` and `refresh_figure_status(...)` from `scripts/figure_qa.py`, followed by render inspection through `run_visual_qa(...)` in `scripts/visual_qa.py`. A figure advances as `verified` only after source hashes, file format, dimensions, resolution, metadata, grayscale/color-blind checks, and human visual review are current. Missing `pdftoppm` is `needs_review`; a changed source is `stale`, never an implicit hash refresh.

## LaTeX paper production and fallback status

Template priority is user-provided, user-selected official, locally verified official, then the built-in Chinese fallback. The fallback under `skills/math-modeling-paper-production/assets/fallback-zh/` is deliberately `fallback_non_submission`: it can support assembly and compilation checks, but it can never authorize `submission_ready: true`.

Paper writing freezes Chinese content only from current validated evidence. Paper production copies the selected template into the active iteration, assembles the content, compiles with the preflight-registered LaTeX tool, checks structure/references/numbers and the 25–27 body-page target with a 30-page total maximum, renders pages through the registered renderer, and requires visual review before finalization. Failures keep immutable attempt logs and a non-ready status.

## Validate the source and method catalog

These checks require no model API or network access:

```bash
python3 scripts/validate_suite.py
python3 scripts/method_catalog.py --root . --check
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The offline end-to-end fixture exercises project initialization, routing gates, Python results, figures, validation, mixed immutable iterations, stale propagation, and fallback paper production. A separate real-compiler smoke runs only when a supported compiler is available.

## Build and validate a distribution bundle

Keep generated bundles outside the repository:

```bash
bundle_root="$(mktemp -d)/math-modeling-suite-bundle"
python3 scripts/build_bundle.py --output "$bundle_root"
python3 scripts/validate_bundle.py "$bundle_root"
```

The builder validates source and staged copies, selects tracked plus non-ignored untracked files, writes the local marketplace layout in a temporary sibling, validates it, and publishes atomically. It refuses a non-empty destination or an output inside the source tree. Environment files are excluded; symlinks, symlinked path components, special filesystem nodes, Git submodules, known credential filenames, private-key suffixes, Git metadata, worktrees, generated bundles, and common caches are rejected or excluded according to the shared archive policy. This filename/type boundary is not a general content secret scanner, so distribution contents still require human review.

## Maintainer resource locations

- Drawing guidance lives in `skills/math-modeling-visualization/references/`; the plotting style lives in `skills/math-modeling-visualization/assets/styles/`.
- Paper templates live in `skills/math-modeling-paper-production/assets/`; selection, production, and finalization rules are owned by that Skill and `scripts/paper_production.py`.
- Method metadata and method guidance live in `skills/math-modeling-method-library/references/`; executable templates and their smoke fixture live in `skills/math-modeling-method-library/assets/`.

Follow [docs/development.md](docs/development.md) for the behavior-fixture-first update workflows, provenance records, version rules, bundle checks, and supplied-project smoke test.

## Safety boundaries

- The plugin never installs Python packages, solver runtimes, TeX, MCP servers, or credentials.
- Repository validation and bundle creation do not modify Codex configuration or a user modeling project.
- All modeling project output belongs under the user-supplied project root, never under the installed Skill tree.
- Unknown, pending, rejected, stale, failed, or malformed prerequisites block downstream authorization and project completion.
- Failed validation cannot route to paper writing or paper production.

## License

MIT. See [LICENSE](LICENSE).
