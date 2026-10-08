# 第三方业务系统连接器

状态：proposed
类型：bug-fix
Owner：backend/package/yuxi/services/connectors/service.py

## 问题

Agent 和工作流需要通过企业集成账号查询、更新业务系统，平台必须同时约束谁可以执行、实际发出哪份请求，以及失败后如何确认副作用。已有连接器候选只完成部分模块：运行类型目录为空，调用准备存在 NameError，审批控制信号回滚账本，执行缺少最终权限与版本绑定，工作流将等待当完成，Agent 模式仍直接调用模型。局部测试通过不能证明完整链路可用。

目标是通用 REST、Salesforce、飞书多维表格 CRM 的管理与双消费路径，在真实授权、持久审批、可恢复执行、网络边界和结果回读上形成闭环。非目标为全平台权限重构、第二套队列、分布式事务、自动补偿及任意脚本适配器。

## 提案

沿现有 LangGraph、FastAPI、PostgreSQL、Redis 和工作流编排实现一个共用连接器执行服务。管理权与 read/write 执行权限分离；审批仅批准指定调用，不能替代最终授权。

### 实现方案

- `yuxi.services.connectors` 拥有管理用例、参数校验、prepare/approve/dispatch/finalize/reconcile；短事务正常退出后才中断、发布或 HTTP。`yuxi.repositories.connector_*` 拥有查询、唯一约束和 CAS，不解密、不 HTTP。
- `adapters` 显式装配内置类型，接收已验证冻结 config/operation/credentials，不查询 DB。`utils.outbound_http` 复用 DNS 与实际连接绑定；知识库保持公网策略，连接器同时验证 origin 和受控内网 CIDR，禁止自动重定向。
- 复用现有五张表：`connectors`、`connector_credentials`、`connector_operations`、`connector_usage_logs`、`connector_operation_attempts`。账本拥有 logical_call_key、身份/运行绑定、审批、结果、owner_attempt/lease；attempt 仅记录每次发送，不作为第二套最终状态。删除保留历史和去重 tombstone。
- `yuxi.permissions` 公开连接器 scope 判断；prepare、决定、dispatch、结果读取都检查有效用户、当前 scope 与归属。dispatch 在 owning transaction 校验 enabled、版本、批准期限和并发槽位，提交后按冻结请求执行。写结果可能不确定时记录 unknown，不因 timeout 伪造 failed。
- `agents/connectors/tools` 从可信 runtime 获取真实 tool_call_id，prepare commit 后执行 LangGraph interrupt。恢复复用原 invocation/thread/checkpoint；Model/ToolMessage 与真实 Request/Run 对齐。
- 工作流使用独立可信 execution context、持久 activation 标识与 definition/resume 快照。waiting_agent/waiting_approval 属于活跃状态；保存当前层后释放 worker，以 generation/CAS 恢复，既有完成写步骤不重跑。`workflow_agent_service` 经正式 AgentRequest/FIFO/Run 接入工具图，model_spec 保持轻量模型路径。
- 前端 API 统一在 `web/src/apis`；`ExtensionsView` 管理连接器，实际 Agent 表单与 WorkflowEditor 消费权限过滤目录。操作、审批和核对组件必须有可达入口，DOM 显示以后端持久事实为准。
- 凭据和恢复材料用 Fernet/key_id 加密，显式 key ring 轮换；缺少密钥以结构化不可用或 required readiness 失败表达。Schema 只由 storage-migrator 幂等升级，ORM/DDL/时间类型一致，旧空身份和不完整批准不能自动执行。

### 边界和维护

当前执行候选作为拒绝样本保留。修复在隔离工作树/运行槽位完成，避免热加载一个“补 import 后就能无授权写入”的中间状态。schema 版本以 manager 为唯一来源；需要修改持久契约时升级到未占用的下一版本。

