# 第三方业务系统连接器

状态：partially implemented（工程测试通过，外部系统真实接入未验证）
类型：feature
Owner：backend/package/yuxi/services/connectors/, backend/package/yuxi/agents/connectors/, web/src/components/extensions/

## 问题

Yuxi 平台当前支持智能体对话、工作流编排和知识库检索，但缺少与企业内部业务系统（CRM、ERP、OA、库存管理等）的结构化集成能力。住户需要在以下场景中连接自有系统：

1. **Agent 对话查询**：智能体在对话过程中实时查询 CRM 客户信息、库存状态等
2. **工作流编排**：多步骤业务流程跨系统协调（如"查询客户 → 生成方案 → 回写 CRM"）
3. **系统回写**：智能体或工作流向外部系统写入数据（如创建工单、更新订单状态）

现有系统能力分散：
- **MCP Server**：可包装外部系统为 LangChain Tool，但需要为每个系统单独开发 MCP Server
- **HTTP 工作流步骤**：可调用外部 API，但无凭据管理、无适配器抽象、无审计
- **Skill 系统**：可打包工具和 MCP 依赖，但不直接封装业务系统连接
- **渠道系统**：已实现多供应商 IM 集成（飞书/钉钉/企微），但仅用于消息收发

缺少统一抽象会导致：
- 每个新系统需要从零开发，无法复用凭据管理、HTTP 客户端、审计日志
- 管理员无法通过配置界面接入新系统，必须编写代码
- Agent 和工作流两条消费路径各自实现，重复且不一致
- 凭据分散存储，无统一加密和访问控制

## 提案

引入"连接器"（Connector）作为业务系统集成的统一抽象。连接器封装外部系统的认证、API 调用和数据转换，对上层提供标准化工具接口。

**术语规范**：
- **连接器**：业务系统集成（CRM、ERP、OA 等）
- **渠道**：消息/IM 平台（飞书、钉钉、企微等）

**核心设计原则**：
1. **配置优先**：管理员通过 UI 配置接入新系统，无需编写代码（通用 REST 适配器）
2. **复用现有基础设施**：不新建执行引擎，Agent 路径复用 Tool 注册系统，工作流路径复用现有步骤编排；HTTP 客户端复用知识库 SSRF 防护原语
3. **凭据安全**：使用 Python `cryptography.fernet` 加密存储（环境变量 `CREDENTIAL_ENCRYPTION_KEY`），API 不返回明文
4. **双消费路径**：Agent 对话（动态注入为 LangChain Tool）+ 工作流编排（新增 connector 步骤类型）
5. **写操作安全**：写操作走 prepare → approve → execute → reconcile 审批流，不直接执行
6. **权限隔离**：每个连接器操作声明 `read_scope` / `write_scope`，复用现有 `yuxi.permissions` 模式，最终授权在后端 service 层 fail-closed

### 实现方案

#### 一、数据模型层

新增五张表，复用现有 schema 迁移机制，schema 版本从 `19` 递增到 `20`：

**1. `connectors` 表**：连接器实例定义
- `id`, `slug` (UNIQUE), `name`, `description`, `connector_type` (`generic_rest` / `salesforce` / `feishu_bitable_crm`), `config` (JSON), `enabled`, `created_by`, `updated_by`, `created_at`, `updated_at`

**2. `connector_credentials` 表**：凭据加密存储
- `id`, `connector_id` (FK), `credential_key`, `credential_value` (BYTEA, Fernet 加密), `UNIQUE(connector_id, credential_key)`

**3. `connector_operations` 表**：预定义操作
- `id`, `connector_id` (FK), `slug`, `name`, `description`, `operation_type` (`read` / `write`), `http_method`, `endpoint_template` (支持 `{{variable}}` 模板), `request_schema` (JSON Schema 验证入参), `response_mapping`, `read_scope`, `write_scope`, `UNIQUE(connector_id, slug)`

**4. `connector_usage_logs` 表**：审计日志
- `id`, `connector_id` (FK), `agent_slug`, `workflow_id`, `run_id`, `operation_slug`, `request_payload`, `response_status`, `response_payload`, `duration_ms`, `created_at`

