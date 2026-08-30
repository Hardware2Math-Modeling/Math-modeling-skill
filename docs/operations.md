# Math Modeling Suite 运维参考

本文保存面向操作者和维护者的详细行为说明。首次安装和第一次使用请先阅读[中文指南](../README.md)或 [English guide](README.en.md)。除非另有说明，命令都从仓库根目录运行。

## 工作流与路由

```text
preflight
  -> problem-analysis
  -> data-analysis? -> model-construction
  -> model-solving -> visualization? -> validation
  -> paper-writing? -> paper-production? -> complete
```

存在相关数据时必须进入 `data-analysis`。声明图表论点或基于图表的验证检查时必须进入 `visualization`。一旦存在可信的论文请求，两个论文阶段都必须执行。`$math-modeling-orchestrator` 独占路由、三个确认门、回滚、恢复和完成检查；各阶段 Skill 不能自行批准下游路由。

`math-modeling-method-library` 是只读支持库，不是第十个工作流阶段。它提供受维护的方法 id、参考资料、确定性 Python 模板、依赖声明及验证、图表和论文指导，但不修改项目状态，也不替用户选择模型。完整阶段注册表和持久状态约定见[系统架构](architecture.md)。

## 显式 Python 预检

调用 orchestrator 时必须给出项目根目录、为本次工作选择的 Python 可执行文件、竞赛及交付要求，以及用户模板的绝对路径或明确说明没有模板。`python3` 这类命令名不能代替解释器身份；预检只探测用户给出的绝对路径，不创建环境、不调用 pip，也不替换解释器。

仓库级方法 smoke test 同样必须通过 `--python` 指向所提供的绝对解释器；`--work-dir` 必须是仓库外的空目录：

```bash
python3 scripts/method_catalog.py \
  --root . \
  --check \
  --smoke \
  --python /absolute/path/to/python \
  --work-dir /absolute/empty/work-directory
```

预检 API 是 `scripts/preflight.py` 中的 `diagnose_environment(...)`。`init_project(...)` 和下面的 CLI 可初始化项目：

```bash
python3 scripts/project_state.py init /absolute/project/root \
  --python-executable /absolute/path/to/python \
  --input-dir /absolute/path/to/input \
  --competition CUMCM
```

存在用户模板时增加 `--template-path /absolute/path/to/main.tex`。项目根目录不能已存在；初始化会把源输入复制为只读清单，写入版本化 manifest，并创建第一个不可变迭代 `iterations/v001/`。

## 不可变迭代、确认门与 stale 证据

`current.json` 指向当前迭代，也可以按问题混合来源，例如 Q1 来自 `v001`、Q2 来自 `v002`。影响结果的修改必须创建新迭代，不能覆盖旧迭代：

```bash
python3 scripts/project_state.py new-iteration /absolute/project/root \
  --reason "revise Q2 parameter source" \
  --question Q2
```

旧迭代目录和模板始终保留为审计证据。状态层写入严格的 schema-version-2 handoff、输入/环境/依赖/运行/结果/图表/验证/论文 manifest，以及只追加的 gate 证据。输入、代码、参数、方法、结果或已注册来源改变时，依赖证据会变为 stale。只有每个被引用问题的依赖都仍然 current 且 frozen 时，才能使用混合迭代；论文组装和完成检查会重新核对真实文件及哈希。

- Gate 1 确认题意解释与关键假设。
- Gate 2 确认每一问的模型、基线、参数来源与验证计划。
- Gate 3 冻结当前结果、验证、运行和相关图表。

`current.json` 中的标签或阶段建议不能替代有效、由 host 绑定的人工确认记录。

## 图表与 figure QA

可视化阶段在绘图前注册 figure manifest，把图表绑定到当前结果文件哈希、claim id、坐标轴和单位、图例决策、标题、论文引用、宽度、用途及输出。`scripts/export_figure.py` 提供 `export_figure(...)`，只从已注册且 current 的来源发布 PDF 以及 PNG 或 SVG。

