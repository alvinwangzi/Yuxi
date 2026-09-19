# Yuxi Agent 开发约定

Yuxi 是基于 LangGraph、FastAPI、Vue 的知识库与多智能体平台。Docker Compose 拥有开发拓扑，源码、数据约束与实际装配拥有当前行为。

## 按任务加载

本文件的安全与证据底线始终适用；实现、写作和提交要求只在对应阶段触发。链接只读取相关章节，已加载且未变化的材料无需重复读取。

| 当前任务 | 所需材料与边界 |
|---|---|
| 只读问答、定位、评估 | 直接相关的源码、配置或文档；不因阅读材料触发实现、决策写作或提交检查 |
| 启动、重载、排障 | 当前 Compose、日志、端口与 readiness；陌生链路查 [架构](ARCHITECTURE.md) 对应章节；共享环境、破坏性操作和权限变更先确认 |
| 修改代码或文档 | 对应子树 `AGENTS.md`、真实 Owner 与[测试规范](docs/develop-guides/testing-guidelines.md)的相关层级；修改陌生模块先读架构对应章节 |
| 非平凡变更 | [Spec Loop](docs/develop-guides/spec-loop.md)、[工程信任系统](docs/develop-guides/engineering-trust.md)与[决策记录](docs/develop-guides/decisions/README.md) |
| 提交或创建 PR | [贡献指南](docs/develop-guides/contributing.md)的对应阶段及[提交前检查](docs/develop-guides/testing-guidelines.md#提交前检查) |
| 并行分支、共享数据或 Schema 不兼容 | [隔离运行环境](docs/develop-guides/parallel-worktree-environments.md) |

修改 `backend/`、`web/`、`docs/` 时分别遵循其子树规则；子树只补充差异。用户当前明确要求优先于本文件，仍须遵守运行时权限与安全限制。技能只补充当前任务所需能力，同类流程选一套；项目规范决定文档落点和证据要求，技能或历史记忆不构成提交、推送或外部操作授权。

## 实现范围

- 实现前明确可验证目标、非目标和假设；多步任务给出简短步骤及验证方式。只有歧义会改变验收、数据、安全或外部状态时才阻塞询问。
- “可以”“例如”等表达只给出方向，不授权扩大范围。采用满足验收的最小线性实现；抽象、依赖、配置、fallback 和兼容路径必须有当前 consumer 与 Owner，真实用户、持久数据与部署承诺也算 consumer。
- 非平凡变更按 Spec Loop 建立或更新 tracked decision，保留问题、决定、替代、后果和验证。`docs/vibe/` 仅是被忽略的临时计划，不承载完成事实；不另建平行主张清单或 claim ID。
- 源码与数据约束拥有行为，独立 oracle 证明结果，实际 workflow 或可问责 Reviewer 形成拒绝后果。规范要求和行为证据分别核对，发现不一致时明确差距。
- 只修改验收所需范围，不顺手清理或格式化。实现明显过长时先简化；新增函数/类使用简洁中文 docstring，注释只解释非显然的约束、时序与安全原因。

## 安全与架构底线

完整链路见[架构不变量](ARCHITECTURE.md#架构不变量)；改变相关行为前读取对应章节。

- HTTP 路由保持薄，用例属于 `yuxi.services`，持久化查询属于 `yuxi.repositories`。
- 普通请求先持久化 Message 和 AgentRunRequest，仅 ready FIFO 队头创建 AgentRun；每次投递 ARQ 前 owning transaction 已提交。同一用户、Agent、线程串行派发，Request 与 Run 使用不同状态模型。
- PostgreSQL 拥有最终业务状态与唯一 LangGraph checkpoint；Redis 只负责投递、短期事件、取消和缓存。API、worker、Agent 不提供本地 checkpoint 后端或静默降级。
- 输出、事件、artifact、错误绑定同一 request/run，不从相邻 Run 猜结果；非终态 Run 有明确 Owner、lease/heartbeat 或等价机制及崩溃后的可观察结局。
- `/api/system/health` 只证明 liveness，`/api/system/ready` 证明接流量条件；业务正确性仍需真实链路验证。必要前置条件失败时显式失败，可选能力降级须结构化且可观察。
- 最终授权在后端依赖、repository 可见性查询及产生副作用的 executor/repository 执行并 fail-closed；前端、prompt 和 schema omission 不承担授权，替代调用路径也不能绕过。
- 不可信输入在 parser、配置、模型/tool JSON、持久化、worker、process、wire 与用户路径边界校验。沙盒路径、对象 URL、宿主路径不可混用，用户路径在 owning filesystem boundary 校验。
- Shipping 启动、路由与能力发现包含知识库、图谱和评估；附件 parser 仅在真实解析动作时惰性加载。
- 不输出或提交 `.env`、账号、Token、用户数据、运行目录和构建产物；保留用户未提交工作，破坏性操作与共享状态变更先确认。

## 验证与交付

- 从最小相关集合开始，按[测试规范](docs/develop-guides/testing-guidelines.md)升级；unit 不能替代真实 PostgreSQL、HTTP、worker 或浏览器语义。
- 回读数据库、文件、对象、DOM 或协议结果；Agent 自述、HTTP 200、日志关键词与 mock 次数不能单独证明完成。
- 新 guard 必须有恢复目标缺陷且因正确原因失败的负向案例；expected output、snapshot、fixture 只能显式更新并审阅，CI 不同时生成和验证 oracle。
- 代码变更 commit 前由不继承开发上下文的全新 Reviewer 审查完整需求、diff、测试和规范，修复影响功能、边界、证据或认知负担的问题；必要审查无法执行时如实报告。
- 提交前执行测试规范的必跑检查，文件保留一个末尾换行。提交信息用中文 Conventional Commit，PR 使用仓库模板，记录 Owner、实际命令、结果、风险和未验证范围；未验证不报通过。
