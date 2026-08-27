# Math Modeling Complete Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有插件骨架实现为一套可恢复、可验证、Python-only、LaTeX-only 的 CUMCM 中文数学建模 Skill 套件，并用离线 fixture 证明它能从题目输入走到结果、图表、论文和质量门禁。

**Architecture:** 保留一个插件、多 Skill 的边界，把运行时状态放在用户指定的赛题项目中。preflight、完整 handoff/schema、manifest、迭代和 Python runner 组成确定性底座；模型分析、方法库和写作 Skill 只负责有证据的决策与叙事；绘图和 LaTeX 生产由独立阶段负责；orchestrator 只按 workflow 和人工门路由，不把算法或文件内容藏在提示词记忆中。

**Tech Stack:** Codex plugin/skill manifests，Markdown，JSON Schema，Python 3.10+ 标准库，用户提供的 Python 环境，unittest，Matplotlib（用户环境中按需），Tectonic/XeLaTeX/latexmk（按用户环境检测），PDF/SVG/PNG。

---

## Scope and file map

本计划是一个有共享契约的四阶段实现计划，而不是四个互相独立的产品：阶段 1 先提供可恢复底座，阶段 2 和 3 通过 manifest 接入它，阶段 4 才能进行端到端验收。每个阶段在自己的检查点都能运行离线测试。

| 路径 | 责任 |
| --- | --- |
| .codex-plugin/plugin.json | 插件版本、描述和发现元数据 |
| skills/math-modeling-orchestrator/ | workflow、路由规则、门禁和恢复说明 |
| skills/math-modeling-preflight/ | 用户配置和环境诊断 Skill |
| skills/math-modeling-method-library/ | 十类方法的只读目录和 30 个最小 Python 模板 |
| skills/math-modeling-visualization/ | 图表登记、导出、风格和渲染 QA Skill |
| skills/math-modeling-paper-production/ | 模板复制、LaTeX 装配、编译、页数和 PDF QA Skill |
| skills/math-modeling-*/SKILL.md | 各阶段的输入、输出、边界和证据规则 |
| scripts/handoff_schema.py | 完整 handoff 的结构检查和版本化迁移共用逻辑 |
| scripts/validate_handoff.py | handoff 校验 CLI |
| scripts/migrate_handoff.py | 旧对话 handoff 到持久运行时 handoff 的迁移 CLI |
| scripts/project_state.py | 项目初始化、迭代、current 指针、gate 和 stale 传播 |
| scripts/manifest.py | 路径安全、SHA-256、输入/环境/模板/运行 manifest |
| scripts/python_runner.py | 使用用户指定解释器执行 Python 并记录运行证据 |
| scripts/preflight.py | Python 包、LaTeX 工具链、输入和模板诊断 |
| scripts/result_contract.py | 每问结构化结果、claim、baseline 和阈值检查 |
| scripts/figure_qa.py | figure manifest、源 hash、格式/DPI 和 stale 检查 |
| scripts/export_figure.py | 统一 Matplotlib 风格和多格式导出 |
| scripts/visual_qa.py | 按论文实际尺寸进行可选渲染和文件级检查 |
| scripts/paper_content.py | 论文内容契约、章节/摘要/符号/引用一致性检查 |
| scripts/paper_production.py | 模板复制、LaTeX 编译、页数和提交状态判定 |
| scripts/latex_qa.py | PDF 结构、页数、引用和正文范围检查 |
| skills/math-modeling-orchestrator/references/schemas/ | handoff、iteration、manifest、gate、paper、figure schema |
| skills/math-modeling-orchestrator/references/competition-packs/cumcm.json | CUMCM 工作流约束和官方规则核验入口 |
| tests/fixtures/cumcm-mini/ | 无网络、无模型 API 的小型中文赛题及模板 |
| tests/test_*.py | 静态、状态、runner、绘图、论文和端到端契约测试 |
| docs/architecture.md、README.md、docs/development.md | 用户运行和维护更新指南 |
| CHANGELOG.md | 版本、迁移和兼容性记录 |

运行时项目固定使用：

    modeling_project/
    ├── input/                         # 原题与附件，只读证据
    ├── iterations/vNNN/               # 不可覆盖的迭代快照
    │   ├── state/ code/ data/ results/ figures/ paper/ manifests/
    ├── current.json                   # 按问来源版本和三道门状态
    ├── qa/                            # 汇总报告
    └── archive/                       # 版本退役说明

所有项目路径参数必须是绝对路径；插件安装目录只读，赛题产物不得写回 Skill 源码或 bundle。

## Conventions locked before coding

1. 持久化运行时 handoff 使用 schema_version: "2"；现有会话中的最小 v1 handoff 仍可由 --legacy 校验并通过迁移工具转换。workflow 自身版本为 2。
2. workflow 阶段顺序固定为 preflight → problem-analysis → data-analysis? → model-construction → model-solving → visualization? → validation → paper-writing? → paper-production?。method-library 是只读查询包，不是状态机阶段。
3. data-analysis 仅在没有数据、没有估计/预测任务且记录理由时可跳过；存在相关数据时必须运行。visualization 在正文或附录引用图时必需；没有任何图需求时记录结构化跳过。用户要求论文时 paper-writing 和 paper-production 均必需。
4. Gate 记录只接受 pending、confirmed、rejected 三个状态；确认记录必须包含 gate id、确认人、UTC 时间、依据 artifact hash、备注和 schema 版本。
5. 图的 role 只接受 evidence、validation、diagnostic、conceptual；conceptual 必须带“示意图”标记，不能支持数据 claim。
6. 结果、图和论文均以当前输入 hash 判断新鲜度。影响某问的输入、代码、参数或方法改变时创建新的 vNNN，旧目录保留并标记 stale。
7. submission-ready 需要用户模板或已核验官方模板；fallback 可编译但 template_status 永远是 fallback_non_submission。正文页数从第 1 部分到第 8 部分计，总页数包含所有页面和附录。
8. 所有命令使用参数数组执行，不经过 shell；不自动安装依赖。缺包或缺工具只产生精确安装建议，待用户确认后再次 preflight。

### Task 0: Create an isolated execution worktree and record a clean baseline

**Files:**
- Create: no repository file
- Test: existing tests/

- [ ] **Step 1: Prepare the execution worktree with the worktree skill**

At implementation time invoke superpowers:using-git-worktrees and create an isolated worktree outside the source tree. Do not edit the main checkout while implementation tasks are running.

- [ ] **Step 2: Record the baseline commands and expected output**

Run from the isolated worktree:

    python3 scripts/validate_suite.py
    python3 -m unittest discover -s tests -p 'test_*.py' -v

Expected: Suite validation passed and 62 existing tests pass. A nonzero baseline is recorded as a pre-existing failure and is fixed before adding new behavior.

Generated logs and environment files stay outside the repository; the first implementation commit contains only the registry/validator changes from Task 1.

### Task 1: Register the new skills and harden the workflow validator

**Files:**
- Modify: scripts/suite_validation.py
- Modify: skills/math-modeling-orchestrator/references/workflow.json
- Modify: tests/test_suite_validation.py
- Modify: tests/test_repository_contract.py
- Create: tests/test_workflow_contract.py

