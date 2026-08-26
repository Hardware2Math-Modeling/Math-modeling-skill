# 数学建模插件套件初始化设计

**状态：** 已获用户确认，作为初始化阶段的实施依据。

## 1. 背景与目标

本仓库将发展为一个面向数学建模任务的 Codex 插件套件。套件由一个主编排 skill 和多个职责单一的阶段 skill 组成。用户安装一次插件后，Codex 可以发现整套能力；主编排 skill 负责根据题目状态选择阶段、传递上下文、检查阶段产物，并在需要时回退。

初始化阶段的目标是打通以下闭环：

1. 仓库具有符合 Codex 插件规范的 manifest 和可发现的 skill 目录。
2. 主 skill 与阶段 skill 之间有明确、可复用的 handoff 契约。
3. 仓库可以被验证、打包为标准 marketplace bundle，并在本机安装测试。
4. 开发迭代可以安全地更新 cachebuster、重装插件并在新线程中验证。
5. 所有关键流程都有不依赖外部 API 的确定性检查。

初始化阶段不实现具体数学方法、求解器或竞赛题答案；阶段 skill 只提供真实的职责边界、输入输出契约和最小工作规则，后续再逐步扩充领域内容。

## 2. 设计原则与非目标

### 设计原则

- **单插件、多 skill：** 插件是安装和版本管理单位，skill 是调用和演进单位。
- **主模型编排：** 目录和安装不会隐式形成程序流水线；阶段顺序、跳过和回退由主编排 skill 的协议决定。
- **小边界：** 每个阶段 skill 只对一个阶段负责，不宣称整个题目完成，也不直接调用其他阶段 skill。
- **渐进披露：** 共享契约放在主 skill 可引用的 reference 中，阶段特定的细节只在对应阶段加载。
- **可逆安装：** 默认命令只校验和生成命令；修改用户 marketplace 或 Codex 配置必须显式确认/传入 `--apply`。
- **标准优先：** manifest、marketplace 路径和 cachebuster 遵循本机插件规范及已安装 Codex CLI 的命令接口。

### 非目标

- 不在初始化阶段接入 MCP、外部数据源、云端求解服务或认证信息。
- 不要求用户维护数据库、状态服务或固定的项目目录。
- 不把阶段结果强制保存为某一种文件格式；只有题目需要持久化时才生成项目产物。
- 不承诺所有数学建模题都能自动完成；缺少会实质改变模型选择的信息时必须向用户询问。

## 3. 仓库与插件架构

当前仓库根目录直接作为插件源码根目录。插件名固定为 `math-modeling-suite`，所有 skill 使用同一前缀以避免与其他插件冲突。

```text
Math-modeling-skill/
├── .codex-plugin/
│   └── plugin.json
├── skills/
│   ├── math-modeling-orchestrator/
│   │   ├── SKILL.md
│   │   ├── agents/openai.yaml
│   │   └── references/
│   │       └── handoff-contract.md
│   ├── math-modeling-problem-analysis/
│   ├── math-modeling-data-analysis/
│   ├── math-modeling-model-construction/
│   ├── math-modeling-model-solving/
│   ├── math-modeling-validation/
│   └── math-modeling-paper-writing/
├── scripts/
│   ├── validate_suite.py
│   ├── build_bundle.py
│   ├── validate_bundle.py
│   ├── install_local.py
│   └── update_cachebuster.py
├── docs/
│   ├── architecture.md
│   └── superpowers/
│       ├── specs/
│       └── plans/
├── README.md
├── LICENSE
└── .gitignore
```

每个 skill 目录至少包含：

- `SKILL.md`：YAML frontmatter 中有唯一的 `name` 和可区分的 `description`，正文只写该阶段实际需要的决策规则。
- `agents/openai.yaml`：UI 展示信息、默认调用提示和必要的 invocation policy。默认保持隐式调用开启；若某阶段只应由主编排 skill 调用，再单独调整并在文档中说明。

### 3.1 插件 manifest

`.codex-plugin/plugin.json` 只声明插件级元数据和 skill 根路径，核心形状如下：

