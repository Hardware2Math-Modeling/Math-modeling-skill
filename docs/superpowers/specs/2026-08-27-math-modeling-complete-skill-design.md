# 数学建模完整 Skill 套件设计

**状态：** 已完成需求讨论，待用户审阅后进入实施计划阶段。

## 1. 目标与范围

将现有 `math-modeling-suite` 从“阶段契约和插件打包骨架”升级为一套能够在 Codex 中辅助完成一道 CUMCM 中文数学建模题的、可恢复、可验证、Python-only、LaTeX-only 的 Skill 套件。

首版正式支持 CUMCM 中文赛题。架构预留其他赛事的 competition pack 接口，但不虚构其规则。工作流要覆盖：题目与附件检查、题意分析、数据处理、方法选择、逐问 Python 建模与求解、科学绘图、模型检验、结果冻结、LaTeX 论文装配、编译和最终质量检查。

### 1.1 硬性要求

- 编程只使用 Python，不提供或调用 MATLAB 工作流。
- 论文只使用 LaTeX，不生成 Word 作为正式交付格式。
- 用户必须提供可用的 Python 解释器绝对路径；没有路径时先询问，不能猜测或切换解释器。
- LaTeX 模板优先使用用户提供的模板。模板缺失时允许使用内置通用 fallback，但必须标记为非官方、可编译但不可直接提交。
- 所有外部数据下载必须先说明用途、字段、来源和许可证，经用户确认后执行；不能用模拟数据冒充赛题数据。
- 初始化阶段和模型阶段设置强制人工确认门：题意/假设、模型/基线/验证方案、结果/数字/图表冻结。
- 最终 PDF 总页数不得超过 30 页；正文目标为 25–27 页。实际页数以编译后的 PDF 统计为准。
- 中文论文为默认，不自动生成英文摘要，除非模板或当届规则明确要求。
- 旧版本和旧结果不可覆盖；影响结果的修改产生新的迭代快照。

### 1.2 非目标

- 不承诺获奖或替用户作出有争议的科学判断。
- 不在没有证据时填充参数、数据、引用、图表、结论或页数。
- 不自动安装 Python、LaTeX、字体、宏包或外部求解器；只诊断并提供针对用户解释器的安装命令，安装由用户确认后完成。
- 不把一次长提示词当作可恢复的运行时状态机。

## 2. 总体架构

保留当前“一个插件、多阶段 Skill”的边界，并增加确定性的项目底座。模型负责题意理解、方法判断、假设解释和论文叙事；脚本负责状态读写、版本快照、哈希、Python/LaTeX 执行、产物索引和可自动判定的质量门禁。

```text
preflight (必需)
  ├─ 用户确认项目根目录、Python 解释器、模板路径和赛事
  ├─ 检查输入、依赖、LaTeX 工具链和模板
  └─ 写入 input/environment/template manifests
       ↓
Gate 1：题意与关键假设确认
       ↓
problem-analysis → data-analysis? → model-construction
       ↓
Gate 2：每问模型、baseline、验证方案确认
       ↓
model-solving → visualization? → validation
       ↓
Gate 3：结果、数字和图表冻结
       ↓
需要论文？ ─否→ 完成验证汇总
       │是
       ↓
paper-writing → paper-production → PDF render/QA
       ↓
submission-ready 或明确失败报告
```

这里的问号表示受条件控制的阶段，而不是模型自行决定的跳过：有相关数据时不得跳过
`data-analysis`；论文请求一旦提出，`paper-writing` 和 `paper-production` 都必须完成；
正文或附录引用图表时 `visualization` 必须完成，否则只能记录“无图需求”的跳过理由。

### 2.1 建议的运行时项目布局

Skill 安装目录保持只读。用户赛题项目由用户指定或确认当前工作目录，所有赛题专属产物写入该目录：

