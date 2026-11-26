# EcoFlow Shopify 主题

先读取主题根目录相对路径 `.agents/shopify-harness.md` 中的公共开发规则。以下约定适用于本主题。

- 默认使用中文沟通。交互优先沿用主题已有的 Alpine.js 模式。
- 开始较大改动前说明检查范围。创建分支、提交或修改已有提交须由用户明确要求。
- `ecoflow-tech` 对应 EcoFlow US。定位组件时优先读取本站的 `docs/project-map.md`；分析 LCP 时按需读取 `docs/lcp-optimization-reference.md` 和 `docs/lcp-loading-map.md`。这些文档由主题项目维护，缺失时从实际模板、section 和 layout 追溯。
- 修改 dataLayer 系列 Liquid、Shopify custom pixel 或对应 GTM 容器前，需要用户对相应代码的明确授权。通用功能和性能任务均不会自动授予这些权限。文件级检查的实际范围见 `.agents/shopify-harness-policy.json`。
- 本主题默认禁止新增 Liquid stylesheet 标签。沿用已有组件的 CSS 资产，在编辑器或首屏使用同步加载，以下区块按实际布局异步加载。已有实现使用 `request.design_mode` 和 `section.index <= 2` 判断，单实例的小段样式也可沿用内联方式。
- 预览前先检查当前浏览器中已有的本地主题预览，确认版本和页面后复用。需要预览时使用用户提供的有效链接。
- 按配置的 PDP 编辑器别名提取组件时，默认取主类型；需要同时列出同组变体时使用 `--include-variants`。顺序按模板 `order`，计入已禁用的实例。
- 需要对照本站轮播、首屏、购物车或第三方脚本的历史实验时，按需读取 `.agents/skills/shopify-performance/references/ecoflow-lessons.md`。调整 App、GTM、ConsentManager 或 Preciso 时沿用相应授权；暂停的页面和第三方策略按当前任务范围处理。