```json
{
  "name": "math-modeling-suite",
  "version": "0.1.0",
  "description": "A staged Codex skill suite for mathematical modeling problems.",
  "author": {
    "name": "硬件重组之打数模"
  },
  "license": "MIT",
  "keywords": ["mathematical-modeling", "CUMCM", "research"],
  "skills": "./skills/",
  "interface": {
    "displayName": "Math Modeling Suite",
    "shortDescription": "Solve modeling problems in explicit stages",
    "longDescription": "Routes mathematical modeling work through analysis, modeling, solving, validation, and paper-writing skills.",
    "developerName": "硬件重组之打数模",
    "category": "Education & Research",
    "capabilities": ["Interactive", "Read", "Write"],
    "defaultPrompt": [
      "Use $math-modeling-orchestrator to work through this modeling problem."
    ]
  }
}
```

初始化实现会根据实际仓库信息补充或校验必需的 manifest 字段，不添加未创建的 MCP/app/hook 声明。

## 4. 阶段职责与路由

标准阶段及其职责如下：

| Skill | 职责 | 默认进入条件 | 主要产物 |
| --- | --- | --- | --- |
| `math-modeling-problem-analysis` | 将题面转成目标、约束、变量、评价指标和待确认问题 | 所有题目 | 问题定义与约束清单 |
| `math-modeling-data-analysis` | 识别数据、单位、质量、缺失、特征和可用证据 | 存在数据或题目要求估计/预测时 | 数据审计与分析结论 |
| `math-modeling-model-construction` | 提出假设、候选模型、符号体系和可解释性理由 | 问题定义已足够明确 | 模型规格与假设清单 |
| `math-modeling-model-solving` | 选择求解方法，组织计算/仿真并记录参数 | 至少一个模型已选定 | 求解结果、代码/图表路径 |
| `math-modeling-validation` | 检查误差、稳健性、敏感性、边界条件和局限 | 有可检验的模型结果 | 验证报告与通过/回退结论 |
| `math-modeling-paper-writing` | 将已验证的工作整理成用户需要的论文结构和表达 | 用户要求成稿或章节 | 论文草稿/章节 |

主 skill 维护一个阶段注册表，引用上述确切名称。阶段 skill 不直接互相调用；主 skill 可以根据题型跳过数据阶段，也可以在验证失败时回退到模型构建或求解阶段。

## 5. 主编排协议

### 5.1 统一 handoff

阶段之间使用名为 `Modeling Handoff` 的结构化 Markdown/YAML 契约。它是模型输出约束，而不是必须由外部程序解析的数据库格式。

```yaml
schema_version: "1"
task:
  statement: "题目原文或可靠摘要"
  objectives: []
  constraints: []
state:
  current_stage: "problem-analysis"
  status: "complete"
context:
  assumptions: []
  variables: []
  data: []
  methods: []
  decisions: []
artifacts:
  - path: "relative/path/to/artifact"
    kind: "table|figure|code|report"
    description: ""
quality:
  checks: []
  warnings: []
  confidence: "high|medium|low"
result:
  summary: "本阶段结论"
  details: []
next:
  recommended_stage: "data-analysis"
  rationale: ""
  alternatives: []
```

必填语义是 `schema_version`、`state`、`result` 和 `next`；其他字段在不适用时使用空数组，不编造数据。阶段可以返回 `needs_revision` 或 `skipped`，但必须说明原因。

### 5.2 状态机规则

```text
problem-analysis → data-analysis? → model-construction
                 → model-solving → validation
validation(pass) → paper-writing?
validation(fail) → model-construction | model-solving
```

- `?` 表示主 skill 可根据题目判断跳过，并记录理由。
- 验证未通过时不得直接进入论文写作。
- 缺少会改变模型选择的关键信息时暂停并向用户提问。
- 普通细节可以作合理假设，但必须进入 `assumptions` 和 `warnings`。
- 每个阶段结束时必须明确“已完成什么、证据在哪里、下一阶段需要什么”。

## 6. 安装、打包与升级

### 6.1 源码与 bundle 的分离

源码根目录是插件根目录，但 Codex 的标准本地 marketplace 使用 `./plugins/<plugin-name>`。`build_bundle.py` 因此生成一个不进入 git 的安装 bundle：

```text
<bundle>/
├── .agents/plugins/marketplace.json
└── plugins/math-modeling-suite/   # 当前仓库的干净副本
```

marketplace 条目使用：