**5. `connector_operation_attempts` 表**：执行尝试与崩溃恢复
- `id`, `connector_id` (FK), `operation_slug`, `logical_call_key` (UNIQUE, 去重约束), `status` (`pending` / `preparing` / `waiting_approval` / `approved` / `executing` / `succeeded` / `failed` / `reconciled`), `owner_id`, `owner_attempt`, `lease_expires_at`, `request_payload`, `response_payload`, `created_at`, `updated_at`

`connector_operation_attempts` 的 `logical_call_key` 唯一约束实现幂等去重：相同调用不会产生重复执行。`owner_id`、`owner_attempt` 和 `lease_expires_at` 提供崩溃恢复能力——worker 崩溃后，新的执行者可获取过期 lease 并继续或标记失败。

工作流状态模型扩展两个新状态：`waiting_agent`（等待 Agent 提供输入）和 `waiting_approval`（等待管理员审批写操作），与现有 `connector_operation_attempts.status` 对齐。

迁移涉及以下修改点：
- `backend/package/yuxi/storage/postgres/manager.py` — `BUSINESS_SCHEMA_VERSION` 改为 `20`，`ensure_business_schema()` 新增 5 张表的 `CREATE TABLE IF NOT EXISTS` 语句
- `backend/package/yuxi/storage_migration.py` — `upgrade_from` 元组追加 `(19, 20)`，`BUSINESS_SCHEMA_VERSION` 改为 `20`

#### 二、SSRF 防护复用

知识库子系统已在 `knowledge/utils/url_fetcher.py` 实现完整的 SSRF 防护原语：DNS 解析校验、私网地址拦截、云元数据服务封锁、`SSRFGuardBackend`（httpcore 网络后端）和 `SSRFGuardTransport`（httpx 传输层）。

连接器模块提取共享 HTTP 工具到 `yuxi/utils/outbound_http.py`：
- 从 `url_fetcher.py` 提取 `resolve_hostname_addresses`、`is_blocked_address`、`assert_no_blocked_address`、`SSRFGuardBackend`、`SSRFGuardTransport` 到共享模块
- `url_fetcher.py` 改为从 `yuxi/utils/outbound_http.py` 导入这些原语，保持原有 `fetch_url_content` 行为不变
- 连接器适配器使用 `SSRFGuardTransport` 创建 `httpx.AsyncClient`，复用同一套 DNS 校验和私网拦截逻辑

HTTP 客户端统一使用 `httpx/httpcore`（与现有 SSRF 基础设施一致），不引入 `aiohttp`。

#### 三、Service 层与适配器模式

**目录结构**：
```
backend/package/yuxi/services/connectors/
├── __init__.py
├── base.py              # ConnectorAdapter 基类
├── registry.py          # 适配器注册表
├── service.py           # ConnectorService CRUD + 执行
├── repository.py        # 数据库 CRUD
├── credential_vault.py  # 凭据加密/解密
└── adapters/
    ├── __init__.py
    ├── generic_rest.py       # 通用 REST 适配器
    ├── salesforce.py         # Salesforce 适配器
    └── feishu_bitable_crm.py # 飞书多维表格 CRM 适配器
```

**ConnectorAdapter 基类**定义 `execute_operation`、`list_operations`、`test_connection` 三个抽象方法。所有适配器通过 `httpx.AsyncClient(transport=SSRFGuardTransport())` 发起外部请求。

**三个预置适配器**：
- `generic_rest`：管理员通过 UI 配置 `base_url`、`auth_type`、`headers`，操作定义存储在 `connector_operations` 表，支持模板变量替换和 JSON Schema 入参校验（使用 `jsonschema` 库）
- `salesforce`：Salesforce REST API 适配，封装 OAuth2 / Session ID 认证
- `feishu_bitable_crm`：飞书多维表格 CRM 适配（基于飞书多维表格 API，非飞书 CRM API），封装 tenant_access_token 认证和多维表格记录读写

**适配器注册**：模块加载时通过 `register_adapter(connector_type, adapter_cls)` 注册到全局注册表。