```text
modeling_project/
├── input/                         # 题目和原始附件，只读
├── iterations/
│   ├── v001/
│   │   ├── state/                 # handoff、决策和门禁状态
│   │   ├── code/q1/ q2/ ...       # 赛题专用 Python
│   │   ├── data/                  # 可复现清洗副本
│   │   ├── results/q1/ q2/ ...    # 数值、指标、运行日志
│   │   ├── figures/               # 图、图表 manifest、渲染检查
│   │   ├── paper/                 # 模板副本、LaTeX 源码和 PDF
│   │   └── manifests/             # input/run/figure/paper/environment
│   └── v002/                      # 任何影响结果的修改都新建版本
├── current.json                   # 当前迭代与各问题来源版本指针
├── qa/                            # 汇总报告
└── archive/                       # 被淘汰版本的说明，不删除证据
```

`current.json` 可以记录不同问题来自不同迭代，例如 Q1 仍采用 v001、Q2 采用 v003；论文装配前必须检查所有来源均已通过当前验证并被冻结。

## 3. Skill 与脚本职责

### 3.1 现有 Skill 的增强

- `math-modeling-orchestrator`：读取状态文件和 workflow，执行 preflight、人工门、版本创建、按问路由、失效传播和最终汇总；不能仅依赖模型记忆。
- `math-modeling-problem-analysis`：输出问题、子问题、变量、约束、指标、单位、事实来源和待确认假设。
- `math-modeling-data-analysis`：只读盘点原始数据，记录字段、单位、缺失、异常、泄漏、转换和外部数据审批。
- `math-modeling-model-construction`：从 10 个方法族中形成候选、baseline 和验证方案；所有关键选择进入 Gate 2。
- `math-modeling-model-solving`：只执行已确认模型，调用用户指定 Python，按问题保存代码、命令、日志、环境和结果。
- `math-modeling-validation`：执行预先声明的检查，失败时定位最早受影响阶段；通过后才能进入冻结门。
- `math-modeling-paper-writing`：只基于当前验证通过且冻结的证据写中文 LaTeX 内容，不负责偷偷补结果。

### 3.2 新增或拆分的能力

新增能力的边界在首版中固定如下，避免“独立 Skill 或工具”造成路由歧义：

```text
skills/math-modeling-preflight/
skills/math-modeling-visualization/
skills/math-modeling-paper-production/
skills/math-modeling-method-library/       # 只读方法参考库，不是工作流阶段
```

前三个目录都是独立可发现、可由 orchestrator 路由的 Skill；方法库是可直接查询的只读
Skill/参考包，不写入项目状态，也不改变模型选择。工作流阶段的固定顺序是：

| 阶段 ID | Skill | 是否必需 | 进入条件 | 产出边界 |
| --- | --- | --- | --- | --- |
| `preflight` | `math-modeling-preflight` | 是 | 新项目或环境/模板变化 | 项目配置、输入/环境/模板 manifest |
| `problem-analysis` | 现有分析 Skill | 是 | preflight 通过 | 题意、子问题、变量、约束、假设 |
| `data-analysis` | 现有数据 Skill | 条件必需 | 存在数据或外部数据需求 | 数据质量和可追溯转换 |
| `model-construction` | 现有建模 Skill | 是 | 前置分析完成 | 每问模型、baseline、验证计划 |
| `model-solving` | 现有求解 Skill | 是 | Gate 2 通过 | 可复现 Python 运行和结构化结果 |
| `visualization` | `math-modeling-visualization` | 引用图时必需 | 有冻结前的结果 | 图、图 manifest、渲染 QA |
| `validation` | 现有验证 Skill | 是 | 求解和必要绘图完成 | 按预设阈值的验证结论 |
| `paper-writing` | 现有写作 Skill | 用户请求论文时必需 | validation 通过、Gate 3 通过 | 中文 LaTeX 内容 |
| `paper-production` | `math-modeling-paper-production` | 请求论文时必需 | paper-writing 完成 | 模板副本、PDF、页数和最终 QA |