```json
{
  "name": "math-modeling-local",
  "interface": {"displayName": "Local Math Modeling"},
  "plugins": [
    {
      "name": "math-modeling-suite",
      "source": {"source": "local", "path": "./plugins/math-modeling-suite"},
      "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
      "category": "Education & Research"
    }
  ]
}
```

### 6.2 开发者安装流程

```bash
python3 scripts/validate_suite.py
python3 scripts/build_bundle.py --output /tmp/math-modeling-suite-bundle
python3 scripts/validate_bundle.py /tmp/math-modeling-suite-bundle
codex plugin marketplace add /tmp/math-modeling-suite-bundle
codex plugin add math-modeling-suite@math-modeling-local
```

`install_local.py` 将把上述步骤封装起来：默认 dry-run，`--apply` 才执行 marketplace 注册/插件安装；脚本必须保留现有 marketplace，不覆盖不属于本套件的条目。

安装后重启 Codex（如已运行），并在新线程中测试；新线程是让更新后的 skill 和工具完整生效的安全边界。

### 6.3 迭代与版本

- 稳定发布使用 SemVer，例如 `0.1.0`、`0.2.0`。
- 本地迭代只替换 `+codex.<UTC timestamp>` cachebuster 后缀，不为了触发重装而虚增语义版本。
- `update_cachebuster.py` 必须保留已有版本基座和 prerelease 部分，并替换旧的 Codex 后缀。
- 生成的 bundle、marketplace 快照、缓存和用户配置不提交到 git。

## 7. 验证与测试

### 7.1 静态验证

`validate_suite.py` 使用 Python 标准库完成以下检查：

- `plugin.json` 是合法 JSON，插件名、版本和必需 interface 字段有效；
- 每个 `skills/*/SKILL.md` frontmatter 可解析，`name` 唯一且符合命名规则；
- 每个 skill 有 `agents/openai.yaml`，默认提示引用自身 skill 名；
- 主编排 skill 引用的阶段名称均存在；
- handoff 契约中的阶段状态、字段和路径引用没有断链；
- 仓库不含初始化器留下的 TODO/TBD scaffold 标记或未完成占位语句。

### 7.2 Bundle 验证

`validate_bundle.py` 对生成 bundle 中的 `plugins/math-modeling-suite` 运行同一套插件/skill 校验，并检查 marketplace 的 source path 实际指向该插件 manifest。

### 7.3 行为 smoke test

初始化阶段提供一个不调用模型 API 的最小 fixture，验证：

1. 主 skill 能列出标准阶段和 handoff 必填字段；
2. 无数据题目会显式跳过 data-analysis；
3. validation 返回失败时路由只能回到 model-construction 或 model-solving；
4. 未完成验证不会路由到 paper-writing。

测试只断言可观察的结构和路由不变量，不匹配某一段自然语言措辞。

## 8. 错误处理与安全边界

- manifest、skill frontmatter 或 marketplace JSON 无效时，验证和安装在任何全局写入前失败。
- bundle 输出目录存在且非空时拒绝覆盖；由脚本创建的临时目录可由用户显式删除。
- 安装脚本不读取或打印认证令牌，不自动安装 Python/TeX/求解器依赖。
- 阶段 skill 不能把未经验证的数值、数据来源或图表标记为已确认；不确定性进入 warnings。
- 外部写入（marketplace、Codex 配置、插件缓存）必须由显式 `--apply` 或用户直接运行命令触发。

## 9. 验收标准

初始化完成时应满足：

1. `python3 scripts/validate_suite.py` 在干净 checkout 中通过。
2. bundle 构建和 bundle 验证通过，且 marketplace source path 可解析。
3. 在存在 Codex CLI 的机器上，按 README 的命令可以注册并安装插件；没有 CLI 时能给出清晰的缺失提示而不修改文件。
4. 新线程中可以显式调用主 skill 和任一阶段 skill。
5. README、架构文档和脚本的命令互相一致。
6. 初始化改动按逻辑分 commit，且不 push 到远程。

## 10. 后续扩展边界

后续增加题型专用 skill、可选求解器、数据工具或论文模板时，优先新增独立 skill/reference，并在主 skill 注册表中声明进入条件和 handoff 版本；不要把不相关的领域规则堆进 orchestrator。若 handoff 发生不兼容变化，递增 `schema_version` 并提供迁移说明。