工作流状态的服务/仓储/worker/API/SSE/浏览器消费者同批接线。connector 恢复纳入实际 worker 周期机制，过期 owner 不能覆盖当前结局。未知远端写结果需要独立只读回查或有证据人工核对。

## 替代方案

- 每系统独立 MCP Server：可复用已有工具消费，但不满足管理员配置、集中凭据、同一授权/审计与工作流消费要求。
- 仅在 HTTP executor 添加认证：路径短，但不能形成 Agent 消费、批准绑定、稳定去重和崩溃结局。
- 只补缺失 import 和类型目录：会激活已有未保护写路径；拒绝作为单独部署候选。
- connector 自建网络实现：重复 DNS/TLS 安全边界；采用共享连接原语并保持两个 consumer 的不同策略。
- 依赖前端/prompt 审批：替代调用可绕过；采用后端执行与持久批准。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| shipping 目录包含三类适配器 | 测试 import 偶然注册 | services/connectors/adapters、factory、API/worker 装配 | 新进程、真实 /types 与 DOM | 不预先 import adapters | Passed |
| 当前 actor 有权执行/决定 | deny、删除用户、跨用户批准、伪造 context | permissions、service、repository | 真实 PG/HTTP 授权测试与 provider 收包 | 拒绝情况下零副作用 | Passed |
| 审批先持久化且绑定版本 | rollback、旧批准执行新请求 | service、账本约束 | commit 后新 session 回读，PG 竞态 | 参数/版本/期限/权限变化 | Passed |
| 重复投递与失联可观察 | 随机调用键、双写、永久 running | execution repository、recovery/worker | PG UNIQUE/CAS、Redis/ARQ、provider mutation | claim 前后崩溃、迟到 owner | Passed |
| HTTP 不越界且内存有界 | 错端口、307 越界、解压后超限 | outbound_http、http_client | 两 origin 的真实 HTTP 与知识库回归 | DNS 重绑定、错误 origin、大响应 | Passed |
| 写后超时保持 unknown | 已写误报 failed 或盲重发 | adapters、service/reconcile | 独立 provider 先写后断连/回查 | 无可靠结局不能重放 | Passed |
| Agent 正式工具链路闭合 | 未调用工具也报绿、错 Run | Agent Request/Run、tools | deterministic assembled E2E/ToolMessage | 无调用、跨 Run 绑定、批准失效 | Passed |
| workflow 7a/7b 正式恢复 | waiting 当完成、父占槽、纯模型 fallback | engine、workflow service/repo、Agent bridge、worker | 1-slot ARQ/PG 与完整 E2E | 并行审批、循环、取消、重投递 | Passed |
| UI 可完成管理和消费 | 类型空、操作/审批无入口 | 实际 Vue 消费入口、apis | 浏览器+API+PG/provider 回读 | 409/权限/empty/error/断线 | Passed |
| Schema/密钥兼容 | 版本伪装、覆盖旧 key、密文不可解 | storage-migrator、vault/轮换脚本 | v19/v20/new PG、轮换回读 | 中途失败、旧空绑定、并发写入 | Passed |
| 外部 Salesforce/飞书可用 | 仅 mock 认证或字段未绑定 | provider adapters | 测试组织/Base 的 read/write/readback | scope、业务 code、分页、字段错 | Not run |

测试层级与执行规则由 testing-guidelines 维护。CI 只读运行 oracle，expected output 不在 CI 生成；新增 guard 有恢复目标缺陷的负控。独立 Review 不替代数据库、协议和浏览器证据。

### 内部验证与接受边界

同 logical key 的并发 prepare 由 PostgreSQL 唯一约束仲裁，相同 digest 返回同一 invocation，不同 digest 返回业务冲突。Agent 工具保留组装时的 connector/operation revision，prepare 拒绝过期版本；工作流初次准备绑定当前配置，后续 dispatch 仍对照冻结版本。