`paper-writing` 负责内容，`paper-production` 负责模板复制、章节装配、编译、PDF
渲染和最终质量检查。`visualization` 可在验证前生成诊断图和候选正文图；Gate 3 后只
允许对已登记图进行不改变数据语义的排版修订，修订会产生新 hash 并触发纸面 QA。

## 4. 持久状态、版本和交接契约

### 4.1 机器可验证 schema

在现有 Markdown/YAML 示例之外，新增 JSON Schema 和实例校验：

```text
skills/math-modeling-orchestrator/references/schemas/
├── handoff.schema.json
├── iteration.schema.json
├── manifest.schema.json
└── gate.schema.json
scripts/validate_handoff.py
scripts/migrate_handoff.py
scripts/project_state.py
```

每个阶段进入和退出前都验证 handoff。运行时 handoff 的七个顶层对象
`schema_version`、`task`、`state`、`context`、`result`、`quality`、`next` 均为必需；
其中 `context`、`quality` 的集合字段在不适用时使用空数组，不能用空字符串伪造证据。
当前仓库为兼容旧版对话 handoff 保留“最小四字段”检查，但一旦写入项目状态文件，
必须通过完整 schema。删除字段、改变字段语义或改变路由规则时升级 schema 并提供迁移逻辑。

### 4.2 Manifest 与新鲜度

每次迭代至少生成：

- `input_manifest.json`：题目/附件相对路径、大小、修改时间、SHA-256、来源和只读状态；
- `environment_manifest.json`：Python 解释器绝对路径、Python 版本、依赖版本和平台信息；
- `run_manifest.json`：代码 hash、输入 hash、完整命令、退出码、种子、运行时间、输出 hash 和日志；
- `figure_manifest.json`：图的角色、claim、源结果 hash、脚本、输出格式和 QA 状态；
- `paper_manifest.json`：模板来源、模板 hash、主入口、引擎、编译命令、PDF hash、页数和 QA 状态；
- `gate_report.json`：人工确认、自动检查、时间、操作者和当前状态。

下游使用报告前重新计算其输入 hash。输入、代码、环境或产物变化后，相关报告立即标记
`stale`，不得继续授权论文。`current.json` 使用以下固定字段，支持按问混合迭代：

```json
{
  "schema_version": "1",
  "project_id": "example-2026-cumcm",
  "active_iteration": "v003",
  "question_sources": {"Q1": "v001", "Q2": "v003"},
  "gates": {"gate1": "confirmed", "gate2": "confirmed", "gate3": "pending"},
  "status": "in_progress",
  "updated_at": "2026-08-27T00:00:00Z"
}
```

任何影响某问结果的输入、代码、参数或方法变更都创建递增的 `vNNN` 目录；新版本从
父版本复制必要证据但不覆盖父版本。失效传播按依赖图执行：该问的 run、figure、validation
和 paper 产物先标记 `stale`，依赖该问的汇总结论也一并失效；不相关问题仍可由
`question_sources` 指向旧版本。

### 4.3 三个人工确认门

1. **Gate 1：题意与关键假设**。确认子问题、目标、约束、单位、外部数据需求和会改变模型的假设。
2. **Gate 2：模型路线**。每一问确认主模型、可信 baseline、参数来源、验证阈值和可接受失败条件。
3. **Gate 3：结果冻结**。确认最终数值、结论、图表用途、版本来源和是否允许进入论文。

确认不是自然语言中的隐含同意，而是可审计的 `gate_report.json` 记录。每条记录至少
包含 `gate_id`、`status`（`pending`/`confirmed`/`rejected`）、确认人、UTC 时间、
所依据的 artifact hash、备注和 schema 版本。没有 `confirmed` 记录时可以保存草稿，
但不能向下游推进或标记完成；`rejected` 必须写明回退阶段。

## 5. Python-only 方法库与执行规范

### 5.1 十个方法族