**ConnectorService** 核心职责：
- CRUD 管理连接器配置和凭据
- 执行操作时加载配置、解密凭据、实例化适配器、记录审计日志
- `get_connector_tools()` 将连接器操作转换为 LangChain Tool 供 Agent 使用
- 写操作走 `prepare → approve → execute → reconcile` 流程：先创建 `connector_operation_attempts` 记录（status=`preparing`），管理员审批后（status=`approved`）才执行，执行后进入 `reconciled` 终态

**凭据加密**：使用 `cryptography.fernet.Fernet`，密钥从环境变量 `CREDENTIAL_ENCRYPTION_KEY` 读取，密文以 BYTEA 存储。API 响应只返回 `credential_keys` 列表，不返回明文值。

**新增依赖**（添加到 `[project].dependencies`）：
- `cryptography>=48.0.1`（凭据加密）
- `jsonschema`（通用 REST 适配器入参校验）

#### 四、Agent 消费路径

**目标**：Agent 在对话中自动获得已配置连接器的工具能力。

关键修改点：
1. `BaseContext`（`@dataclass(kw_only=True)`）新增 `connectors: ResourceSelection` 字段
2. `resolve_agent_resource_options()` 新增 `connectors` 分支
3. `merge_agent_config_json()` 的 `_RESOURCE_FIELDS` 集合新增 `"connectors"`
4. `resolve_configured_runtime_tools()` 加载连接器工具：解析 connector slugs，调用 `connector_service.get_connector_tools(slug)` 为每个操作生成 `@tool` 包装函数
5. Agent 配置 UI 新增连接器选择（在 Agent 运行时配置表单中增加连接器 Tab）

**权限校验**：Agent 调用连接器工具时，service 层校验当前 Agent 是否拥有该操作的 `read_scope` 或 `write_scope`，fail-closed。

#### 五、工作流消费路径

**目标**：工作流编辑器新增"连接器"步骤类型，可视化调用连接器操作。

关键修改点：
1. 新增 `ConnectorStepExecutor`（`backend/package/yuxi/workflows/executors/connector_executor.py`），签名与现有 executor 一致：`execute(step_data: dict, context: dict, *, db_session=None)`
2. `workflows/executors/__init__.py` 的 `_init_executor()` 注册 `connector` 步骤类型
3. 工作流编辑器 UI 新增连接器步骤配置面板（选择连接器、操作、参数）
4. VueFlow 节点注册：使用 `@lucide/vue` 图标（与项目现有图标库一致），不使用 `ApiOutlined`

**写操作审批**：工作流执行到写操作的 connector 步骤时，步骤状态进入 `waiting_approval`，等待管理员在管理界面审批后继续执行。

#### 六、前端管理界面

**目标**：管理员通过 UI 配置和管理连接器。

管理入口位于 `/extensions?tab=connectors`（现有扩展页面的新 Tab），不重命名 `SkillsConnectorsView.vue`。

关键修改点：
1. 现有扩展页面 Tab 列表新增 `{ key: 'connectors', label: '连接器' }`（仅管理员可见）
2. `activeChildLoading` refMap 新增 `connectors` 条目
3. 新增 `ConnectorCardList.vue`：连接器列表，支持创建、编辑、启用/停用、测试、删除
4. 新增 `ConnectorConfigModal.vue`：连接器配置弹窗，按 `connector_type` 动态渲染配置表单
5. 前端图标统一使用 `@lucide/vue`

API 路由复用渠道系统的鉴权模式（`Depends(get_admin_user)` + `Depends(get_db)`），前缀 `/system/connectors`。

## 替代方案