直接连接器步骤的 unknown 进入持久 waiting_approval，pending binding 用 kind=reconciliation 区分人工核对。核对前不自动重发；管理员带当前 scope 和回查证据核对成功后恢复原 activation，读取同一 invocation 的加密结果，继续下游。拒绝或核对失败保持父失败；其他待项不能覆盖已确定的失败。飞书成功 business code 不能掩盖 HTTP 错误。

dispatch 已结束的 succeeded/failed/rejected/cancelled/unknown 不再需要执行快照，因此删除整个含凭据的 execution_snapshot_ciphertext；保留版本、digest、tombstone、加密 params/result 与 receipt 供去重和核对。当前消费路径没有终态快照 consumer，不引入永久凭据副本；存量历史材料及备份仍按受批准的保留策略处理。

恢复扫描保留 unknown 的待核对状态；从运行历史重开非终态详情继续轮询，关闭或切换详情后迟到响应不能覆盖当前运行。Agent 拒绝审批后恢复原工具得到 approval_rejected 受控结果，不产生第三方 HTTP；工作流拒绝仍使父运行失败，二者使用各自已有状态模型。

隔离 Compose 的连接器相关 unit、真实 PostgreSQL、HTTP、Vault/rotation、工作流暂停与正式 Agent bridge 完整集合持续复验，最后冻结候选的实际命令、数量与日志以源码外报告为准；历史集合有重叠，不相加，也不作为新候选的审查结论。新进程注册、同类型冲突拒绝、当前 scope/身份、并发审批、取消与 claim 提交边界、结果提交失败、迟到 owner、双表终态、加密错误证据、并行审批、循环激活、核对恢复不重复写、解压分配预算及读重试逐次授权均有对应负向 oracle。

真实管理 HTTP 与直接工作流、普通 Agent、工作流 Agent bridge 的 read/required write assembled 回归共 `14 passed`。使用真实 API、单槽位 ARQ worker、PostgreSQL checkpoint 和独立 HTTP/model replay，回读精确 Request/Run/ToolMessage/output、invocation/attempt 与远端 mutation；不允许零工具调用或失败自动 skip。三个 provider 在本地真实 HTTP 验证认证、标准操作、分页、业务错误、写后回读、错误分类及受控路径，不能替代外部组织/Base。

浏览器通过正常登录和 UI 操作完成 REST CRUD、操作 PATCH/revision 与删除自身 fixture，并回读 HTTP 保存结果；覆盖桌面、窄屏、真实深色主题、类型 503 注入、禁止创建和重试恢复。新建和缺省读取/写入范围均为 deny，授权必须由管理员明确填写。显式配置失败不再静默丢弃；类型目录空值/失败不再显示为已加载。浅色/窄屏和操作管理截图在源码外，不提交账号、会话或测试数据。

真实 PostgreSQL 迁移矩阵包括 v19 缺表装配、v19/v20 naive UTC、当前新库、重复执行和版本失败回滚；无关 WorkflowStep 业务时间保持原契约。旧无效身份保留，迁移仅诊断约束和数量；旧 key 在相应材料处理前必须继续保留。Windows 与 Bash 初始化验证首次生成、幂等和半配对拒绝；Bash guard 位于根 scripts 原生 unittest，CI 宿主明确执行，不要求 backend 容器存在根脚本路径。rotation 验证 terminal/unknown 保留材料、dry-run、重跑和损坏批次回滚。

飞书字段逻辑键变更在管理事务内同步未自定义的标准操作 schema；自定义 schema 保留管理员限制，需显式编辑后才能使用新增字段。适配器拒绝不在当前 mapping 中的业务参数，不进行部分静默写入。管理 PATCH 显式 null 清空 description，非 nullable name/enabled 的 null 被拒绝；参数/Schema 错误不回显私有输入。连接器删除清除活凭据，已冻结调用仍保留自身加密证据与 tombstone。并行待项先检查全部失败，失败父保留子取消重试；正式 resume/worker claim 拒绝终态父，排队和中断子均可收敛。

