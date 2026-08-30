# Math Modeling Suite

Math Modeling Suite is a Codex plugin that runs a staged mathematical-modeling workflow from problem analysis through validated results, with figures and paper production when relevant.

**[中文指南](../README.md)**

## Prerequisites

- [Codex CLI](https://developers.openai.com/codex/cli/reference/) with `plugin` commands
- Git
- Python 3.10+

The installer builds, validates, and registers a local Codex plugin bundle. It does not install Python packages, LaTeX, solver runtimes, MCP servers, or credentials.

## First installation

Clone the repository and run the installer from its root. `--bundle` must name a nonexistent or empty directory **outside the repository**.

### macOS / Linux

```bash
git clone <repository-url>
cd Math-modeling-skill

BUNDLE_PATH="/absolute/path/outside/this/repository/math-modeling-suite-bundle"
python3 scripts/install_local.py --bundle "$BUNDLE_PATH" --apply
```

### Windows PowerShell

```powershell
git clone <repository-url>
Set-Location Math-modeling-skill

$BundlePath = "C:\CodexBundles\math-modeling-suite-bundle"
py -3 scripts/install_local.py --bundle $BundlePath --apply
```

Restart Codex if it was open, and use the plugin in a new thread. Confirm the installation with:

```bash
codex plugin list
```

The list should include `math-modeling-suite`.

## Get the absolute Python path

The workflow uses only the interpreter you explicitly supply. Verify Python 3.10+ and copy its absolute path.

macOS / Linux:

```bash
python3 --version
python3 -c 'from pathlib import Path; import sys; print(Path(sys.executable).resolve())'
```

Windows PowerShell:

```powershell
py -3 --version
py -3 -c "from pathlib import Path; import sys; print(Path(sys.executable).resolve())"
```

## First use

Start a new Codex thread and replace every example value below:

```text
Use $math-modeling-orchestrator for this mathematical-modeling task.

- Project directory (absolute path): /absolute/path/to/my-modeling-project
- Problem and attachments (text or absolute paths): /absolute/path/to/problem-and-attachments
- Python executable (absolute path): /absolute/path/to/python
- Competition: CUMCM
- Paper required: yes
- LaTeX template (optional absolute path; write "not provided" if absent): /absolute/path/to/main.tex

Run preflight first. Stop at every human confirmation gate and explain what I need to approve.
```

Gate 1 confirms the problem interpretation and key assumptions. Gate 2 confirms each model, baseline, parameter sources, and validation plan. Gate 3 freezes the current results, validation evidence, and any figures. Data analysis, visualization, and paper stages are routed only when relevant.

## Help and deeper documentation

- [Operations](operations.md): troubleshooting, updates/removal, routing, evidence, validation, figures, and paper production
- [Architecture](architecture.md)
- [Development and resource updates](development.md)
- [Changelog](../CHANGELOG.md)
- [Codex Skills](https://developers.openai.com/codex/skills/), [Codex CLI reference](https://developers.openai.com/codex/cli/reference/), and [Build plugins](https://developers.openai.com/plugins/build/plugins/)

MIT licensed; see [LICENSE](../LICENSE).
