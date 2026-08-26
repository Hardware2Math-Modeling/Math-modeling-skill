# Math Modeling Suite Architecture

## System boundary

`math-modeling-suite` is one Codex plugin and one versioned distribution unit. The children under `skills/` are independent discovery and invocation units. Installing the plugin makes every skill available; it does not create an automatic program pipeline. `$math-modeling-orchestrator` owns stage selection, state transfer, skip decisions, revision control, and rollback decisions at model runtime.

The initialization layer has no external runtime dependency. It provides contracts and deterministic tooling; future domain work adds mathematical methods behind the existing stage boundaries.

## Component map

| Skill | Owns | Must not own |
| --- | --- | --- |
| `math-modeling-orchestrator` | Cross-stage state, routing, gates, resume, revision, final synthesis | Detailed work of a stage |
| `math-modeling-problem-analysis` | Objectives, constraints, metrics, variables, ambiguities | Final model selection or solving |
| `math-modeling-data-analysis` | Provenance, units, quality, transformations, exploratory evidence | Final model selection or causal invention |
| `math-modeling-model-construction` | Assumptions, notation, candidate models, equations, selection rationale | Full numerical execution |
| `math-modeling-model-solving` | Algorithms, parameters, reproducibility, computed artifacts | Silent model changes or final validation |
| `math-modeling-validation` | Fit, residuals, sensitivity, robustness, feasibility, limitations, rollback | Paper writing after a failed gate |
| `math-modeling-paper-writing` | Traceable presentation of validated work | New evidence, hidden failures, or invented citations |

## Routing source of truth

`skills/math-modeling-orchestrator/references/workflow.json` is the machine-readable stage registry. The suite validator enforces these normal completion transitions:

```text
problem-analysis -> data-analysis | model-construction
data-analysis -> model-construction
model-construction -> model-solving
model-solving -> validation
validation-pass -> paper-writing | complete
validation-fail -> problem-analysis | data-analysis | model-construction | model-solving
paper-writing -> complete
```

Every new problem enters problem analysis first. Data analysis is optional and records a reason when skipped. Paper writing is optional and requires a current validation pass with no invalidated input stage. No route from failed validation may reach paper writing; validation rolls back to the earliest stage invalidated by its evidence.

The transition table applies only after a stage returns `complete` or `skipped`. `needs_revision` does not advance: the orchestrator retries a locally deficient stage or rolls back to the earliest upstream stage invalidated by new evidence. It preserves the prior result as audit evidence, marks affected later work invalid, and reruns every affected downstream stage through validation.

## Modeling Handoff

`skills/math-modeling-orchestrator/references/handoff-contract.md` defines the shared stage output. The minimum stable interface is:

```yaml
schema_version: "1"
task:
  statement: "Original problem or a faithful summary"
  objectives: []
  constraints: []
state:
  current_stage: "problem-analysis"
  status: "complete"
  validation_status: "pending"
  completed_stages:
    - "problem-analysis"
  invalidated_stages: []
quality:
  checks: []
  warnings: []
  confidence: "medium"
result:
  summary: "Stage result"
  details: []
next:
  recommended_stage: "data-analysis"
  rationale: "Why"
  alternatives: []
```

Stages also preserve assumptions, variables, data provenance, methods, decisions, equations, artifacts, failed runs, and validation evidence when those fields apply. `completed_stages` contains only current results; superseded results remain as audit evidence while `invalidated_stages` identifies what must be rerun. A prior validation pass becomes `stale` as soon as any input stage is invalidated. Empty collections are valid; fabricated values are not.

The handoff is a structured model-output contract. Users do not need a database or state file. Persist it only when the active modeling project benefits from an auditable artifact.

## Validation layers

1. `scripts/validate_suite.py` checks source structure, regular-file/symlink boundaries for metadata, manifest fields, skill metadata, stage references, handoff fields, and routing invariants.
2. `python3 -m unittest discover -s tests -p 'test_*.py' -v` checks failures as well as the happy path without model APIs.
3. `scripts/build_bundle.py` creates a clean standard marketplace bundle outside the source tree.
4. `scripts/validate_bundle.py` proves that the marketplace path resolves inside the bundle, applies the archive-tree policy, and checks that the copied plugin still passes suite validation.
5. The bundled Codex plugin and skill validators provide an optional compatibility check when their PyYAML dependency is available.

## Installation boundary

The repository root is the plugin source. A generated bundle adapts it to Codex's local marketplace layout:

```text
bundle/.agents/plugins/marketplace.json
bundle/plugins/math-modeling-suite/.codex-plugin/plugin.json
```

`install_local.py` is dry-run by default. `--apply` is the authorization boundary for `codex plugin marketplace add` and `codex plugin add`.

A configured local marketplace points to an exact bundle root. `--marketplace-registered` skips registration only for that same path; it must not be used with an unrelated fresh temporary directory. Refresh an existing development marketplace through a recoverable directory swap at its registered path, then reinstall the plugin and start a new thread.

The two `--apply` Codex commands are external and sequential rather than transactional. If marketplace registration succeeds but plugin installation fails, inspect the configured marketplace first; retry with `--marketplace-registered` for the exact path, or intentionally remove the newly created `math-modeling-local` marketplace before retrying. The installer never removes an existing marketplace automatically.

Bundle construction stages files in a temporary sibling, validates the staged plugin, and publishes the finished tree atomically. The builder excludes environment files and repository metadata; build or reuse rejects symlinks, unreadable directories, sockets/FIFOs/devices, Git submodules, generated cache paths, known credential filenames, and private-key suffixes, while reuse also rejects any environment file injected after the build. This is deliberately a filename and filesystem-type policy rather than a content-level secret scanner; ordinary-looking files still require human review before distribution.

## Adding a stage or specialization

Add a new skill only when it has a distinct trigger, input/output boundary, and useful independent invocation. Then:

1. Create `skills/<prefixed-name>/SKILL.md` and `agents/openai.yaml`.
2. Add its entry, completion transitions, optionality, and gates to `workflow.json` if the orchestrator routes to it.
3. Define what it adds to the Modeling Handoff and what it must not change.
4. Extend validator constants and structural tests.
5. Run a behavior fixture that asserts a routing or quality invariant rather than exact prose.
6. Validate the source and a generated bundle before reinstalling.

Prefer references inside a stage for substantial method families. Do not grow the orchestrator into a catalog of algorithms.

## Contract evolution

Compatible additions may keep handoff `schema_version: "1"`. Removing a field, changing field meaning, narrowing an accepted value, or altering required routing semantics is incompatible: increment the schema version and document how an existing handoff resumes or migrates.

Stable plugin releases use SemVer. Local development changes only the `+codex.<cachebuster>` build metadata so Codex loads a new cache key without pretending a new public release exists.
