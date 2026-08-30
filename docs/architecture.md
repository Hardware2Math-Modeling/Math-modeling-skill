# Math Modeling Suite Architecture

## System boundary

`math-modeling-suite` is one Codex plugin and one versioned distribution unit. Skills under `skills/` are independently discoverable, but the orchestrator is the only component that routes stages, evaluates gates, resumes state, creates immutable iterations, propagates stale evidence, and decides completion. The read-only method library is support material, not a routed stage.

## Routed stages

`skills/math-modeling-orchestrator/references/workflow.json` is the machine-readable source of truth. Exactly these nine stages are routed in this order:

| Stage | Skill | Optionality and boundary |
| --- | --- | --- |
| `preflight` | `math-modeling-preflight` | Required first; verifies the user-supplied absolute Python path, project, inputs, dependencies, LaTeX tools, and template. |
| `problem-analysis` | `math-modeling-problem-analysis` | Required; records objectives, subproblems, variables, constraints, metrics, units, and assumptions. |
| `data-analysis` | `math-modeling-data-analysis` | Conditionally required when data or external data is relevant; otherwise records a guarded skip reason. |
| `model-construction` | `math-modeling-model-construction` | Required; proposes candidates, baseline, equations, assumptions, and validation plan for each question. |
| `model-solving` | `math-modeling-model-solving` | Required; executes only the Gate 2 accepted model with the registered Python interpreter and persists reproducible evidence. |
| `visualization` | `math-modeling-visualization` | Conditionally required for figure claims or figure-based checks; registers sources, roles, outputs, and figure QA before validation. |
| `validation` | `math-modeling-validation` | Required; runs declared checks and rolls back to the earliest invalidated stage on failure. |
| `paper-writing` | `math-modeling-paper-writing` | Required after a trusted paper request; writes only from current validated and frozen evidence. |
| `paper-production` | `math-modeling-paper-production` | Required after paper writing; copies the template, compiles LaTeX, renders pages, performs QA, and finalizes only eligible templates. |

`math-modeling-method-library` is a read-only support Skill. It exposes maintained method ids, references, deterministic templates, dependency metadata, validation guidance, and figure/paper notes. It has no workflow stage id, does not write project state, and never authorizes model selection or a downstream route.

Normal completion transitions are:

```text
preflight -> problem-analysis
problem-analysis -> data-analysis | model-construction
data-analysis -> model-construction
model-construction -> model-solving
model-solving -> visualization | validation
visualization -> validation
validation-pass -> paper-writing | complete
validation-fail -> problem-analysis | data-analysis | model-construction | model-solving
paper-writing -> paper-production
paper-production -> complete
```

Optionality is guard-controlled: data analysis may skip only with a reason when no relevant data exists; visualization may skip only with a reason when there is no figure claim or diagnostic requirement; paper stages may skip only when no trusted paper request exists. `needs_revision` never advances downstream.

## Persistent state and handoff

The user-supplied project root contains immutable evidence:

```text
modeling_project/
├── input/                         # original inputs, copied read-only
├── iterations/
│   ├── v001/                      # first immutable snapshot
│   └── v002/                      # new snapshot for result-affecting changes
├── current.json                   # active iteration and per-question source pointers
├── qa/                            # append-only gates and stale reports
└── archive/                       # retained audit notes
```

Each iteration has `state/`, `code/`, `data/`, `results/`, `figures/`, `paper/`, and `manifests/`. Runtime handoffs and machine records use schema version `2`; legacy schema-version-1 handoffs are migrated through `scripts/migrate_handoff.py` before runtime validation. State records current stage/status, validation status (`pending`, `pass`, `needs_revision`, `stale`), completed stages, invalidated stages, assumptions, decisions, artifacts, hashes, and bounded next-stage rationale.

Any input, code, parameter, method, result, or registered source change creates a new immutable iteration before further work. `current.json` may mix question sources (for example Q1 from `v001`, Q2 from `v002`); dependent runs, figures, validation, and paper evidence are marked stale and old files remain untouched. Downstream authorization reloads the canonical current pointer, handoff, manifests, gates, and real file hashes; a pointer status, recommendation, or self-authored receipt is never sufficient.

Gate 1 confirms interpretation and assumptions. Gate 2 confirms each model, baseline, parameter source, and validation plan. Gate 3 freezes current results, run/validation manifests, and any figures. Validation failure cannot route to paper writing or production; completion also requires current accepted-model, dependency, environment, official-rule, and (when requested) paper-finalization evidence.

## Validation and bundle boundaries

1. `python3 scripts/validate_suite.py` checks regular-file metadata, manifest schema, frontmatter, stage registry, support contract, handoff fields, guards, and routing invariants.
2. `python3 -m unittest discover -s tests -p 'test_*.py' -v` exercises deterministic unit, contract, and offline end-to-end behavior without model APIs.
3. `python3 scripts/build_bundle.py --output <outside-source-dir>` builds a temporary sibling marketplace bundle and validates the staged plugin before atomic publication.
4. `python3 scripts/validate_bundle.py <bundle>` checks marketplace path resolution, archive-tree policy, copied plugin validation, and regular-file/symlink/special-file boundaries.

Bundle construction excludes environment files, Git metadata, worktrees, generated bundles, bytecode, and common caches. It rejects symlinks, symlinked components, special nodes, Git submodules, known credential filenames, and private-key suffixes. This is a deterministic filename/type boundary, not a content-level secret scanner; human review remains required. The installed Skill tree is read-only from the perspective of user projects, and project-specific inputs/results never belong in the bundle.

## Extending the suite

Add a routed stage only when it has a distinct trigger, input/output boundary, handoff fields, guard, and transition. Add maintained methods, drawing guidance, or templates under the owning Skill’s `references/` and `assets/` directories rather than expanding the orchestrator. Update the validator, behavior fixtures, tests, README, architecture, development guide, and changelog, then build and validate a bundle and run both offline and supplied-project smoke checks. See [development.md](development.md).