- **只用 MCP Server**：为每个系统开发独立 MCP Server，灵活但开发成本高，管理员无法自助配置
- **只用 HTTP 工作流步骤**：扩展现有 HTTP 步骤支持凭据引用，但缺少操作抽象和审计
- **只用 Skill 打包**：将连接器封装为 Skill，但 Skill 侧重能力分发而非运行时集成
- **新建执行引擎**：为连接器设计独立执行引擎，但会重复 HTTP 客户端、凭据管理和审计逻辑
- **凭据明文存储**：沿用渠道系统的 JSON 列，但存在安全风险
- **使用 aiohttp**：独立引入 aiohttp 作为 HTTP 客户端，但会重复知识库已有的 SSRF 防护实现，增加维护面和安全审计成本
- **前端硬编码适配器**：每新增一种系统类型就开发专用 UI，但扩展性差

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 管理员可通过 UI 创建通用 REST 连接器并测试连接 | 凭据未加密存储、API 返回明文、测试连接不验证真实端点 | ConnectorService、CredentialVault、connector_router | 真实 HTTP/PostgreSQL integration：创建连接器后回读凭据列为 BYTEA，API 响应只含 credential_keys | 错误凭据测试连接失败且返回结构化错误，不暴露异常栈 | 工程测试通过（unit + integration + E2E）；真实浏览器未验证 |
| Agent 对话中可自动调用已配置连接器的只读操作 | 工具未注入、操作参数未传递、审计日志缺失、权限未校验 | resolve_configured_runtime_tools()、ConnectorService.get_connector_tools()、connector_usage_logs | 真实 Agent run：发送"查询客户 X"，回读 usage_logs 表含该次调用；Agent 无 scope 时工具调用被拒 | Agent 未配置连接器时不注入任何连接器工具；无 read_scope 的 Agent 调用被拒 | 工程测试通过（unit + E2E）；LLM 未调用工具时 skip |
| 工作流可编排跨系统只读流程 | connector 步骤未注册、模板变量未替换、步骤失败无处理 | ConnectorStepExecutor、WorkflowEngine、connector_operations | 真实工作流 run：执行"查询 CRM → 生成报告"，回读 steps 表含两步结果 | 连接器不可用时工作流步骤明确失败，不静默跳过 | 工程测试通过（unit + E2E） |
| 写操作走审批流且不直接执行 | 写操作无审批直接执行、审计日志缺失、状态转换不正确 | connector_operation_attempts、ConnectorService、审批流程 | 真实工作流 run：执行"更新商机"，回读 operation_attempts 表含 prepare → waiting_approval → approved → reconciled 完整状态链 | 未经审批的写操作不产生外部 HTTP 调用 | 工程测试通过（unit + integration）；真实审批流程未验证 |
| 凭据加密存储且 API 不返回明文 | 加密密钥泄露、API 响应含 credential_value、数据库列类型为 TEXT | CredentialVault、ConnectorResponse schema、connector_credentials | 真实 HTTP integration：API 响应只含 credential_keys，数据库列类型为 BYTEA | 直接查询数据库无法读取明文凭据 | 工程测试通过（unit + integration） |
| 去重约束阻止重复执行 | 同一操作被并发触发多次、logical_call_key 未生效 | connector_operation_attempts UNIQUE 约束 | 真实 PostgreSQL integration：相同 logical_call_key 的第二次插入触发唯一约束冲突 | 相同 call_key 的并发请求只有一个被执行 | 工程测试通过（integration） |
| 崩溃恢复：lease 过期后新执行者可接管 | owner_id 未设置、lease 未过期、恢复后状态不一致 | connector_operation_attempts (owner_id, lease_expires_at) | 模拟 worker 崩溃：设置过期 lease，新 worker 获取 lease 并完成执行或标记失败 | lease 未过期时其他 worker 不能接管 | 工程测试通过（unit） |
| SSRF 防护覆盖连接器 HTTP 调用 | 连接器可访问内网地址、云元数据服务未被拦截 | yuxi/utils/outbound_http.py、SSRFGuardTransport | 真实 integration：配置 base_url 为 `http://169.254.169.254/` 的连接器，测试连接返回 SSRF 拦截错误 | 合法公网地址正常访问不受影响 | 工程测试通过（unit + integration） |
| 管理界面位于 /extensions?tab=connectors | Tab 未显示、非管理员可见、图标不一致 | 扩展页面 Tab 配置、用户权限 | 真实浏览器：管理员在扩展页面可见连接器 Tab 且图标来自 @lucide/vue，普通用户不可见 | 普通用户无法看到连接器 Tab | 前端组件已实现；真实浏览器未验证 |

## 风险

