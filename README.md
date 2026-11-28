# Shopify Harness

这套工具帮助开发者和编码代理维护 Shopify 主题。它能按模板中的实例定位 section，指导跨主题迁移、页面验收和性能分析，并校验 Git 变更。可在本地完成安装和检查。运行环境为 macOS 或 Linux、Git 和 Python 3.7+。主题包含 Node 测试时需要支持 `node --test` 的 Node.js，运行 Theme Check 时需要安装 Shopify CLI。

## 给现有主题接入通用版

以下示例假设当前位于 harness 根目录，主题 Git 仓库是同级的 `../my-theme`，其根目录有 `layout/theme.liquid`。也可直接传主题绝对路径。

```sh
./sync-to-theme.py --profile generic --dry-run ../my-theme
./sync-to-theme.py --profile generic ../my-theme
```

1. 在主题自己的 `AGENTS.md` 中加入一行。已有规则可原样保留，缺少入口时可新建。

   ```md
   处理 Shopify 主题任务时，先读取仓库根目录的 .agents/shopify-harness.md，并遵循本主题的具体约定。
   ```

2. 使用 Claude Code 的团队，在主题的 `CLAUDE.md` 中加入 `@AGENTS.md`。要让这些技能出现在 Claude Code 的项目技能目录中，在主题根目录执行一次以下命令。逐个创建链接可以保留团队已有的其他技能；遇到同名技能时先比较两份内容。

   ```sh
   mkdir -p .claude/skills
   for skill in section-port shopify-performance shopify-commit-message shopify-page-review; do
     entry=".claude/skills/$skill"
     if [ -e "$entry" ] || [ -L "$entry" ]; then
       printf '保留已有路径 %s\n' "$entry"
       continue
     fi
     ln -s "../../.agents/skills/$skill" "$entry"
   done
   ```

3. 检查主题 Git diff 和新文件。把公共清单中的文件、`.agents/shopify-harness.lock.json`、入口改动和选用的技能链接一起纳入团队版本控制。若主题原来忽略了 `.agents/`，先调整该主题的忽略范围，使这些文件可以提交。第二位开发者克隆主题后即可使用。

在主题根目录尝试定位一个真实组件。将路径和名称替换为该主题的 JSON 模板和编辑器标签。输出按模板顺序列出实例 ID、类型和禁用状态。选定实例后，可以要求代理用 `section-port` 迁移它，核对目标主题的 block、snippet、翻译和店铺资源。

```sh
python3 .agents/skills/section-port/scripts/extract_section.py templates/index.json --editor-name 'Hero' --list
python3 .agents/scripts/verify-changes.py
```

## EcoFlow 原有工作区

保留原来的命令，在 harness 根目录运行。默认选择 `ecoflow`，向目标主题同步公共文件、EcoFlow 的根说明、策略和历史案例。

```sh
./sync-to-theme.py --dry-run ../ecoflow-tech
./sync-to-theme.py ../ecoflow-tech
```

此模式沿用主题忽略 `AGENTS.md`、`CLAUDE.md`、`.agents/` 和 `.tmp/` 的约定，拒绝改写已被 Git 跟踪或未被忽略的路径。基线仍在 `.tmp/shopify-harness-sync.json`，旧版基线可以继续使用。若这些文件只用于本地代理，沿用主题现有的 `.shopifyignore` 发布设置。

## 更新与冲突处理

使用团队选定的 harness 版本，在同一模式下先运行 `--dry-run`，再正式同步。通用版把内容摘要和执行权限保存到可随仓库提交的 lock 文件，EcoFlow 版将其留在工作区。只读预览会检查整份清单。目标副本已被本地编辑或删除、首次接入时遇到不同内容，都会在复制前报告冲突。相同版本重复安装应显示需要复制 0 项。

发生冲突时按输出的**源文件**和**目标路径**比较差异。例如 EcoFlow 的根入口：

```sh
git diff --no-index -- profiles/ecoflow/AGENTS.md ../ecoflow-tech/AGENTS.md
```

先保留本地定制，再把公共改进或 EcoFlow 专属改进合并到对应来源。对没有基线的旧工作区，确认合并结果后，使冲突项两端内容和执行位一致，再重跑原命令。同步中断后可用原命令重试。移出清单的旧文件保留在主题中，由主题团队决定是否清理。

## 校验范围

| 命令或选项 | 检查内容 |
|---|---|
| `python3 .agents/scripts/verify-changes.py` | 检查已暂存、未暂存及新增文件。保护规则覆盖删除和重命名两端。主题配置、模板、section group、locale 支持注释和尾逗号；其他 JSON 使用严格语法。 |
| `--staged` | 从 Git index 读取文件。需要 Node 测试或 Theme Check 时导出完整暂存快照，复用本机已安装的根 `node_modules`。 |
| `--base origin/main` | 在本地比较当前工作树与目标分支的差异，以目标分支和 HEAD 的共同祖先为基准。运行前先获取目标分支及其历史。 |
| `--theme-check` | 有主题文件或 Theme Check 配置变更时，以完整主题运行 Shopify CLI。报告变更文件上的诊断；若未改文件报错，按需对照 Git 基线，保留未改调用方上的新增错误，汇总历史错误。CLI 执行异常会使校验失败。 |
| `--skip-tests` | 跳过主题根 `tests/` 下的 `*.test.js`、`*.test.cjs`、`*.test.mjs`。其他测试入口由主题团队维护。 |

通用版默认采用目标主题的样式组织方式。需要保护特定路径或限制新增 Liquid stylesheet 标签的团队，可以在主题根目录维护 `.agents/shopify-harness-policy.json`。通用安装器把该文件留给团队。两个可选字段及格式如下；路径按仓库相对路径匹配，忽略大小写。

```json
{
  "protected_paths": ["snippets/analytics*.liquid"],
  "forbid_new_stylesheet": true
}
```

EcoFlow 版自动安装自己的策略。已获授权的例外可分别使用 `--allow-protected` 和 `--allow-stylesheet`，校验输出会记录例外。后台 custom pixel 或 GTM 容器的授权由团队另行管理。

## 维护 harness

- `manifest.txt` 管理公共主题规则、脚本和技能；`profiles/ecoflow/manifest.txt` 追加专属文件，支持“主题目标路径 => harness 源路径”。根 `AGENTS.md` 供本仓库维护者使用。
- 主题自己的项目地图、测试、店铺配置和原始性能报告在主题中维护。公共性能测量方法和 EcoFlow 案例分别分发。
- 提交前在 harness 根目录运行 `python3 -m unittest discover -s tests -v`。回归测试使用临时 Git 主题。要在本地运行完整套件，请确保 Node.js 和 Shopify CLI 都在 PATH 中。缺少其中一项时，对应测试会显示为跳过。