1. 优化与决策；
2. 预测、回归与时间序列；
3. 综合评价与多指标决策；
4. 统计分析与数据处理；
5. 机器学习、分类、聚类与降维；
6. 图论与网络；
7. 机理模型与数值分析；
8. 随机模拟与不确定性；
9. 博弈与多主体决策；
10. 几何、空间与信号。

算法目录借鉴公开项目的分类和适用条件，不复制没有明确许可的实现。首版至少提供每个
方法族 3 个可运行的 Python 模板（共不少于 30 个），并为每个方法统一提供：触发条件、
前提假设、输入字段/单位、核心公式、复杂度或规模边界、Python 最小模板、参数含义、
失败信号、验证方法、建议图表和论文写法。模板必须声明其依赖和已知不适用情形；不能
因为库中存在模板就自动选择该方法。

### 5.2 依赖和环境策略

用户必须提供 Python 解释器绝对路径。仓库自身的契约测试可以使用开发机的
`python3`，但任何赛题代码、数据处理、求解和绘图运行都只能使用该绝对路径。
最小基线依赖候选为：

```text
numpy, pandas, scipy, matplotlib, scikit-learn,
statsmodels, networkx, openpyxl
```

根据已确认的方法生成按题目裁剪的依赖清单；深度学习、Prophet、专业优化器等重依赖默认不安装。preflight 使用指定解释器执行检查，并在缺包时只输出精确命令：

```bash
/absolute/path/to/python -m pip install "package>=lower-bound"
```

用户确认安装完成后重新诊断；不得自动安装、使用系统 Python 或隐藏降级。

### 5.3 按问执行

每个问题独立拥有 `code/qN`、`results/qN`、运行日志和结果契约。代码必须从真实输入读取数据，固定随机种子，输出 JSON/CSV 等结构化结果，并记录失败尝试。Runner 捕获 stdout/stderr、退出码、超时、环境和 hash；Skill 解释模型和结果，但不把 Runner 的失败改写成成功。

## 6. 科研绘图设计

新增 `math-modeling-visualization`，采用已确认的 C 风格：

- **正文图（C-A）**：极简、白底、少色、统一字体和线宽、矢量优先，适合正文和灰度打印；
- **诊断图（C-B）**：允许关键点、区间、机制和误差注释，但明确标记为 diagnostic/exploratory；
- 两者共享色盲友好配色、单位规则和导出规范。

建议目录：

```text
skills/math-modeling-visualization/
├── SKILL.md
├── agents/openai.yaml
├── references/
│   ├── chart-selection.md
│   ├── figure-roles.md
│   ├── visual-style.md
│   ├── render-qa.md
│   └── templates/catalog.json
├── scripts/
│   ├── profile_data.py
│   ├── export_figure.py
│   ├── validate_figure.py
│   ├── visual_qa.py
│   └── build_contact_sheet.py
└── assets/styles/modeling.mplstyle
```

每张图先登记再绘制。`role` 只能取 `evidence`、`validation`、`diagnostic`、
`conceptual` 之一；`conceptual` 图必须明确标注“示意图”，不能作为数据证据：

```json
{
  "figure_id": "q1-error-distribution",
  "role": "validation",
  "question_id": "Q1",
  "claim_id": "claim-q1-03",
  "sources": [{"path": "results/q1/metrics.json", "sha256": "..."}],
  "outputs": ["figures/q1-error-distribution.pdf", "figures/q1-error-distribution.png"],
  "status": "verified"
}
```

图表门禁必须检查：

- 图来自真实结果，不能使用未标记的示意数据；
- 图型与论证目标匹配，概念流程图不得冒充数据证据；
- 坐标轴、单位、图例、误差区间、样本范围和有效数字完整；
- 色盲友好、灰度可读、字体和线宽统一；
- 优先 PDF/SVG，PNG 达到约定 DPI；
- 在论文实际尺寸渲染后无裁切、重叠、乱码或不可读文字；
- 图号、图题、claim 和正文引用闭环；
- 图表源结果或代码变化会使图标记 stale。