**凭据安全**：加密密钥 `CREDENTIAL_ENCRYPTION_KEY` 必须通过环境变量注入，不能提交到代码库。密钥丢失会导致已存储凭据无法解密。建议生产环境使用密钥管理服务（如 Vault、AWS Secrets Manager）。

**Schema 迁移**：新增 5 张表需要 `BUSINESS_SCHEMA_VERSION` 从 `19` 递增到 `20`。迁移脚本使用 `CREATE TABLE IF NOT EXISTS` 保证幂等性。现有迁移机制不支持回滚，新增表一旦提交到生产环境只能通过 `DROP TABLE` 手动撤销。

**SSRF 共享提取**：从 `knowledge/utils/url_fetcher.py` 提取共享原语到 `yuxi/utils/outbound_http.py` 是跨模块重构，需要确保知识库原有 `fetch_url_content` 行为完全不变。提取后 `url_fetcher.py` 改为导入共享模块，需验证知识库解析和连接器两条链路均不受影响。

**性能**：高频调用连接器可能成为瓶颈。`connector_usage_logs` 表会快速增长，需要定期归档或分区。建议初期按 `created_at` 月份分区，后续引入 ClickHouse 等分析型数据库。

**写操作风险**：回写外部系统（如更新 CRM 订单）失败时，Yuxi 侧无法回滚。审批流程（prepare → approve → execute → reconcile）提供人工确认环节，但执行后的外部系统回滚仍由外部系统负责。`connector_operation_attempts` 的 `reconciled` 状态记录最终结果，不保证外部一致性。

**适配器维护**：预置适配器（Salesforce、飞书多维表格 CRM）依赖第三方 API 版本。API 变更时需要更新适配器代码。通用 REST 适配器可缓解此问题，但牺牲了易用性。注意飞书多维表格 CRM 与飞书 CRM API 是不同产品，适配器基于多维表格 API 实现。

**并发控制**：同一连接器的并发调用可能导致外部系统限流。`connector_operation_attempts` 的 lease 机制提供崩溃恢复，但初期不引入全局并发限制（如 asyncio.Semaphore），待真实场景驱动。

**依赖新增**：新增 `cryptography>=48.0.1` 和 `jsonschema` 到 `[project].dependencies`。`cryptography` 是成熟的加密库，`jsonschema` 用于通用 REST 适配器的入参校验。两个依赖均不引入新的系统级要求。

## 实施状态

### 已完成（工程测试通过）

- **数据模型**：5 张表（connectors、connector_credentials、connector_operations、connector_usage_logs、connector_operation_attempts）已实现并迁移（schema 19 → 20）
- **凭据保险库**：Fernet 加密存储，API 不返回明文
- **SSRF 防护**：提取共享原语到 `yuxi/utils/outbound_http.py`，知识库和连接器共用
- **Service 层**：CRUD、执行、审计日志、去重、lease 恢复
- **管理 API**：`/api/system/connectors` 路由，管理员鉴权
- **三个适配器**：generic_rest、salesforce、feishu_bitable_crm（工程实现，未接通真实外部系统）
- **Agent 消费路径**：动态工具注入、权限校验
- **工作流消费路径**：ConnectorStepExecutor、步骤注册
- **前端管理界面**：ConnectorCardList、ConnectorConfigModal、ConnectorOperationEditors 等组件
- **CI 集成**：unit / integration / E2E 测试步骤已添加到 `system-tests.yml` 和 `test.yml`
- **用户文档**：`docs/advanced/third-party-connectors.md`

### 未完成（交付未闭合项）

- **Salesforce 真实外部接入**：无测试账号，适配器工程测试通过但未验证真实 API 调用。在交付中列为"未完成接入验收"
- **飞书多维表格 CRM 真实外部接入**：无测试 Base/表/字段，适配器工程测试通过但未验证真实 API 调用。在交付中列为"未完成接入验收"
- **真实浏览器验收**：前端组件已实现，但未在真实浏览器中验证管理员完整操作流程和普通用户权限隔离
- **写操作真实审批流程**：工程测试覆盖了状态机转换，但未通过真实浏览器完成管理员审批操作

工程测试通过与外部接入通过分别报告，不互相冒充。