- [ ] **Step 1: Add failing registry and guard tests**

Add tests that assert the new discoverable skills and exact stage registry:

    def test_new_skills_are_discoverable_and_method_library_is_not_a_stage(self):
        self.assertIn("math-modeling-preflight", ALL_SKILLS)
        self.assertIn("math-modeling-visualization", ALL_SKILLS)
        self.assertIn("math-modeling-paper-production", ALL_SKILLS)
        self.assertIn("math-modeling-method-library", ALL_SKILLS)
        workflow = self.load_workflow()
        stage_skills = [item["skill"] for item in workflow["stages"]]
        self.assertNotIn("math-modeling-method-library", stage_skills)
        self.assertEqual(stage_skills[0], "math-modeling-preflight")
        self.assertEqual(stage_skills[-1], "math-modeling-paper-production")

    def test_paper_production_requires_paper_writing_and_visualization_guard_is_explicit(self):
        workflow = self.load_workflow()
        self.assertEqual(
            workflow["transitions"]["paper-writing"], ["paper-production"]
        )
        self.assertEqual(
            workflow["guards"]["visualization-skip"],
            {"allowed": True, "requires_reason": True, "requires_no_figure_claim": True},
        )
        self.assertTrue(workflow["guards"]["paper-production"]["requires_paper_request"])

    def test_failed_validation_cannot_reach_any_paper_stage(self):
        workflow = self.load_workflow()
        failed = workflow["transitions"]["validation-fail"]
        self.assertNotIn("paper-writing", failed)
        self.assertNotIn("paper-production", failed)
        self.assertNotIn("complete", failed)

Run:

    python3 -m unittest tests/test_suite_validation.py tests/test_repository_contract.py tests/test_workflow_contract.py -v

Expected: FAIL because the current constants and workflow contain only the original six stages.

- [ ] **Step 2: Implement the registry as separate discoverable and routed sets**

In scripts/suite_validation.py define these exact constants:

    WORKFLOW_STAGE_SKILLS = (
        "math-modeling-preflight",
        "math-modeling-problem-analysis",
        "math-modeling-data-analysis",
        "math-modeling-model-construction",
        "math-modeling-model-solving",
        "math-modeling-visualization",
        "math-modeling-validation",
        "math-modeling-paper-writing",
        "math-modeling-paper-production",
    )
    SUPPORT_SKILLS = ("math-modeling-method-library",)
    STAGE_SKILLS = WORKFLOW_STAGE_SKILLS
    ALL_SKILLS = (ORCHESTRATOR_SKILL, *WORKFLOW_STAGE_SKILLS, *SUPPORT_SKILLS)

Extend supported stage metadata, guards, and transition constants to require the exact order above. Add visualization-skip and paper-production guards, and reject unknown stage/guard keys. Update _validate_skills so SUPPORT_SKILLS are checked for their own catalog/reference contract instead of being forced to reference the stage handoff. Keep the existing symlink, credential-name, frontmatter, and bundle safety checks unchanged.

- [ ] **Step 3: Update the machine-readable workflow**

Replace workflow.json with schema_version: "2" and these routes:

    {
      "transitions": {
        "preflight": ["problem-analysis"],
        "problem-analysis": ["data-analysis", "model-construction"],
        "data-analysis": ["model-construction"],
        "model-construction": ["model-solving"],
        "model-solving": ["visualization", "validation"],
        "visualization": ["validation"],
        "validation-pass": ["paper-writing", "complete"],
        "validation-fail": ["problem-analysis", "data-analysis", "model-construction", "model-solving"],
        "paper-writing": ["paper-production"],
        "paper-production": ["complete"]
      },
      "guards": {
        "data-analysis-skip": {"allowed": true, "requires_reason": true},
        "visualization-skip": {"allowed": true, "requires_reason": true, "requires_no_figure_claim": true},
        "paper-writing": {"optional": true, "requires_validation_pass": true, "requires_gate3": true, "requires_no_invalidated_inputs": true},
        "paper-production": {"optional": true, "requires_paper_request": true, "requires_paper_writing": true}
      }
    }

The stage entries mark preflight, problem-analysis, model-construction, model-solving, and validation as required; data-analysis, visualization, paper-writing, and paper-production are conditionally optional under their guards. A visualization stage is required whenever a figure claim exists.

- [ ] **Step 4: Update contract tests and run the focused suite**

Update expected lists in tests/test_repository_contract.py, add assertions for the two new handoff paths and the absence of paper routes from validation failure, then run:

    python3 -m unittest tests/test_suite_validation.py tests/test_repository_contract.py tests/test_workflow_contract.py -v

Expected: all focused tests pass.

- [ ] **Step 5: Commit the registry change**

    git add scripts/suite_validation.py skills/math-modeling-orchestrator/references/workflow.json tests/test_suite_validation.py tests/test_repository_contract.py tests/test_workflow_contract.py
    git commit -m "feat: register complete modeling workflow stages"

### Task 2: Add versioned handoff schemas and migration

**Files:**
- Create: skills/math-modeling-orchestrator/references/schemas/handoff.schema.json
- Create: skills/math-modeling-orchestrator/references/schemas/iteration.schema.json
- Create: skills/math-modeling-orchestrator/references/schemas/manifest.schema.json
- Create: skills/math-modeling-orchestrator/references/schemas/gate.schema.json
- Create: scripts/handoff_schema.py
- Create: scripts/validate_handoff.py
- Create: scripts/migrate_handoff.py
- Create: tests/fixtures/handoff-v2.json
- Create: tests/test_handoff_schema.py

- [ ] **Step 1: Write failing schema tests**

Use JSON fixtures created in a temporary directory. Define valid_handoff() by deep-copying tests/fixtures/handoff-v2.json and define invalid variants by changing one field; do not construct a partial object that bypasses the common fixture. The runtime handoff must require all seven semantic objects and reject invented empty strings:

    def test_runtime_handoff_requires_full_objects(self):
        payload = {"schema_version": "2", "task": {}, "state": {}, "result": {}, "next": {}}
        errors = validate_document(payload, kind="handoff", mode="runtime")
        self.assertIn("context", " ".join(errors))
        self.assertIn("quality", " ".join(errors))

    def test_needs_revision_requires_failed_checks_and_no_forward_authorization(self):
        payload = valid_handoff()
        payload["state"]["status"] = "needs_revision"
        payload["next"]["recommended_stage"] = "paper-writing"
        payload["next"]["failed_checks"] = []
        errors = validate_document(payload, kind="handoff", mode="runtime")
        self.assertTrue(any("failed_checks" in error for error in errors))
        self.assertTrue(any("paper-writing" in error for error in errors))

    def test_v1_minimal_handoff_migrates_without_losing_task_text(self):
        legacy = {"schema_version": "1", "task": {"statement": "保留这段题面"}, "state": {"current_stage": "model-solving"}, "result": {}, "next": {}}
        migrated = migrate_payload(legacy)
        self.assertEqual(migrated["schema_version"], "2")
        self.assertEqual(migrated["task"]["statement"], "保留这段题面")
        self.assertEqual(migrated["state"]["current_stage"], "model-solving")
        self.assertEqual(migrated["context"]["assumptions"], [])