参考方向包括公开的 Nature 风格、SciPilot Figure Skill 和 ModelViz 的模板驱动/质量检查思路；只吸收可复用原则，不复制受限资产。图表脚本不得内置未经登记的随机示例数据；
测试中的 fixture 数据必须明确标记为测试数据，不能进入提交产物。

## 7. LaTeX 论文生产

### 7.1 模板优先级

```text
用户提供模板
  > 用户明确指定的官方模板
  > 本地已核验模板
  > 内置通用 fallback
```

开始前必须询问模板路径。模板缺失时可使用仓库内置的通用中文 LaTeX 模板，但输出和报告必须写明：非官方、提交前必须替换。模板与当届规则冲突时保留用户模板副本，生成冲突报告，允许草稿编译，但禁止 `submission-ready`。

模板 manifest 记录赛事、届次、来源 URL、核验日期、许可证、hash、主入口、引擎、必须章节、页数/字号/匿名要求、AI 披露要求、编译命令和 fallback 状态。模板复制到当前迭代的 `paper/`，不修改 Skill 安装目录。用户未提供模板时，fallback 的
`template_status` 固定为 `fallback_non_submission`；只有用户模板或已核验官方模板才
可能进入 `submission-ready` 候选。

### 7.2 固定论文结构

默认生成中文论文，不添加英文摘要：

```text
摘要
关键词
1 问题背景与重述
  1.1 问题背景
  1.2 问题重述
2 问题分析
3 模型假设
4 符号说明
5 模型的建立与求解
  5.1 第一问
    5.1.1 建模
    5.1.2 计算
  5.2 第二问
    5.2.1 建模
    5.2.2 计算
  ...
6 模型检验
7 模型评价与推广/改进
8 结论
附录 A 参考文献
附录 B 代码清单与关键代码
附录 C AI 使用说明与人工复核记录
附录 D 补充表格、推导和图表
```

实际问题数决定 `5.x` 数量。每一问的正文必须同时包含建模思路和计算过程；不能只在附录给代码或数字。第 6 部分按问引用 validation gate 已通过的证据，不另造检验结果。章节名可由当届官方模板要求覆盖，但结构语义必须保留并记录映射。

### 7.3 摘要写作规则

摘要首段固定为两句功能：第一句讲背景并肯定问题存在，第二句说明本文完成了什么。其后每一问占一个自然段：

- 段首用总领句概括该问目标；
- 中间概述建模步骤、求解方法和必要验证；
- 段尾给出该问答案或核心定量结论；
- 关键结果、模型名称或答案可适当使用 `\\textbf{}` 加粗，但不滥用；
- 摘要后紧接 `关键词`，关键词来自题目、模型和应用领域。

不得在摘要中写未冻结数字、未验证性能或模板无法支持的断言。

### 7.4 符号、图表和引用

第 4 部分生成三列表格：`符号 | 说明 | 单位`。所有公式中的重要符号必须出现，单位必须一致。图表必须有图号、图题、来源/数据范围和正文引用；表格必须有表号、表题和引用。引用、数字、模型名称和结论由脚本做跨文件一致性检查。

### 7.5 页数门禁

- 编译后实际统计 PDF 页数；“正文页数”定义为从第 1 部分开始到第 8 部分结束，
  “总页数”包含封面、摘要、正文和全部附录；统计脚本记录使用的页范围和工具版本；
- 正文目标 25–27 页；
- 最终 PDF 总页数 `<= 30`；
- 少于 25 页时只补充必要的推导、分析、验证和限制，不灌水；
- 超过 30 页时先压缩重复叙述、优化图表布局、合并冗余表格，把完整代码移到独立附件；
- 仍无法满足时暂停并报告原因，请用户决定；
- 禁止空白页、异常字号、不可见文字或其他伪造页数手段。

## 8. 竞赛规则、联网和数据治理

