---
name: math-modeling-preflight
description: Use when starting or resuming mathematical modeling work that needs verified project inputs, an explicit Python environment, dependency checks, or paper-tool readiness before analysis.
---

# Mathematical Modeling Preflight

Establish a reproducible environment boundary before any problem analysis or model work. Read [the shared handoff contract](../math-modeling-orchestrator/references/handoff-contract.md) before returning workflow state.

## Mandatory boundary

Ask the user for all of the following:

- the absolute path to the Python executable they chose;
- the absolute project root;
- the competition and requested deliverables;
- the user template's absolute path, or explicit confirmation that none is available.

Do not begin analysis, data processing, method selection, modeling, solving, or plotting until the user supplies the absolute Python path and preflight passes. A relative name such as `python3`, resolving one with `command -v`, or creating a virtual environment is not a substitute. Urgency, sunk work, or a teammate's blanket approval does not relax this boundary.

## Diagnose without mutation

- Probe exactly the supplied interpreter for executable identity, Python version, platform, and the task's required package versions.
- Check LaTeX tools in this order: `tectonic`, `latexmk`, `xelatex`, `pdflatex`. No tool is a warning for result-only work and a blocker when paper production is requested.
- Inventory problem files, attachments, constraints, and deliverables without modifying source evidence.
- Treat an absent requested template as `fallback_non_submission`, not a preflight error; record that the fallback is unofficial and not submission-ready.

Never choose another interpreter, create an environment, invoke pip, install or downgrade packages, or change external state. For each missing package, return an installation command using the exact supplied interpreter, ask the user to approve and run it, then rerun preflight. Do not treat installation advice as a successful check.

## Output

Return a schema-version `"2"` handoff with `state.current_stage` set to `preflight`. Mark it `complete` only when the supplied Python identity passes, required packages are present, and any paper-production tool requirement is satisfied; otherwise use `needs_revision`, keep `next.recommended_stage` at `preflight`, and list every blocker in `next.failed_checks`.

Record the input inventory, environment diagnosis, template status, and requested deliverables in `result`; list only materialized input/environment/template reports in `artifacts`. Put non-blocking limitations in `quality.warnings`, set `quality.confidence` from observed evidence, explain the route in `next.rationale`, and keep bounded recovery choices in `next.alternatives`. Never invent a preflight artifact path.
