---
name: math-modeling-method-library
description: Use when a modeling stage needs to retrieve or compare maintained method ids, assumptions, dependencies, executable templates, validation needs, or paper and figure guidance without advancing workflow state.
---

# Mathematical Modeling Method Library

Retrieve maintained method records for a calling modeling stage. The caller remains responsible for evidence, selection, implementation, validation, and workflow status.

Read the machine-readable [support contract](references/support-contract.json) first. It is the authoritative read-only and state-access boundary.

## Retrieve a maintained method

1. Search [the catalog](references/catalog.json) by its exact Chinese `family` or English `id`. Do not invent, rename, or compose a catalog id. If the task suggests an extension, keep one maintained base id and list the extension separately.
2. Read only the selected [method reference](references/methods/) and its catalog-named template under `assets/templates/`. Return the stable id and family so the choice is auditable.
3. Check the catalog `dependencies` against the caller's preflight report. An empty list means standard library only. A missing or unprobed dependency is blocking; do not install it, choose another interpreter, or silently substitute a different method.
4. Return applicability, assumptions, input meanings and units, formula and parameter meanings, scale boundary, failure signals, validation, figure roles, paper wording, and provenance/license notes. Separate catalog facts from task-specific judgment and alternatives.

Catalog figure roles use only `evidence`, `validation`, `diagnostic`, and `conceptual`. Preserve each `claim_supporting` flag; diagnostic, conceptual, or otherwise exploratory figures do not support a result claim.

## Executable boundary

Templates expose `solve(data, config) -> {values, metrics, assumptions}` and the common `--input/--output/--seed` JSON interface. They are deterministic for a fixed input and seed. Template execution belongs to the calling solving stage, using the user-supplied absolute interpreter and the repository runner; this support skill does not execute project code.

Catalog maintainers can validate with `python3 scripts/method_catalog.py --root . --check`. Smoke execution additionally requires explicit `--python /absolute/path` and an empty external `--work-dir`; it has no implicit interpreter and installs nothing.

## Fail closed

For an unknown family/id, missing field or dependency, unsafe template path, invalid catalog, or failed/non-finite smoke output, report the exact failure and stop retrieval or execution. Do not fall back to a nearby id, another package, or another method. A catalog entry is a maintained option, not evidence that it is selected, fitted, feasible, or validated for the task.

## Resource boundary

Consult catalog, references, fixtures, and templates without modifying them during a modeling task.

## State boundary

Return the retrieval record to the calling stage without mutating its handoff or advancing workflow state. Do not create competition artifacts. This skill does not replace problem analysis, construction, solving, validation, or user judgment.
