# Development and update workflow

This guide applies to maintained drawing guidance, paper templates, and algorithm methods. Keep user-project inputs, iterations, results, and credentials outside the plugin source. Every change follows the same evidence-first loop:

1. Create or extend a behavior fixture that demonstrates the intended observable contract and first record the current failing baseline.
2. Add the resource under the owning Skill: drawing rules in `skills/math-modeling-visualization/references/` (and styles/assets when needed), paper templates in `skills/math-modeling-paper-production/assets/`, and algorithm methods in `skills/math-modeling-method-library/references/` plus `assets/templates/` and the catalog fixture.
3. Record source URL or provenance, license, upstream/resource version, and SHA-256 in the relevant manifest/catalog record. Do not copy unlicensed source code or embed secrets.
4. Update every machine and human contract touched by the resource: schema and handoff fields, workflow or guard transitions when routing changes, validator constants, focused tests, README, architecture, and changelog.
5. Run the fixture again and implement the smallest change that makes it pass. Preserve old templates, methods, and behavior fixtures as immutable evidence.
6. Build and validate a clean bundle outside the repository:

   ```bash
   bundle_root="$(mktemp -d)/math-modeling-suite-bundle"
   python3 scripts/build_bundle.py --output "$bundle_root"
   python3 scripts/validate_bundle.py "$bundle_root"
   ```

7. Run the offline suite and then a real supplied project smoke using an explicit absolute Python path and any user-supplied LaTeX/renderer paths. The smoke must use a temporary project outside the repository; never install dependencies as part of validation.

## Update a drawing rule

Start with a figure fixture that registers a source hash, role, claim id, axes/units, caption, output dimensions, and expected QA status. Add the rule to the owning visualization references (or style asset), update `figure_qa.py`/`visual_qa.py` contracts and tests, and document the source/license/version/hash. Run `validate_figure_manifest(...)`, export through `scripts/export_figure.py`, perform deterministic figure QA plus human visual review, then run the bundle and supplied-project smokes.

## Update a paper template

Start with a paper-production fixture covering template selection, manifest provenance, immutable copy, required Chinese sections, compilation, page limits, and finalization eligibility. Add the template under `skills/math-modeling-paper-production/assets/` and record source URL, license, version/date, hash, engine, required sections, and whether it is official. Update template schemas, selection/production validators, tests, README, architecture, and changelog. A fallback must remain `fallback_non_submission`; only a user or independently verified official template can become submission-ready. Compile and render with the exact preflight-registered tools, then run the offline and real supplied-project smokes.

## Update an algorithm method

Start with a method-catalog fixture containing deterministic input, seed, expected finite output, validation signals, figure roles, paper notes, and dependency behavior. Add the method reference, catalog entry, executable `solve(data, config)` template, and fixture under `skills/math-modeling-method-library/`; record source/license/version/hash and dependency declarations. Update catalog/schema/validator tests and user-facing docs. Run `python3 scripts/method_catalog.py --root . --check`, then a smoke with `--python /absolute/path/to/python --work-dir /absolute/empty/work-directory`, followed by the bundle and supplied-project smokes. The method library remains read-only support: it never mutates handoffs or routes stages.

## Versioning and immutability

Increment the handoff schema version when removing a field, changing field meaning, narrowing accepted values, or changing required routing semantics. Add migration logic and a compatibility note; never silently reinterpret an old handoff. A compatible additive field may remain on schema version 2 when validators preserve existing semantics.

Increment the competition pack version when competition rules, required deliverables, official-source requirements, page/format constraints, or other event-specific policy changes. Keep the prior pack immutable and select the new version explicitly in a project manifest; do not rewrite old project evidence.

Any result-affecting input, code, parameter, method, or source change creates `iterations/vNNN/` (starting with immutable `v001`) before more work. `current.json` may mix question sources across iterations, while old manifests, templates, figures, runs, and papers remain untouched audit evidence. Mark affected downstream artifacts stale and rerun the required gates. Never overwrite a published template, iteration, manifest, or canonical finalization record.