Run:

    python3 -m unittest tests/test_handoff_schema.py -v

Expected: FAIL because the schema and migration modules do not exist.

- [ ] **Step 2: Define the complete v2 handoff schema**

handoff.schema.json must use additionalProperties: false at the top level, require schema_version, task, state, context, artifacts, quality, result, and next, and constrain:

    {
      "schema_version": "2",
      "state": {
        "current_stage": "preflight|problem-analysis|data-analysis|model-construction|model-solving|visualization|validation|paper-writing|paper-production",
        "status": "pending|in_progress|complete|needs_revision|skipped",
        "validation_status": "pending|pass|needs_revision|stale",
        "completed_stages": ["string"],
        "invalidated_stages": ["string"]
      },
      "quality": {"checks": [], "warnings": [], "confidence": "high|medium|low", "limitations": []},
      "next": {"recommended_stage": "string|null", "rationale": "non-empty string", "alternatives": [], "failed_checks": []}
    }

context contains arrays for assumptions, variables, data, methods, decisions, equations, and parameters; artifacts requires relative path, kind, and description. All paths reject absolute components and parent traversal.

- [ ] **Step 3: Implement standard-library validation and migration**

Implement these functions in scripts/handoff_schema.py:

    def validate_document(payload: object, *, kind: str, mode: str = "runtime") -> list[str]:
        """Return deterministic field-path errors for one v2 document."""

    def migrate_payload(payload: dict[str, object]) -> dict[str, object]:
        """Return a v2 payload while preserving all recognized v1 evidence."""

    def load_and_validate(path: Path, *, kind: str, mode: str = "runtime") -> dict[str, object]:
        """Load JSON, validate it, and raise ValueError on an invalid document."""

The validator reports deterministic field paths such as state.validation_status; it never coerces strings, fills measurements, or silently accepts a legacy payload in runtime mode. migrate_payload copies known v1 values, adds empty arrays for inapplicable collections, records context.decisions with the migration source, and sets state.validation_status to stale if the legacy handoff claimed a pass without hashes.

validate_handoff.py accepts --input, --mode runtime|legacy, and --json; a nonempty error list exits 1. migrate_handoff.py accepts --input, --output, and --pretty, writes atomically, and refuses to overwrite an existing output.

- [ ] **Step 4: Add schema fixtures and run the focused tests**

Run:

    python3 -m unittest tests/test_handoff_schema.py -v
    python3 scripts/validate_handoff.py --input tests/fixtures/handoff-v2.json

Expected: all tests pass and the CLI prints handoff valid for the checked-in valid fixture.

- [ ] **Step 5: Commit the schema contract**

    git add skills/math-modeling-orchestrator/references/schemas scripts/handoff_schema.py scripts/validate_handoff.py scripts/migrate_handoff.py tests/test_handoff_schema.py tests/fixtures/handoff-v2.json
    git commit -m "feat: add versioned modeling handoff schemas"

### Task 3: Implement project state, immutable iterations, manifests, gates, and stale propagation

**Files:**
- Create: scripts/manifest.py
- Create: scripts/project_state.py
- Create: tests/test_project_state.py
- Create: tests/test_manifest.py

- [ ] **Step 1: Write failing state and hash tests**

Cover initialization, version numbering, per-question pointers, gate records, and stale propagation. In setUp create self.temp_path, self.input_dir with problem.txt and data.csv, and self.project by calling init_project with the explicit resolved test interpreter:

    def test_init_requires_absolute_python_and_creates_v001(self):
        project = self.temp_path / "project"
        state = init_project(project, python_executable=Path(sys.executable), input_dir=self.input_dir, template_path=None)
        self.assertEqual(state["active_iteration"], "v001")
        self.assertTrue((project / "iterations/v001/manifests/input_manifest.json").is_file())

    def test_new_iteration_never_overwrites_parent_and_preserves_unaffected_question(self):
        create_iteration(project, reason="revise Q2", affected_questions=["Q2"])
        current = load_current(project)
        self.assertEqual(current["question_sources"]["Q1"], "v001")
        self.assertEqual(current["question_sources"]["Q2"], "v002")
        self.assertTrue((project / "iterations/v001").is_dir())
        self.assertTrue((project / "iterations/v002").is_dir())

    def test_input_hash_change_marks_dependent_run_figure_validation_and_paper_stale(self):
        mark_stale(project, changed_paths=["input/data.csv"], question_ids=["Q2"])
        report = json.loads((project / "qa/staleness.json").read_text())
        self.assertEqual(report["status"], "stale")
        self.assertEqual(set(report["invalidated"]["Q2"]), {"run", "figure", "validation", "paper"})

Run:

    python3 -m unittest tests/test_project_state.py tests/test_manifest.py -v

Expected: FAIL because no runtime state implementation exists.

- [ ] **Step 2: Implement deterministic manifest primitives**

In scripts/manifest.py implement:

    def sha256_file(path: Path) -> str:
        """Hash one regular file in streaming chunks."""

    def sha256_paths(root: Path, relative_paths: Iterable[Path]) -> dict[str, str]:
        """Return sorted relative-path to SHA-256 mappings."""

    def atomic_write_json(path: Path, payload: object) -> None:
        """Write canonical UTF-8 JSON through a same-directory temporary file."""

    def utc_now() -> str:
        """Return an ISO-8601 UTC timestamp with a Z suffix."""

    def relative_regular_files(root: Path) -> Sequence[Path]:
        """Enumerate regular non-symlink files below root in lexical order."""

Reject symlink components, special files, absolute artifact paths, and paths outside the project root. JSON is UTF-8, sorted keys, two-space indentation, and a trailing newline. The input manifest records relative path, byte size, UTC modification time, SHA-256, source label, and read_only: true; it never changes input permissions.

- [ ] **Step 3: Implement project initialization and version operations**

project_state.py exposes:

    def init_project(project_root: Path, *, python_executable: Path, input_dir: Path, template_path: Path | None, competition: str = "CUMCM") -> dict[str, object]:
        """Create a new project and return its canonical current.json payload."""

    def load_current(project_root: Path) -> dict[str, object]:
        """Load and validate the current pointer."""

    def create_iteration(project_root: Path, *, reason: str, affected_questions: Sequence[str]) -> str:
        """Create and return the next immutable vNNN directory name."""

    def record_gate(project_root: Path, *, gate_id: str, status: str, confirmer: str, artifact_hashes: Sequence[str], note: str) -> dict[str, object]:
        """Append one auditable gate record and return the updated gate report."""

    def mark_stale(project_root: Path, *, changed_paths: Sequence[str], question_ids: Sequence[str]) -> dict[str, object]:
        """Propagate stale status to dependent artifacts without deleting evidence."""