CI 的路径 selector 和实际命令覆盖新增 unit、integration 与 bridge E2E，确定性 gate 不依赖 Salesforce/飞书凭据。CI 装配一个 worker 槽位，密钥不打印；源码接线只记 `Inspected`，远端 job 尚未执行，不能记 `Passed`。代码提交前仍需不继承开发上下文的全新 Reviewer 对冻结候选、完整需求/diff/oracle 和未验证边界审查。

全库基线问题没有被关闭或伪报通过。固定基线的前端全量为 `405 passed / 10 failed`，lint 为 20 errors；当前失败项逐一归因相同，修改前端的 lint 与 build 通过。固定基线后端 Ruff 有 207 diagnostics，当前剩余均为基线问题，新增 diagnostics 为零；相关模块 lint/format 通过。旧 Schema 测试在固定基线和当前均有相同五项失败（v0.7.2 结构断言与 resource-selection helper/版本契约），连接器 v21 的独立矩阵通过。工程契约检查由基线 32 errors 降为当前 18 个既有错误；Verifier unit 通过。文档构建排除内部 AGENTS 页面，保持真实 dead-link 检查，不扩大 ignoreDeadLinks。

本记录保持 proposed：内部连接器候选与全库 gate、远端 CI、目标环境和外部 provider 接受是不同主张。用户暂无 Salesforce 测试组织和飞书测试 Base，真实 read/write/readback 为 `Not run`；不推送、合并或共享部署，不宣称整体接受完成。

### 最后审查补齐的内部契约

HTTP 只请求 identity，允许单层 gzip/deflate 时用原始流和 zlib max_length 在分配前限制解压输出；未知编码、截断和额外 member 显式失败。真实 HTTP 压缩负控将 64 MiB 解压正文压到约 64 KiB，1 MiB 预算下旧候选峰值分配约 142 MiB，修复后的客户端峰值须小于 8 MiB；普通流仍在超限时停止读取并关闭。

飞书 query 的 filters 仅允许当前映射逻辑键、最多 16 个非空短字符串，以固定 and/is 条件转换为已发现的真实字段名，客户关联和状态也沿配置映射；不接受任意 filter DSL。分页参数留在 query，条件进入 records/search 请求体，依据[官方 SDK 请求契约](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/api/bitable/v1/model/search_app_table_record_request.py)和[字段条件契约](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/api/bitable/v1/model/condition.py)。本地协议验证不替代真实 Base 验收。

REST 的 retry_policy 仅允许 max_attempts：读取 1–3 次，写和 SaaS 均一次。只重试 429/502/503/504、超时或网络错误；每次都先提交前一 attempt 的响应事实，再重新校验当前 scope、版本和运行 Owner，提交下一 attempt 后才发送。远端幂等策略只支持两个专用 header 名，值来自持久 invocation ID，不采用调用者 UUID；不据此自动重试 unknown 写入或承诺远端 exactly-once。管理页保留这些可编辑策略。

审批、取消和核对的提交后通知由 connectors.consumer_service 拥有，router 仅装配请求与稳定响应；通知失败保留决定，由工作流持久恢复扫描补投递。模型 replay 的拒绝剧本必须显式声明 approval_rejected，并收到绑定 invocation 的 not_sent 工具结果，成功剧本仍拒绝该错误；MockTransport fixture 显式提供未读取 ByteStream，不通过生产 fallback 绕开原始流边界。

### 审批、认证与字段配置的最后拒绝边界

timeout_seconds 是整个 HTTP 响应与一次 invocation 所有认证、字段读取、重试的总预算，不为每次尝试重新计时。超时后读调用失败、写调用 unknown，未完成 attempt 结束；慢流每段及时到达也不能无限续租。启用配置必须有当前认证方式的完整凭据对，停用草稿可缺配；同 key upsert/delete 矛盾意图拒绝，删除必需凭据可在同一凭据事务明确 enabled=false。启用和重新准备也复核，不能沿历史缺配配置创建新调用。