首版以 CUMCM 为正式 competition pack。规则文件按赛事和届次存放，记录官方 URL、发布日期、核验时间和内容 hash；提交前重新核验当届官方通知。规则与模板冲突时以官方规则为合规判断依据。

联网分三类：

1. 官方规则/模板只读核验：可以自动查询并保存来源和 hash；
2. 学术文献检索：可提出候选，但纳入论文前由用户确认；
3. 外部建模数据：必须先说明字段、用途、来源、许可证和风险，用户确认后下载。

网络不可用时使用本地缓存并明确核验日期；不能把搜索摘要直接写为事实或引用。外部
数据下载和非官方文献抓取默认暂停，只有用户确认审批记录后才执行；官方规则/模板的
只读核验也必须把 URL、检索日期和内容 hash 写入 manifest。

### 8.1 公开项目借鉴边界

实现阶段可以阅读以下公开仓库来比较分类、提示词边界和模板化工作流，但只吸收已在本
设计中明确的原则，不复制无明确许可证的代码、提示词或论文模板：

| 项目 | 仅借鉴的方向 |
| --- | --- |
| `jihe520/MathModelAgent` | 按赛题阶段组织任务、把结果交给后续审阅 |
| `XiaoMaColtAI/math-modeling-skill` | Skill 目录和建模任务分层 |
| `zhnnky329/MathModeling-skills` | 方法分类和逐问建模提示 |
| `yushui2022/MathModel-Skill` | 论文产出与建模过程衔接 |
| `Lupynow/math-modeling-skills` | 可复用算法条目和案例索引 |
| `handsomeZR-netizen/mathmodel-skill` | 竞赛场景下的工作流拆分 |

每次发布前都要重新记录来源 URL、访问日期和许可证状态；若许可证不清晰，只保留自写
实现和抽象后的接口说明。

## 9. 错误处理与完成状态

任何缺包、输入不可读、数据泄漏、模型不可行、收敛失败、验证不通过、图表 QA 失败、模板冲突、编译失败或页数不满足都采用 fail-closed：

- 保留日志和失败产物；
- 写入可读报告与机器报告；
- 标记当前阶段 `needs_revision` 或 `stale`；
- 创建新迭代，不覆盖旧版本；
- 定位最早受影响阶段并重新运行所有受影响下游；
- 阻止论文冻结和 `submission-ready`。

只有以下条件同时满足才可标记完成：

- 当前版本所有必需阶段有有效结果；
- Gate 1、Gate 2、Gate 3 已记录；
- Python 运行和结果 manifest 均新鲜且可复现；
- 所有必需验证通过；
- 图表和表格证据完整并通过 QA；
- LaTeX 实际编译成功；
- PDF 页数和结构检查通过；
- 数字、公式、单位、图表、引用和版本来源一致；
- 所有限制、外部数据和 AI 使用说明已披露。

## 10. 测试和验收

### 10.1 单元和契约测试

扩展现有测试以覆盖：schema 实例、状态迁移、版本不可覆盖、失效传播、manifest hash、Python 环境诊断、图表契约、模板 manifest、页数门禁和跨文件数字一致性。

### 10.2 端到端 fixture

新增一个不依赖网络和真实模型 API 的小型 CUMCM 风格题目 fixture，包含题面、CSV/Excel 附件和可编译 fallback LaTeX 模板。测试命令显式接收外部提供的
`--python /absolute/path/to/python`（或等价环境变量），不把解释器、虚拟环境或其缓存
打入仓库。至少验证：

1. 新项目初始化并通过 preflight；
2. Gate 1 阻止未确认的题意继续；
3. Gate 2 后按问生成并运行 Python；
4. 真实结果生成结构化指标和图表；
5. 改变 Q2 后生成 v002，Q1 仍引用 v001；
6. 改变输入或代码后旧 manifest 变为 stale；
7. 验证失败不能进入论文；
8. 冻结后生成中文摘要、关键词、1–8 章和附录；
9. LaTeX 实际编译，页数和引用检查运行；
10. 缺依赖、模板冲突、超 30 页和编译失败均 fail closed。