init_project requires an existing absolute executable Python file and creates only an empty project layout plus v001; it writes current.json with schema_version, project_id, active_iteration, question_sources, gates, status, and updated_at. create_iteration uses the next zero-padded integer, copies evidence with copytree(source, destination, symlinks=False) only after path checks, writes an iteration manifest, and refuses an existing target. record_gate rejects unknown gate ids/statuses and stores UTC time, hashes, confirmer, note, and schema version. mark_stale updates machine and human reports without deleting old artifacts.

- [ ] **Step 4: Add command-line entry points and test failure modes**

The CLI subcommands are exactly init, new-iteration, gate, and stale; all accept absolute paths and print the resulting JSON path. Add tests for relative Python paths, missing input directories, output collisions, unknown gate ids, and attempts to write through a symlink.

Run:

    python3 -m unittest tests/test_project_state.py tests/test_manifest.py -v

Expected: all state and safety tests pass.

- [ ] **Step 5: Commit the runtime state layer**

    git add scripts/manifest.py scripts/project_state.py tests/test_project_state.py tests/test_manifest.py
    git commit -m "feat: add immutable modeling project state"

### Task 4: Add preflight diagnostics and the reproducible Python runner

**Files:**
- Create: scripts/preflight.py
- Create: scripts/python_runner.py
- Create: skills/math-modeling-preflight/SKILL.md
- Create: skills/math-modeling-preflight/agents/openai.yaml
- Create: tests/test_preflight.py
- Create: tests/test_python_runner.py

- [ ] **Step 1: Write failing environment and runner tests**

Use Path(sys.executable).resolve() as the explicitly supplied test interpreter; never hide it in the fixture. Define RunFailed in scripts/python_runner.py and import it in the test. Assert missing packages produce install advice but do not invoke pip:

    def test_preflight_reports_missing_package_with_exact_interpreter_command(self):
        report = diagnose_environment(
            project_root=self.project,
            python_executable=Path(sys.executable).resolve(),
            required_packages=["package_that_cannot_be_present_in_fixture"],
            template_path=None,
        )
        self.assertEqual(report["python"]["status"], "pass")
        self.assertEqual(report["packages"][0]["status"], "missing")
        self.assertIn(f"{Path(sys.executable).resolve()} -m pip install", report["packages"][0]["install_command"])

    def test_runner_captures_command_exit_code_logs_and_output_hash(self):
        result = run_python(Path(sys.executable).resolve(), self.script, cwd=self.project, output_dir=self.project / "results", input_paths=[self.input_file], seed=7, timeout_seconds=30)
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue((self.project / "results/stdout.log").is_file())
        self.assertTrue((self.project / "results/run_manifest.json").is_file())
        self.assertEqual(result["seed"], 7)

    def test_runner_rejects_nonzero_script_and_never_uses_shell(self):
        with self.assertRaises(RunFailed):
            run_python(Path(sys.executable).resolve(), self.failing_script, cwd=self.project, output_dir=self.project / "failed", input_paths=[], seed=0, timeout_seconds=30)

Run the focused tests and expect import failures.

- [ ] **Step 2: Implement Python and package diagnostics**

diagnose_environment must reject a relative or non-regular interpreter, run [python, "-c", "import sys; print(sys.executable); print(sys.version)"], and inspect each package with [python, "-c", "import importlib.metadata as m; print(m.version(NAME))"]. The report includes interpreter path, resolved path, version, platform, package status/version, and an install command using that exact path. It never calls pip, chooses another interpreter, or downgrades a package.

Check tools in this order: tectonic, latexmk, xelatex, pdflatex; record executable path/version or missing. A missing LaTeX tool is a warning for result-only work and a blocking error for paper production. A missing user template selects the explicit fallback status, not an error at preflight.

- [ ] **Step 3: Implement the subprocess runner**

run_python accepts an explicit cli_mode value of json_io or plain. In json_io mode it builds [python, script, "--input", input_path, "--output", output_path, "--seed", seed]; in plain mode it runs [python, script]. Both modes use a controlled environment containing PYTHONHASHSEED and MPLBACKEND=Agg. It sets a timeout, captures UTF-8 stdout/stderr, writes stdout.log, stderr.log, command.json, and run_manifest.json, computes code/input/output hashes, and raises RunFailed on timeout or nonzero exit. It does not alter the model specification or convert a failed run to success.

- [ ] **Step 4: Write the preflight Skill contract**

math-modeling-preflight/SKILL.md must require the user’s absolute Python path before any model work, ask for project root/template path/competition, describe package and LaTeX diagnostics, explain confirmation before installation, and return a v2 handoff with preflight artifacts. agents/openai.yaml must mention $math-modeling-preflight and retain allow_implicit_invocation: true.

- [ ] **Step 5: Run and commit**

    python3 -m unittest tests/test_preflight.py tests/test_python_runner.py -v
    git add scripts/preflight.py scripts/python_runner.py skills/math-modeling-preflight tests/test_preflight.py tests/test_python_runner.py
    git commit -m "feat: add environment preflight and Python runner"

Expected: focused tests pass; no pip or external installation command is observed.

### Task 5: Build the ten-family method library with executable templates