确定性 figure QA 依次使用 `scripts/figure_qa.py` 的 `validate_figure_manifest(...)`、`refresh_figure_status(...)`，再通过 `scripts/visual_qa.py` 的 `run_visual_qa(...)` 做渲染检查。只有来源哈希、格式、尺寸、分辨率、元数据、灰度/色盲检查及人工视觉检查均为 current，图表才能进入 `verified`。缺少 `pdftoppm` 时状态为 `needs_review`；来源改变时状态为 `stale`，不会隐式刷新哈希。

## LaTeX 论文生产与 fallback 状态

模板优先级依次为：用户提供、用户选择的官方模板、本地验证的官方模板、内置中文 fallback。位于 [`skills/math-modeling-paper-production/assets/fallback-zh/`](../skills/math-modeling-paper-production/assets/fallback-zh/) 的内置模板固定为 `fallback_non_submission`：它可以用于组装和编译检查，但不能授权 `submission_ready: true`。

论文写作只从 current、已验证且已冻结的证据生成中文内容。论文生产会把选定模板复制到当前迭代，组装内容，使用预检登记的 LaTeX 工具编译，检查结构、引用、数值、25–27 页正文目标和 30 页总上限，再通过已登记的 renderer 渲染并要求人工视觉检查。失败会保留不可变的尝试日志和非 ready 状态。

## 验证源代码与方法目录

以下检查不需要模型 API 或网络：

```bash
python3 scripts/validate_suite.py
python3 scripts/method_catalog.py --root . --check
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

离线端到端 fixture 覆盖项目初始化、路由 gate、Python 结果、图表、验证、混合不可变迭代、stale 传播和 fallback 论文生产。仅在存在受支持编译器时，才运行独立的真实编译器 smoke test。

## 创建与验证发布 bundle

生成的 bundle 必须放在仓库外：

```bash
bundle_root="$(mktemp -d)/math-modeling-suite-bundle"
python3 scripts/build_bundle.py --output "$bundle_root"
python3 scripts/validate_bundle.py "$bundle_root"
```

builder 会验证源文件和 staging 副本，选择已跟踪及未被忽略的未跟踪文件，在临时同级目录中写入本地 marketplace 布局，验证后原子发布。它拒绝非空目标和源代码树内部的输出。环境文件会被排除；符号链接、带符号链接的路径组件、特殊文件系统节点、Git submodule、已知凭据文件名、私钥后缀、Git 元数据、worktree、生成 bundle 和常见缓存会按共享归档策略被拒绝或排除。这个文件名/文件类型边界不是通用的内容秘密扫描器，因此发布内容仍需人工审阅。

## 安装、更新与卸载

`scripts/install_local.py` 会构建或复用有效 bundle，并在 `--apply` 存在时调用 Codex plugin 命令。没有 `--apply` 时只做 dry run，不修改 Codex 配置。`--marketplace-registered` 只适用于同一个已注册的 bundle 绝对路径；安装器会验证这个绑定关系。

非空的现有 bundle 会被验证并复用，不会从更新后的仓库自动重建。更新或卸载插件前，先运行 `codex plugin --help` 和 `codex plugin marketplace --help` 查看当前 CLI 支持的操作，并遵循 [Codex CLI reference](https://developers.openai.com/codex/cli/reference/)。操作后使用 `codex plugin list` 检查结果；Codex 已打开时应重启并新建对话。

安装器不会安装 Python 包、LaTeX、求解器运行时、MCP server 或凭据。项目输出只属于用户提供的项目根目录，不应写入已安装的 Skill 树。

## 维护者资源位置

- 绘图指导位于 [`skills/math-modeling-visualization/references/`](../skills/math-modeling-visualization/references/)，绘图样式位于 [`skills/math-modeling-visualization/assets/styles/`](../skills/math-modeling-visualization/assets/styles/)。
- 论文模板位于 [`skills/math-modeling-paper-production/assets/`](../skills/math-modeling-paper-production/assets/)；模板选择、生产和最终确认规则由该 Skill 和 `scripts/paper_production.py` 管理。
- 方法元数据和指导位于 [`skills/math-modeling-method-library/references/`](../skills/math-modeling-method-library/references/)；可执行模板及 smoke fixture 位于 [`skills/math-modeling-method-library/assets/`](../skills/math-modeling-method-library/assets/)。

资源更新、版本规则、bundle 检查和用户项目 smoke test 见[开发与资源更新指南](development.md)。
