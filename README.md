# Math Modeling Suite

Math Modeling Suite 是一个面向 Codex 的数学建模插件，通过分阶段流程完成问题分析、建模求解、验证，并在需要时生成图表和论文。

**[English guide / 英文指南](docs/README.en.md)**

## 安装前准备

- 支持 `plugin` 命令的 [Codex CLI](https://developers.openai.com/codex/cli/reference/)
- Git
- Python 3.10 或更高版本

安装器只负责构建、验证并注册本地 Codex 插件包；它不会安装 Python 包、LaTeX、求解器、MCP server 或凭据。

## 首次安装

先克隆仓库并进入仓库根目录。`--bundle` 必须指向**仓库外部**一个不存在或为空的目录。

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

安装完成后，如果 Codex 已经打开，请重启 Codex，并在新对话中使用插件。用下面的命令确认插件已列出：

```bash
codex plugin list
```

列表中应出现 `math-modeling-suite`。

## 获取 Python 可执行文件的绝对路径

工作流只使用你明确提供的 Python 解释器，不会自行创建环境或替换解释器。先确认它是 Python 3.10+，再复制绝对路径。

macOS / Linux：

```bash
python3 --version
python3 -c 'from pathlib import Path; import sys; print(Path(sys.executable).resolve())'
```

Windows PowerShell：

```powershell
py -3 --version
py -3 -c "from pathlib import Path; import sys; print(Path(sys.executable).resolve())"
```

## 第一次使用

在 Codex 新对话中复制下面的提示词，并把示例值全部换成自己的绝对路径和要求：

```text
请使用 $math-modeling-orchestrator 完成这个数学建模任务。

- 项目目录（绝对路径）：/absolute/path/to/my-modeling-project
- 题目与附件（文字说明或绝对路径）：/absolute/path/to/problem-and-attachments
- Python 可执行文件（绝对路径）：/absolute/path/to/python
- 竞赛：CUMCM
- 是否需要论文：是
- LaTeX 模板（可选，绝对路径；没有则写“未提供”）：/absolute/path/to/main.tex

请先完成环境预检；每到人工确认门时停下来，说明需要我确认的内容。
```

工作流有三个必须由你确认的节点：Gate 1 确认题意与关键假设；Gate 2 确认各问模型、基线、参数来源和验证计划；Gate 3 冻结当前结果、验证记录及相关图表。数据分析、可视化和论文阶段只会在任务确实需要时进入。

## 遇到问题、更新或卸载

- 找不到插件时，先运行 `codex plugin list`，然后重启 Codex 并新建对话。
- 安装器拒绝路径时，确认 bundle 位于仓库外，且首次安装时目标目录不存在或为空。
- 更新与卸载由 Codex CLI 管理；参见[运维参考](docs/operations.md#安装更新与卸载)和 [Codex CLI reference](https://developers.openai.com/codex/cli/reference/)。

## 深入阅读

- [运维参考](docs/operations.md)：路由、预检、不可变迭代、验证、图表与论文生产
- [系统架构](docs/architecture.md)
- [开发与资源更新](docs/development.md)
- [更新记录](CHANGELOG.md)
- [Codex Skills](https://developers.openai.com/codex/skills/) 与 [构建 Codex 插件](https://developers.openai.com/plugins/build/plugins/)

## 许可证

MIT，详见 [LICENSE](LICENSE)。