### 10.3 每次开发后的验证命令

```bash
python3 scripts/validate_suite.py
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/build_bundle.py --output /tmp/math-modeling-suite-bundle
python3 scripts/validate_bundle.py /tmp/math-modeling-suite-bundle
```

如果改变了 Skill 内容，还要运行官方 `quick_validate.py`；如果改变插件 manifest，还要运行官方 `validate_plugin.py`。安装测试使用 dry-run，真正修改 Codex 配置必须显式使用 `--apply`。每次安装或更新后使用新 Codex thread。

## 11. 开发和更新流程

新增能力遵循“行为 fixture → 失败基线 → 最小实现 → 同一 fixture 通过 → schema/workflow/validator/文档同步 → bundle 验证”的循环。新增阶段必须有独立触发条件、输入输出边界、handoff 字段和路由规则；新增方法优先放进阶段 references/assets，不把 orchestrator 变成算法百科。

用户提供的新绘图指导、论文模板或算法模板应按以下路径归档：

- 可执行逻辑放 `skills/<skill>/scripts/`；
- 重型说明放 `references/`；
- 模板、字体、样式和示例产物放 `assets/`；
- 题目专属文件只放用户项目的 `iterations/`；
- 来源、许可证、版本和 hash 写入 manifest；
- 不覆盖已发布模板，新增版本或 competition pack；
- 同步更新 schema、workflow、测试、README 和 changelog；
- 重新构建、校验和安装 bundle，再用真实题目验证。

实现按四个可独立验收的阶段拆分，避免一次改动同时触碰所有边界：

1. **底座阶段**：完成 preflight、项目目录、迭代快照、完整 handoff/schema、manifest、
   Gate 记录和 Python runner；先让无模型 API 的 fixture 能恢复和正确 fail-closed。
2. **方法与绘图阶段**：补齐十类方法目录及最小模板，加入 visualization、图表 manifest、
   样式和渲染 QA；用真实 fixture 结果证明图表来自数据且能触发 stale 传播。
3. **论文生产阶段**：加入中文 LaTeX fallback、用户模板复制、章节/摘要/符号表装配、
   编译、页数和跨文件一致性检查；fallback 永远保持非提交状态。
4. **竞赛验收阶段**：加入 CUMCM competition pack、规则核验记录、端到端三天迭代测试、
   bundle/官方 Skill 校验和文档更新；只有这一阶段通过才报告“可作为完整 Skill 运行”。

每个阶段都必须先添加行为 fixture 和失败断言，再实现最小代码；阶段之间以 manifest 和
schema 接口连接，不以共享的隐式全局变量连接。

## 12. 方案自检结果

- 所有用户已确认的硬要求均有对应章节：Python-only、LaTeX-only、用户模板优先、Python 环境必需、外部数据审批、三个人工门、三天版本迭代、C 风格绘图、摘要格式、1–8 章结构、符号三列表格和 25–30 页门禁。
- “正文超过 25 页”和“总页数不超过 30 页”统一解释为正文目标 25–27 页；实际无法同时满足时 fail-closed 并请求用户决定。
- 绘图 Skill 与论文生产 Skill 分离，但通过 figure/paper manifest 连接；不会让图表质量规则淹没建模阶段。
- 模板可缺失但 Python 环境不可缺失；fallback 永远不标记为提交就绪。
- 现有插件安全打包流程保留，不把用户项目、状态、缓存或凭据打入 bundle。
- 已消除“新增能力是否独立 Skill”“handoff 最小字段与完整字段冲突”“按问迭代如何失效传播”、
  “正文页数如何统计”和“测试环境从何处取得”等歧义；这些决定已在第 2、3、4、7、10、11 节固定。
- 范围拆成四个可验收阶段；方法库是只读支持包，visualization 和 paper-production 的路由
  条件已明确，不要求把所有算法逻辑塞入 orchestrator。