Schema 的允许子集按 schema 节点检查，字段名是数据；本地引用在保存时展开并拒绝不存在的目标、循环和过深链。x-approval-visible/x-approval-target 是当前审批消费者使用的显式布尔注解，凭据命名字段禁止公开。冻结摘要显示完整有界目标、公开变更、变更字段、版本和有效期，未完整标注的动态请求不能批准；私人值仍只在加密参数中。预置操作由平台声明摘要字段，REST 由管理员在参数 Schema 显式标注，digest 继续绑定全部参数。

Salesforce upsert 的 account_external_id_field 由管理员配置，模型只能提供外部键值和受限业务字段，不猜默认字段，也不允许模型选择字段。飞书管理员可保存停用 Base 草稿和完整应用凭据，经独立管理用例只读发现同一 Base 的表与已选表字段；选择字段和调用参数名会保存真实 field ID/type，并同步未自定义的标准 Schema。启用前必须确认已映射字段类型，执行时仍以真实目录校验文本、数字、单/多选、毫秒日期、复选框和关联格式；不支持类型和错误值在业务写入前拒绝。目录响应、游标、表归属与总预算都有边界，普通用户不能调用管理发现入口。参考[官方表/字段模型](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/api/bitable/v1/model/app_table_field.py)与[官方记录值格式](https://github.com/larksuite/openclaw-lark/blob/main/skills/feishu-bitable/references/record-values.md)，真实 Base 接入仍未接受。

敏感 payload 维护清理在执行模式每批重新取缩小过滤集首批，dry-run 使用独立稳定排序游标；五条跨三批的真实 PG 回读证明不漏清理，unknown 与去重 tombstone 保留。不在共享环境运行破坏性演练。

审批可批准条件核对所有真实路径/query 变量，以及预置 SDK 操作的固定目标键，不能用无关公开标签代替隐藏的真实 record ID。管理写测试必须携带受校验 Idempotency-Key，逻辑调用键绑定当前 actor/connector/operation，参数变化返回 conflict；required 测试返回可恢复 invocation/digest/摘要，批准后同键继续，响应丢失重试不重复远端写。该链路以真实 HTTP、PG 与独立 POST 计数验证并纳入 CI。Salesforce 客户读取支持配置拥有的外部业务键等值查询，不忽略该过滤。工作流编辑器显示所选 schema 类型/必填、参数示例与写审批策略。

本人 invocation 回读必须重新校验当前 active actor、连接器/操作启用与 scope，且 Agent/Workflow Run 必须实际存在并由该用户可见；管理详情用当前管理角色并仅返回白名单摘要和 attempt，不解密私人结果。响应映射逐块检查独立输出预算，重复路径不能将有界输入放大为几十 MiB。飞书查询/读取仅输出配置字段，写回读仅交付本次修改字段，未映射列不进入 ToolMessage/工作流；记录身份与分页保留。

管理列表查询/类型筛选使用服务端分页，超过前100项仍有入口；调用详情展示 invocation、attempt、run绑定、版本、发送状态、时间和脱敏结果。操作/审批/usage 的请求 generation 防止切换与关闭后旧响应覆盖。测试与生产共享的 formatter、tool builder、interrupt payload 和 model replay helpers 使用公共命名，不跨模块导入私有实现。正式 owning 连接器说明同步到当前认证、审批、unknown 与不盲重发契约。

## 风险

存量 running 行的 owner_attempt 或 lease 缺失不被填成虚构 owner。恢复扫描锁定过期或失去 owner/lease 的行，使用数据库中的真实 owner 值（含 NULL/IS NULL）CAS，读失败、写 unknown，关闭同一 owner 的 attempt；以 owner_missing/lease_missing/lease_expired 区分诊断，不阻断同批正常行，不重发。

同 logical_call_key 的 failed/cancelled/running 回放返回账本原结局或进行中状态，不进入新的 dispatch；prepare 与 claim 间状态变化时也回读同一调用，不盲重发。终态失败有密文时回放同一次结果，没有 payload 的恢复或取消保留状态摘要；取消不补猜为未发送。Connector PATCH 名称沿创建的 1–128 字符边界在 HTTP 与 service 双层校验。

配置弹窗的启用、认证切换与 credential_patch 由同一 ConnectorService 管理事务保存，统一比较版本、加密并刷新凭据，再校验最终配置；凭据意图无效时配置与版本一并回滚。保留独立凭据 endpoint，其校验与组合保存共用同一私有 helper。wire JSON 的指数数字也校验有限性，飞书业务成功码要求严格整数，不能将 False 或 0.0 当作成功。

最终管理边界补齐带时区的调用日期上下界，列表与总数使用同一 repository 条件；反向或无时区日期显式拒绝。SaaS 的方法、路径、query/body 模板和响应类型由 provider adapter 拥有，管理 DTO 宣告归属、后端拒绝改变、UI 只读，schema/mapping/审批仍可按已有范围编辑。操作 enabled 必须是布尔值，嵌入创建中的停用值也真实落库。

容量只在 connector 锁内的 dispatch claim 原子判定，prepare 不承担无锁限流；每次失败释放事务后等待，最长五秒，恢复容量后重新验证 Owner、权限与版本再提交 attempt。读取重试加入短随机抖动，秒数或 HTTP 日期的 Retry-After 上限五秒，仍受一次调用的总 HTTP 预算约束。审批 watch 比较 invocation ID 内容，等值轮询不清空展示，新 ID 变化则使旧响应失效。

工作流 Agent 的未知写入与直接 connector 步骤拥有同等拒绝后果：ToolNode 中断等待核对，repository 独立检查当前激活的 unknown 写，即使模型或旧子 Run 已完成也不推进下游。核对成功后沿原调用结果与正式 Agent resume 恢复，不发送第二次写；preauthorized 写同样受此约束。

Salesforce 分页每次合并后检查总业务投影预算；读取与写后回查绑定目标 Id，15/18 位 ID 仅接受校验后缀正确的等价形式。upsert 回读同时验证配置拥有的外部键，receipt 带 id 时也必须匹配；读回不符保留已确认写 receipt，返回 readback_failed，不把另一记录当成功。总预算回归的端到端计时包含 PostgreSQL 领取与结局提交，墙钟上限显式由 1.35 秒调整至 1.8 秒，HTTP 预算仍为一秒，并保留独立服务收包仅两次、无第三次发送与 attempt 终态回读，避免用数据库提交耗时误判 HTTP 预算。

provider 页顶层、记录列表、终止布尔值和继续游标均在各 adapter 的 owning parser 校验；首批也受记录上限约束，合法空页必须有明确结构。总结果预算检查实际返回对象而非删减协议元数据的替代对象。飞书直接读取同样绑定请求 record_id。HTTP 公共 JSON parser 拒绝 NaN/Infinity、错误编码和过深 JSON；认证响应须是对象、token 为非空字符串，Salesforce instance_url 为字符串。错误认证响应仅产生认证收包，不能先将非字符串凭据拼成 bearer 再发送业务请求。

- 外部写不能随本地事务回滚，unknown 必须真实展示；不承诺 exactly-once。
- 冻结请求与权限撤销存在在途边界，以 dispatch claim 线性化，不声称能撤回远端请求。
- 旧批准缺身份/快照不可安全补猜；维护窗口内诊断后失效或核对，不批量重发。
- 密钥丢失不能解密已有数据；新旧 key 同时装配后才轮换，配置不进入日志/提交。
- 工作流 Agent bridge 扩展长生命周期；真实 FIFO、1-slot 等待、父取消与输出绑定为接受门槛。
- 共享网络提取失败先恢复知识库原行为，修复后复验；不放宽安全或复制 fallback 绕过。
- 缺外部账号不阻止内部开发，外部验收保持 Not run，整体完整接受不能提前声明。
