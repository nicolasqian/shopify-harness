# Shopify Harness 维护约定

本仓库维护供 Shopify 主题使用的代理规则、技能、检查脚本和同步器。使用中文与维护者沟通，遵循本次任务范围，保留已有工作区改动。创建分支、提交或发布需要维护者明确要求。

- 公共主题规则位于 `.agents/shopify-harness.md`，公共分发清单位于 `manifest.txt`。
- EcoFlow 的根入口、校验策略、组件别名和历史案例位于 `profiles/ecoflow/`。保留无参数配置选择时的旧同步命令、忽略路径保护及旧基线兼容性。
- 修改安装或校验逻辑时用临时 Git 主题验证首次安装、升级和冲突。使用真实主题时优先只读检查及 `--dry-run`。
- 运行 `python3 -m unittest discover -s tests -v`。变更涉及 Shopify CLI 时核对真实 CLI 测试结果。测试不得接触店铺或改写用户主题。
