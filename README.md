# Math Modeling Skill Suite

A Codex plugin for staged mathematical modeling workflows, initially focused on CUMCM-style problems. One orchestrator routes work through six independently discoverable skills: problem analysis, data analysis, model construction, model solving, validation, and paper writing.

This repository currently provides the plugin architecture and development workflow. It deliberately does not claim a complete catalog of mathematical methods yet.

## Architecture

```text
math-modeling-orchestrator
  -> math-modeling-problem-analysis
  -> math-modeling-data-analysis       (optional)
  -> math-modeling-model-construction
  -> math-modeling-model-solving
  -> math-modeling-validation
       -> model construction/solving   (failed validation)
       -> math-modeling-paper-writing   (optional, passed validation)
```

The plugin is the installation and version boundary. Each directory under `skills/` is an independent Codex skill. The orchestrator owns cross-stage routing; stage skills return a structured Modeling Handoff but do not call one another or declare the whole problem complete.

Only a `complete` or justified `skipped` stage advances through the normal workflow. A `needs_revision` result retries the current stage or rolls back to the earliest invalidated upstream stage, then reruns every affected downstream stage.

See [docs/architecture.md](docs/architecture.md) for the stage registry, handoff contract, safety boundaries, and extension rules.

## Requirements

- Python 3.10 or newer for repository scripts and tests
- Codex CLI with plugin commands for local installation
- No Python packages, API keys, solver runtimes, or network access for validation and bundle creation

## Validate the source

```bash
python3 scripts/validate_suite.py
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The validator checks the plugin manifest, skill frontmatter, UI metadata, stage registry, handoff contract, skip/rollback rules, and unresolved scaffold markers.

## Build a local marketplace bundle

Codex local marketplaces resolve plugin paths from a standard bundle layout. Keep generated bundles outside this repository:

```bash
bundle_root="$(mktemp -d)/math-modeling-suite-bundle"
python3 scripts/build_bundle.py --output "$bundle_root"
python3 scripts/validate_bundle.py "$bundle_root"
```

The bundle contains:

```text
<bundle>/
  .agents/plugins/marketplace.json
  plugins/math-modeling-suite/
```

The builder refuses to overwrite a non-empty directory or write inside the source tree. It excludes Git metadata, isolated worktrees, generated local bundles, bytecode, and common caches.

## Preview and install locally

For installation, choose a persistent bundle path outside the repository. Start with a dry run; it builds or reuses a valid bundle and prints the exact Codex commands without changing Codex configuration:

```bash
bundle_root="/absolute/persistent/path/math-modeling-suite-bundle"
python3 scripts/install_local.py --bundle "$bundle_root"
```

After reviewing the output, install from that same validated bundle:

```bash
python3 scripts/install_local.py --bundle "$bundle_root" --apply
```

This runs:

```bash
codex plugin marketplace add "$bundle_root"
codex plugin add math-modeling-suite@math-modeling-local
```

Restart Codex if it is open, then use a new thread so the installed skill set is loaded cleanly.

## Invoke the skills

Use the orchestrator for an end-to-end problem:

```text
Use $math-modeling-orchestrator to work through this modeling problem: <problem>
```

Use a stage skill directly for bounded work:

```text
Use $math-modeling-validation to validate these model results and identify the correct rollback if a check fails.
```

All available skill names are listed in [docs/architecture.md](docs/architecture.md).

## Development update loop

Preview a cachebuster change:

```bash
python3 scripts/update_cachebuster.py
```

Apply it only when the source should move to a new local plugin cache key:

```bash
python3 scripts/update_cachebuster.py --apply
```

The configured local marketplace records its bundle root. To update without changing that registration, build a fresh staging bundle, preserve the current bundle as a recoverable backup, and put the fresh bundle at the exact registered path:

```bash
registered_bundle="/absolute/persistent/path/math-modeling-suite-bundle"
staging_parent="$(mktemp -d)"
staging_bundle="$staging_parent/math-modeling-suite-bundle"
backup_bundle="${registered_bundle}.backup-$(date -u +%Y%m%d-%H%M%S)"

python3 scripts/build_bundle.py --output "$staging_bundle"
python3 scripts/validate_bundle.py "$staging_bundle"
mv "$registered_bundle" "$backup_bundle"
mv "$staging_bundle" "$registered_bundle"
python3 scripts/install_local.py \
  --bundle "$registered_bundle" \
  --marketplace-registered \
  --apply
```

Keep the backup until the plugin has been verified. `--marketplace-registered` is valid only when the exact `--bundle` path is already registered; inspect `codex plugin marketplace list --json` if uncertain. Start a new Codex thread after reinstalling.

Stable releases use SemVer. Local iterations replace only the `+codex.local-<UTC timestamp>` build metadata.

## Safety boundaries

- Validation, tests, bundle creation, and installer dry runs do not modify Codex configuration.
- `install_local.py` requires `--apply` before it runs external Codex commands.
- `update_cachebuster.py` requires `--apply` before it edits the plugin manifest.
- The plugin does not install solver runtimes, TeX, Python packages, MCP servers, or credentials.
- Failed model validation cannot route to paper writing.

## License

MIT. See [LICENSE](LICENSE).
