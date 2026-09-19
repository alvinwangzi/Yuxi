# 文档约定

修改本目录时应用根 [AGENTS.md](../AGENTS.md)，并按[文档编写与维护规范](develop-guides/documentation-guidelines.md)读取对应的页面类型、写作和验证章节。纯阅读只取所需事实，不触发写作、决策或提交流程。

## 层级定位

每个事实只有一个完整 Owner，其他页面保留当前任务所需上下文和相对链接。先按[页面类型与目录职责](develop-guides/documentation-guidelines.md#信息架构与事实-owner)确定位置。系统边界和主链路属于根 `ARCHITECTURE.md`，测试层级和命令属于[测试规范](develop-guides/testing-guidelines.md)，工程信任闭环属于[工程信任系统](develop-guides/engineering-trust.md)，非显然取舍属于 `decisions/`，事故因果属于 `postmortems/`，已发布变更属于 changelog，未完成方向属于 roadmap。`docs/vibe/` 是本地临时计划，不被跟踪。源码、schema、Compose 和数据约束拥有可执行事实；外部资料和 Agent 自述只帮助定位，不覆盖当前 Owner。

## 写作入口

1. 定位读者、任务、前置条件、完成标准和非目标，确定页面类型；非平凡信息架构或长期约束先建立 proposed decision。
2. 沿入口 → service/executor → repository/持久化或发布点 → 用户或模型可见结果重建真实链路，核对权限、失败路径、可选能力和相关测试。
3. 一次只撰写或重写一个 Section，完成后核对事实、相对链接和相邻章节重复。先更新事实 Owner，再更新导航和入站链接。
4. 提交前运行最小相关 gate，由不继承开发上下文的 Reviewer 对照完整需求、源码、diff、测试和未验证范围审查。

详细写作规则按页面类型读取[文档编写与维护规范](develop-guides/documentation-guidelines.md)对应章节。

## 导航与预算

- 新增正式页面更新 `.vitepress/config.mts` 的正确父级和阅读顺序；内部 `AGENTS.md`、decision 与 postmortem 不因位于 `docs/` 就自动成为用户导航入口。
- `scripts/verify_engineering_contracts.py` 的 AGENTS 字符预算是 standing-order guardrail。超限时先下沉示例和背景再压缩重复；确需提高预算时同步更新 decision 和 gate，不能静默删掉必要约束或关闭检查。
- 修改配置、API、状态、权限或机制说明时检查相关测试；文档构建只证明 Markdown、导航和链接有效，不证明语义正确。构建失败修正文档、锚点或导航，不扩大 `ignoreDeadLinks` 掩盖问题。

验证命令在[测试规范](develop-guides/testing-guidelines.md)统一维护。