**Files:**
- Create: skills/math-modeling-method-library/SKILL.md
- Create: skills/math-modeling-method-library/agents/openai.yaml
- Create: skills/math-modeling-method-library/references/catalog.json
- Create: skills/math-modeling-method-library/references/methods/*.md (30 entries)
- Create: skills/math-modeling-method-library/assets/templates/*.py (30 templates)
- Create: skills/math-modeling-method-library/assets/fixtures/method-smoke.json
- Create: scripts/method_catalog.py
- Create: tests/test_method_library.py

- [ ] **Step 1: Define the catalog contract and failing completeness tests**

catalog.json entries require id, family, name_zh, trigger_conditions, assumptions, inputs, formula, scale_limit, template, dependencies, failure_signals, validation, figure_roles, paper_notes, and license_notes. Define EXPECTED_FAMILIES as the ten Chinese family ids used by catalog.json. Add tests:

    def test_catalog_contains_exactly_three_templates_per_family(self):
        catalog = load_catalog()
        self.assertEqual(len(catalog), 30)
        counts = Counter(item["family"] for item in catalog)
        self.assertEqual(set(counts), set(EXPECTED_FAMILIES))
        self.assertTrue(all(counts[family] == 3 for family in EXPECTED_FAMILIES))

    def test_every_entry_has_a_safe_executable_template_and_no_unlicensed_copy(self):
        for item in load_catalog():
            template = ROOT / "skills/math-modeling-method-library/assets/templates" / item["template"]
            self.assertTrue(template.is_file())
            self.assertIn("def solve(", template.read_text(encoding="utf-8"))
            self.assertIn("license_notes", item)
        self.assertNotIn("T" + "ODO", template.read_text(encoding="utf-8"))

- [ ] **Step 2: Add the 30 method definitions**

Use exactly these three entries in each family, with Chinese explanation and an English id:

| 方法族 | 三个方法 |
| --- | --- |
| 优化与决策 | linear-programming, mixed-integer-programming, nonlinear-constrained-optimization |
| 预测、回归与时间序列 | ols-ridge-regression, exponential-smoothing, arima-forecasting |
| 综合评价与多指标决策 | entropy-topsis, ahp-weighted-score, dea-efficiency |
| 统计分析与数据处理 | bootstrap-confidence, hypothesis-test, robust-outlier-detection |
| 机器学习、分类、聚类与降维 | random-forest-classification, kmeans-clustering, pca-reduction |
| 图论与网络 | shortest-path, max-flow-min-cut, pagerank-centrality |
| 机理模型与数值分析 | ode-integration, nonlinear-least-squares, finite-difference-heat |
| 随机模拟与不确定性 | monte-carlo-propagation, latin-hypercube-sampling, markov-chain-simulation |
| 博弈与多主体决策 | normal-form-nash, evolutionary-replicator, best-response-dynamics |
| 几何、空间与信号 | linear-interpolation, convex-hull-geometry, fft-denoising |

Every entry must state applicability, assumptions, units, formula, complexity/scale boundary, parameter meanings, failure signals, validation, suggested figures, and paper wording. Sources from public GitHub projects are recorded as inspiration only; include source URL and license status in license_notes and write original templates under MIT repository terms.

- [ ] **Step 3: Implement the common template interface**

Every assets/templates/*.py file must expose this exact interface and deterministic JSON output:

    from __future__ import annotations
    import argparse
    import json
    from pathlib import Path
    from typing import Any

    def solve(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Return method-specific values plus metrics and assumptions."""
        values = [float(value) for value in data["values"]]
        return {"values": values, "metrics": {"count": len(values)}, "assumptions": []}

    def main() -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--input", required=True)
        parser.add_argument("--output", required=True)
        parser.add_argument("--seed", type=int, default=0)
        args = parser.parse_args()
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = solve(data, {"seed": args.seed})
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

The shown body is the executable interface smoke implementation; each of the 30 files replaces its values calculation with the named method’s concrete formula while preserving the same JSON contract. The main function reads UTF-8 JSON from --input, writes UTF-8 JSON to --output, accepts --seed, and converts numerical arrays to JSON-safe lists. Templates use only declared baseline dependencies; a method that needs an optional package returns a clear dependency error rather than silently substituting another method. The 30 smoke fixtures contain small deterministic values and are labeled test data.

- [ ] **Step 4: Implement catalog validation and smoke execution**

method_catalog.py exposes load_catalog, validate_catalog, and run_smoke. It rejects duplicate ids, unknown families, missing fields, unsafe template paths, undeclared dependencies, and nonzero template exits. run_smoke invokes the user-supplied interpreter through python_runner.py; it never runs templates with system Python implicitly.

- [ ] **Step 5: Run tests and commit the method library**

    python3 -m unittest tests/test_method_library.py -v
    python3 scripts/method_catalog.py --root . --check
    git add skills/math-modeling-method-library scripts/method_catalog.py tests/test_method_library.py
    git commit -m "feat: add ten-family modeling method library"

Expected: 30 catalog entries, three per family, all static checks pass; smoke execution is run separately with an explicit interpreter.
### Task 6: Implement publication-quality visualization and figure evidence QA

**Files:**
- Create: skills/math-modeling-visualization/SKILL.md
- Create: skills/math-modeling-visualization/agents/openai.yaml
- Create: skills/math-modeling-visualization/references/chart-selection.md
- Create: skills/math-modeling-visualization/references/figure-roles.md
- Create: skills/math-modeling-visualization/references/visual-style.md
- Create: skills/math-modeling-visualization/references/render-qa.md
- Create: skills/math-modeling-visualization/assets/styles/modeling.mplstyle
- Create: scripts/figure_qa.py
- Create: scripts/export_figure.py
- Create: scripts/visual_qa.py
- Create: tests/test_figure_qa.py

- [ ] **Step 1: Write failing figure contract tests**

In setUp create a project root, one source JSON file, valid PDF/SVG fixtures, and local builders make_manifest(role="evidence", claim_type="data"), make_png_manifest(dpi), and manifest_without_claim. The builders calculate the source hash with scripts/manifest.py so each failure changes exactly one contract field.

    def test_manifest_requires_claim_source_hash_role_and_outputs(self):
        errors = validate_figure_manifest(self.manifest_without_claim)
        self.assertTrue(any("claim_id" in error for error in errors))

    def test_stale_source_hash_blocks_verified_status(self):
        manifest = make_manifest()
        self.source.write_text("changed", encoding="utf-8")
        errors = validate_figure_manifest(manifest, project_root=self.project)
        self.assertTrue(any("stale" in error for error in errors))

    def test_png_requires_dimensions_and_at_least_300_dpi(self):
        manifest = make_png_manifest(dpi=150)
        errors = validate_figure_manifest(manifest, project_root=self.project)
        self.assertTrue(any("DPI" in error for error in errors))

    def test_conceptual_figure_cannot_support_evidence_claim(self):
        manifest = make_manifest(role="conceptual", claim_type="data")
        errors = validate_figure_manifest(manifest, project_root=self.project)
        self.assertTrue(any("示意图" in error or "conceptual" in error for error in errors))

- [ ] **Step 2: Implement source-hash and file-format checks**

figure_qa.py exposes:

    FIGURE_ROLES = ("evidence", "validation", "diagnostic", "conceptual")
    def validate_figure_manifest(manifest: dict[str, object], *, project_root: Path) -> list[str]:
        """Return deterministic figure-manifest and source-freshness errors."""

    def refresh_figure_status(manifest_path: Path, *, project_root: Path) -> dict[str, object]:
        """Recompute source hashes and persist verified/stale status."""

Require relative source/output paths, existing regular files, matching SHA-256 for every source, a nonempty claim_id except for explicitly labeled exploratory drafts, axis/units/legend metadata, and status: verified only after all checks pass. Parse PNG dimensions and pHYs DPI from the file header without Pillow; accept PDF/SVG only when their signatures and nonzero sizes are valid. PDF/SVG is preferred; PNG requires both dpi_x and dpi_y at least 300.

- [ ] **Step 3: Add the shared style and export helper**

modeling.mplstyle fixes a Unicode-capable font fallback list, line widths, marker sizes, color-blind-safe palette, white background, outward ticks, and savefig.dpi: 300. export_figure.py applies the style, accepts a source result path and a figure manifest path, writes PDF plus PNG (or SVG), and refuses to draw when the source hash in the manifest is stale. It never creates unregistered random data.

- [ ] **Step 4: Implement render QA and write the visualization Skill**

visual_qa.py checks output dimensions at the requested paper width, invokes pdftoppm when available, and reports missing tools as needs_review rather than pretending that a visual inspection passed. The Skill describes C-A正文图 and C-B诊断图, chart-selection rules, units/precision, grayscale and color-blind checks, figure-caption/claim/reference closure, and the condition for an explicit no-figure skip.

- [ ] **Step 5: Run tests and commit**

    python3 -m unittest tests/test_figure_qa.py -v
    git add skills/math-modeling-visualization scripts/figure_qa.py scripts/export_figure.py scripts/visual_qa.py tests/test_figure_qa.py
    git commit -m "feat: add evidence-traceable scientific figures"

Expected: stale source, low DPI, missing labels, conceptual misuse, and malformed output all fail closed.

### Task 7: Strengthen per-question results and validation evidence

**Files:**
- Create: scripts/result_contract.py
- Create: tests/test_result_contract.py
- Modify: skills/math-modeling-model-solving/SKILL.md
- Modify: skills/math-modeling-validation/SKILL.md
- Modify: skills/math-modeling-model-construction/SKILL.md

- [ ] **Step 1: Write failing result-contract tests**

Define valid_result() with Q1, a named model, a baseline metric, finite metric values with units and source hashes, a run manifest, one validation cycle, one claim, and freeze_status="draft"; each test mutates only the field under test.

    def test_result_requires_question_model_baseline_metrics_and_seed(self):
        errors = validate_result_payload({"question_id": "Q1"})
        for field in ("model_id", "baseline", "metrics", "run_manifest", "validation_plan"):
            self.assertTrue(any(field in error for error in errors))

    def test_validation_threshold_change_is_recorded_as_new_cycle(self):
        payload = valid_result()
        payload["validation_plan"]["threshold"] = 0.99
        payload["validation_history"] = [{"threshold": 0.90, "status": "fail"}]
        errors = validate_result_payload(payload)
        self.assertTrue(any("threshold" in error for error in errors))

    def test_nan_or_unverified_number_cannot_be_frozen(self):
        payload = valid_result()
        payload["metrics"]["score"] = "NaN"
        payload["freeze_status"] = "confirmed"
        errors = validate_result_payload(payload)
        self.assertTrue(any("finite" in error or "freeze" in error for error in errors))

- [ ] **Step 2: Implement result and claim validation**

result_contract.py requires question_id, model_id, assumptions, baseline, parameters, metrics, units, run_manifest, validation_plan, claims, and freeze_status. Each metric carries value, unit, source path, source hash, and finite numeric status. Each validation plan carries threshold, split/scope, seed, and method; changing a threshold requires a new validation_cycle_id and preserves the previous outcome. A result cannot be frozen while its run, figure, or validation manifest is stale.

- [ ] **Step 3: Update model-solving and validation Skill instructions**

Require one result contract per Qn, explicit baseline and acceptance thresholds before execution, fixed seed, structured JSON/CSV output, and evidence-backed rollback. Add Gate 2 and Gate 3 handoff fields without allowing either Skill to mark the whole project complete.

- [ ] **Step 4: Run tests and commit**

    python3 -m unittest tests/test_result_contract.py -v
    git add scripts/result_contract.py tests/test_result_contract.py skills/math-modeling-model-solving/SKILL.md skills/math-modeling-validation/SKILL.md skills/math-modeling-model-construction/SKILL.md
    git commit -m "feat: enforce per-question result evidence"

### Task 8: Add Chinese paper content contract and paper-writing rules

**Files:**
- Create: skills/math-modeling-paper-production/references/paper-content.schema.json
- Create: scripts/paper_content.py
- Create: tests/test_paper_content.py
- Modify: skills/math-modeling-paper-writing/SKILL.md

- [ ] **Step 1: Write failing content and abstract tests**

Define valid_content(question_count) with one frozen result claim per question, the required section map, a three-column symbol row, and empty-but-explicit reference/code/AI review arrays. Set self.evidence to a temporary evidence tree containing the matching result manifest.

    def test_abstract_requires_two_sentence_intro_and_one_paragraph_per_question(self):
        content = valid_content(question_count=2)
        content["abstract"]["intro"] = "只写了一句。"
        errors = validate_paper_content(content)
        self.assertTrue(any("两句" in error or "intro" in error for error in errors))
        content["abstract"]["question_paragraphs"] = [content["abstract"]["question_paragraphs"][0]]
        errors = validate_paper_content(content)
        self.assertTrue(any("Q2" in error for error in errors))

    def test_symbol_table_has_symbol_description_and_unit(self):
        content = valid_content(question_count=1)
        content["symbols"][0].pop("unit")
        self.assertTrue(any("unit" in error for error in validate_paper_content(content)))

    def test_claim_must_resolve_to_frozen_result_hash(self):
        content = valid_content(question_count=1)
        content["claims"][0]["source_hash"] = "wrong"
        self.assertTrue(any("hash" in error for error in validate_paper_content(content, evidence_root=self.evidence)))

- [ ] **Step 2: Define the paper-content schema**

The schema requires language: zh-CN, abstract.intro_sentences with exactly two sentences (background/existence, then work completed), one question_paragraph per detected question, keywords, sections 1 through 8, a three-column symbols array (symbol, description, unit), figure/table references, references, code appendix, AI-use disclosure, and human review records. Numerical claims must carry result path and SHA-256. English abstract fields are rejected unless the template/competition manifest explicitly requests them.

- [ ] **Step 3: Implement content consistency checks**

paper_content.py exposes validate_paper_content, question_ids, referenced_figures, referenced_tables, and freeze_content. It checks the requested 5.1.1/5.1.2 style headings, every question’s modeling and calculation subsection, \\textbf{} use only in abstract/important claims, no unsupported numbers, and figure/table references that resolve to verified manifests. It does not invent prose or numerical values.

- [ ] **Step 4: Update the paper-writing Skill**

Document the exact Chinese structure: 摘要、关键词、1 问题背景与重述（1.1/1.2）、2 问题分析、3 模型假设、4 符号说明、5 模型的建立与求解（按问分 5.x.1 建模和 5.x.2 计算）、6 模型检验、7 模型评价与推广/改进、8 结论、附录 A–D。 State that Gate 3 and current validation are prerequisites, fallback templates are non-submission, and the writer must report evidence gaps instead of filling them.

- [ ] **Step 5: Run tests and commit**

    python3 -m unittest tests/test_paper_content.py -v
    git add skills/math-modeling-paper-production/references/paper-content.schema.json scripts/paper_content.py tests/test_paper_content.py skills/math-modeling-paper-writing/SKILL.md
    git commit -m "feat: enforce Chinese modeling paper content contract"

### Task 9: Implement LaTeX template selection, production, compilation, and page gates

**Files:**
- Create: skills/math-modeling-paper-production/SKILL.md
- Create: skills/math-modeling-paper-production/agents/openai.yaml
- Create: skills/math-modeling-paper-production/assets/fallback-zh/main.tex
- Create: skills/math-modeling-paper-production/assets/fallback-zh/refs.bib
- Create: skills/math-modeling-paper-production/assets/fallback-zh/README.md
- Create: scripts/latex_qa.py
- Create: scripts/paper_production.py
- Create: tests/test_latex_qa.py
- Create: tests/test_paper_production.py

- [ ] **Step 1: Write failing template and page-gate tests**

In setUp create self.user_template and self.fallback as regular temporary directories; the fake compiler writes a minimal valid PDF on success and exits 9 with stderr on failure.

    def test_user_template_wins_and_is_hashed(self):
        report = select_template(user_template=self.user_template, fallback_dir=self.fallback)
        self.assertEqual(report["template_status"], "user_provided")
        self.assertEqual(report["source"], str(self.user_template.resolve()))
        self.assertRegex(report["sha256"], r"^[0-9a-f]{64}$")

    def test_missing_template_is_compilable_fallback_but_not_submission_ready(self):
        report = select_template(user_template=None, fallback_dir=self.fallback)
        self.assertEqual(report["template_status"], "fallback_non_submission")
        self.assertFalse(report["submission_ready_eligible"])

    def test_total_pages_over_30_fails_closed_and_body_range_is_recorded(self):
        qa = evaluate_page_gate(total_pages=31, body_pages=26, body_start=2, body_end=27)
        self.assertEqual(qa["status"], "fail")
        self.assertIn("30", qa["failed_checks"])

    def test_body_below_target_is_warning_not_filled_with_blank_pages(self):
        qa = evaluate_page_gate(total_pages=20, body_pages=18, body_start=2, body_end=19)
        self.assertEqual(qa["status"], "needs_revision")
        self.assertNotIn("blank", " ".join(qa["actions"]).lower())

- [ ] **Step 2: Create the Chinese fallback template**

Use ctexart with explicit UTF-8, geometry, caption, booktabs, amsmath, hyperref, and a neutral color palette. Put % BODY_START immediately before section 1 and % BODY_END immediately after section 8 so the QA script can define正文页范围. Include visible labels for fallback/non-official status and the required appendix headings. The fallback README states that it is a compile smoke template and cannot be submitted as an official contest template.

- [ ] **Step 3: Implement template selection and manifest creation**

select_template(user_template: Path | None, fallback_dir: Path, official_template: Path | None = None) applies the fixed priority user > explicitly specified official > locally verified official > fallback. It copies files into the current iteration’s paper/template/, rejects symlinked or out-of-root files, records source URL/license/verification date when supplied, computes a tree hash, records engine and main entry, and sets template_status exactly as locked in the conventions.

- [ ] **Step 4: Implement LaTeX compilation and PDF QA**

paper_production.py exposes produce_paper(project_root, iteration, content_path, environment_manifest_path, template_path=None, compiler=None). It assembles content only after Gate 3 and current validation, invokes the detected compiler without a shell (Tectonic first, otherwise latexmk/xelatex), captures logs, writes paper_manifest.json, and leaves failed output for audit. latex_qa.py counts pages using pdfinfo when available and a conservative PDF page-object fallback, checks section markers, unresolved references, empty/broken page output, body range markers, and total/body thresholds. It never pads, hides, or deletes pages to meet limits.

- [ ] **Step 5: Run tests and commit**

    python3 -m unittest tests/test_latex_qa.py tests/test_paper_production.py -v
    git add skills/math-modeling-paper-production scripts/latex_qa.py scripts/paper_production.py tests/test_latex_qa.py tests/test_paper_production.py
    git commit -m "feat: add Chinese LaTeX paper production gates"

The tests use a fake compiler executable in a temporary directory for deterministic compilation behavior and separately skip the real TeX smoke test when no compiler is installed.
### Task 10: Add CUMCM competition pack and orchestrator routing/gates

**Files:**
- Create: skills/math-modeling-orchestrator/references/competition-packs/cumcm.json
- Modify: skills/math-modeling-orchestrator/SKILL.md
- Modify: skills/math-modeling-orchestrator/references/handoff-contract.md
- Modify: skills/math-modeling-problem-analysis/SKILL.md
- Modify: skills/math-modeling-data-analysis/SKILL.md
- Modify: skills/math-modeling-orchestrator/agents/openai.yaml
- Create: tests/test_orchestrator_contract.py

- [ ] **Step 1: Write failing routing and gate tests**

    def test_new_problem_must_enter_preflight_before_problem_analysis(self):
        text = ORCHESTRATOR.read_text(encoding="utf-8")
        self.assertIn("$math-modeling-preflight", text)
        self.assertIn("before invoking problem analysis", text)

    def test_gate3_is_required_before_paper_writing(self):
        text = ORCHESTRATOR.read_text(encoding="utf-8")
        self.assertIn("Gate 3", text)
        self.assertIn("paper-production", text)
        self.assertIn("confirmed", text)

    def test_external_data_requires_usage_fields_license_and_user_confirmation(self):
        text = DATA_ANALYSIS.read_text(encoding="utf-8")
        for phrase in ("用途", "字段", "许可证", "用户确认"):
            self.assertIn(phrase, text)

- [ ] **Step 2: Add a non-factual CUMCM pack**

cumcm.json declares competition: "CUMCM", language: "zh-CN", requires_official_verification: true, the three gate ids, paper page defaults, and an empty official_sources array. It does not assert a current year’s rules, submission URL, or license. The preflight report requires a user-provided or read-only verified official source before a final submission claim.

- [ ] **Step 3: Update orchestrator routing instructions**

The orchestrator must read workflow, load/migrate v2 handoff, invoke preflight first, require the exact three gate records, route visualization based on figure claims, route paper-writing only after validation pass and Gate 3, and route paper-production only after paper content is complete. It must preserve per-question source versions and mark downstream artifacts stale before rerouting. It must explicitly pause for missing Python path, model-changing ambiguity, unapproved external data, template conflict, or page-gate failure.

- [ ] **Step 4: Update the shared handoff contract and data stage**

Document v2 fields, gate artifacts, current/stale semantics, recommended_stage as a recommendation rather than permission, and no-forward routing on needs_revision. Add the external-data approval record shape (purpose, fields, source, license, risk, user_confirmation) and require it before any download.

- [ ] **Step 5: Run tests and commit**

    python3 -m unittest tests/test_orchestrator_contract.py tests/test_repository_contract.py -v
    git add skills/math-modeling-orchestrator skills/math-modeling-problem-analysis/SKILL.md skills/math-modeling-data-analysis/SKILL.md tests/test_orchestrator_contract.py
    git commit -m "feat: route gates and CUMCM compliance checks"

### Task 11: Build the offline end-to-end CUMCM-style fixture

**Files:**
- Create: tests/fixtures/cumcm-mini/input/problem.txt
- Create: tests/fixtures/cumcm-mini/input/data.csv
- Create: tests/fixtures/cumcm-mini/template/main.tex
- Create: tests/fixtures/cumcm-mini/template/refs.bib
- Create: tests/fixtures/cumcm-mini/scripts/q1.py
- Create: tests/fixtures/cumcm-mini/scripts/q2.py
- Create: tests/test_end_to_end_fixture.py

- [ ] **Step 1: Create deterministic Chinese fixture inputs**

Use a short, original CUMCM-style prompt with two questions (one descriptive regression question and one constrained allocation question) and a small CSV whose columns, units, and provenance are stated in problem.txt. Mark the fixture as test data in every manifest. The scripts read the copied input path, set a seed, write finite JSON metrics with units, and intentionally contain no network or model API calls.

- [ ] **Step 2: Write the failing end-to-end assertions**

The test must call init_project(project, python_executable=Path(sys.executable).resolve(), input_dir=input_dir, template_path=None) explicitly and define the local helpers gate_status, cannot_route, figure_status, validation_status, paper_content_status, and paper_manifest by reading the public JSON artifacts. It then asserts this sequence:

    assert gate_status(project, "gate1") == "pending"
    assert cannot_route(project, "model-construction")
    record_gate(project, gate_id="gate1", status="confirmed", confirmer="tester", artifact_hashes=[], note="fixture review")
    record_gate(project, gate_id="gate2", status="confirmed", confirmer="tester", artifact_hashes=[], note="fixture review")
    run_q1_and_q2(project)
    assert figure_status(project, "q1-fit") == "verified"
    assert validation_status(project) == "pass"
    record_gate(project, gate_id="gate3", status="confirmed", confirmer="tester", artifact_hashes=[], note="fixture review")
    assert paper_content_status(project) == "complete"
    assert paper_manifest(project)["template_status"] == "fallback_non_submission"
    assert paper_manifest(project)["submission_ready"] is False

Also assert that changing Q2 creates v002 while current.json["question_sources"]["Q1"] == "v001", changing input/data.csv marks Q2 run/figure/validation/paper stale, a failed validation cannot call paper production, and a fake compiler failure leaves logs and a non-ready status.

- [ ] **Step 3: Implement only the fixture adapters needed by the test**

Use the public functions from Tasks 3–9; do not add fixture-specific shortcuts to production modules. Where the fallback template cannot be compiled on the host, use the fake compiler from tests/helpers/fake_compiler.py and retain a separate real-compiler smoke test guarded by tool detection.

- [ ] **Step 4: Run the end-to-end test and commit**

    python3 -m unittest tests/test_end_to_end_fixture.py -v
    git add tests/fixtures/cumcm-mini tests/test_end_to_end_fixture.py
    git commit -m "test: add offline complete modeling workflow fixture"

Expected: the fixture proves gate blocking, Python execution, real-result figure provenance, validation rollback, mixed iterations, stale propagation, Chinese paper structure, and fallback non-submission status.

### Task 12: Update repository metadata, documentation, and safe distribution checks

**Files:**
- Modify: .codex-plugin/plugin.json
- Modify: README.md
- Modify: docs/architecture.md
- Create: docs/development.md
- Create: CHANGELOG.md
- Modify: tests/test_bundle.py
- Modify: tests/test_repository_contract.py

- [ ] **Step 1: Add failing documentation/metadata assertions**

Assert the manifest description mentions Python, LaTeX, and staged verification; README includes --python, preflight, v001, figure QA, fallback status, and the update paths for drawing guidance/templates; architecture lists all nine routed stages and the read-only method library.

- [ ] **Step 2: Update plugin metadata without introducing unsupported declarations**

Bump the semantic version to 0.2.0, retain skills: "./skills/", update interface descriptions and the default orchestrator prompt, and do not add hooks, apps, MCP servers, credentials, or user-project paths to the manifest.

- [ ] **Step 3: Write the maintainer update guide**

docs/development.md gives exact workflows for adding a drawing rule, paper template, or algorithm method: create a behavior fixture, add the resource under the owning Skill, record source/license/version/hash, update schema/workflow/validator/tests/docs, build and validate a bundle, and run the offline plus a real supplied-project smoke test. It explains when a schema version or competition pack version must change and how to keep old templates/iterations immutable.

- [ ] **Step 4: Extend bundle tests and run source validation**

Ensure new assets are regular files, fixture/user state is not bundled, fallback templates contain no credentials, and the builder still rejects symlinks, special files, environment files, and private-key suffixes. Run:

    python3 scripts/validate_suite.py
    python3 -m unittest discover -s tests -p 'test_*.py' -v

- [ ] **Step 5: Commit documentation and metadata**

    git add .codex-plugin/plugin.json README.md docs/architecture.md docs/development.md CHANGELOG.md tests/test_bundle.py tests/test_repository_contract.py
    git commit -m "docs: document complete skill operations and updates"

### Task 13: Run full release verification and hand off the implementation

**Files:**
- Modify: docs/superpowers/plans/2026-08-27-math-modeling-complete-skill-implementation.md (checkboxes only)
- Create outside repository: temporary bundle and QA reports

- [ ] **Step 1: Run all deterministic checks**

    python3 scripts/validate_suite.py
    python3 -m unittest discover -s tests -p 'test_*.py' -v
    bundle_root="$(mktemp -d)/math-modeling-suite-bundle"
    python3 scripts/build_bundle.py --output "$bundle_root"
    python3 scripts/validate_bundle.py "$bundle_root"
    python3 scripts/install_local.py --bundle "$bundle_root"

Expected: source validation passes, all tests pass, bundle validation passes, and installer dry-run prints commands without changing Codex configuration.

- [ ] **Step 2: Run optional official validators when present**

Locate the installed Codex quick_validate.py and validate_plugin.py; run them against the source and generated bundle. If either validator is unavailable, record that fact in the QA report rather than substituting an unsupported result. Do not run codex plugin add unless the user explicitly requests installation.

- [ ] **Step 3: Inspect the bundle and generated fixture artifacts**

Confirm the bundle contains all required Skill metadata, schemas, references, templates, and scripts, but no iterations/, virtual environment, cache, credential filename, or test-generated result. Confirm the fixture paper has the Chinese sections and that fallback status blocks submission-ready.

- [ ] **Step 4: Update the plan checkboxes and changelog**

Mark only observed passing steps complete, add the exact test count and tool availability to CHANGELOG.md, and record any user-supplied Python/LaTeX paths only in the external QA report, never in the repository.

- [ ] **Step 5: Request code review before integration**

Invoke superpowers:requesting-code-review with the implementation commits, test output, bundle path, and any unresolved warnings. Do not claim the Skill is complete until review findings are resolved and the verification commands are rerun.

## Spec coverage and self-review checklist

Before executing this plan, verify that every design requirement maps to a task:

| Design requirement | Covered by |
| --- | --- |
| Python-only and user interpreter required | Tasks 3, 4, 10, 11 |
| User template priority and fallback non-submission | Tasks 8, 9, 11 |
| Three gates and fail-closed routing | Tasks 1, 3, 7, 10, 11 |
| v001/v002 mixed per-question iteration and stale propagation | Task 3 and Task 11 |
| Ten families and at least 30 templates | Task 5 |
| C-A/C-B figure quality and source closure | Task 6 and Task 11 |
| Chinese abstract, sections, symbols table, appendices | Task 8 and Task 9 |
| 25–27 body target and <=30 total pages | Task 9 and Task 11 |
| CUMCM rules/data governance and external approval | Task 10 |
| Bundle safety and development/update workflow | Task 12 and Task 13 |

Run these self-review commands on the plan before committing it:

    rg -n -e "T[B][D]" -e "T[O]DO" -e $'\\u5f85\\u5b9a' -e $'\\u672a\\u5b9a\\u4e49' -e $'\\u5360\\u4f4d' docs/superpowers/plans/2026-08-27-math-modeling-complete-skill-implementation.md
    git diff --check

The first command must return no matches; the second must exit successfully. Check that every function name used in a later task is defined in an earlier task or in the existing repository, that every new stage has both SKILL.md and agents/openai.yaml, and that no task asks the implementation to invent data, citations, page counts, or official rules.
