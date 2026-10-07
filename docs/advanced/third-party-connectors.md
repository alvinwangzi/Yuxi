# 第三方业务系统连接器

Yuxi 支持通过"连接器"将外部业务系统（CRM、ERP、OA 等）接入平台，让智能体和工作流能够查询和操作这些系统。

## 核心概念

- **连接器**：一个外部系统的配置实例，包含地址、认证方式和操作列表。
- **操作**：连接器下的具体 API 调用，分为只读（read）和写入（write）两种类型。
- **适配器**：连接器的执行后端，决定如何解析配置、发起请求和处理响应。

## 支持的连接器类型

| 类型 | 说明 |
| --- | --- |
| `generic_rest` | 通用 REST 适配器，管理员自行配置 base_url、认证方式和操作定义 |
| `salesforce` | Salesforce REST API 适配，封装 OAuth2 / Session ID 认证 |
| `feishu_bitable_crm` | 飞书多维表格 CRM 适配，基于飞书多维表格 API（非飞书 CRM API） |

## 创建连接器

管理员在 **扩展 → 连接器** 页面创建连接器。需要填写：

1. **基本信息**：名称、slug（唯一标识）、描述
2. **类型与配置**：选择连接器类型，填写对应配置（如 `generic_rest` 需要 `base_url`、`auth_type`）
3. **凭据**：API Key、Token 等敏感信息，加密存储
4. **操作定义**：每个操作的 HTTP 方法、端点模板、入参 Schema、响应映射

以 `generic_rest` 为例，配置 JSON：

```json
{
  "base_url": "https://crm.example.com/api/v1",
  "auth_type": "bearer_token",
  "default_headers": {
    "Accept": "application/json"
  }
}
```

操作定义示例（查询客户）：

```json
{
  "slug": "query_customer",
  "name": "查询客户",
  "operation_type": "read",
  "http_method": "GET",
  "endpoint_template": "/customers/{{customer_id}}",
  "request_schema": {
    "type": "object",
    "properties": {
      "customer_id": { "type": "string" }
    },
    "required": ["customer_id"]
  },
  "response_mapping": {
    "customer_name": "$.name",
    "customer_email": "$.email"
  }
}
```

## 凭据管理

凭据使用 `Fernet` 对称加密后存储在数据库中，加密密钥通过环境变量 `CREDENTIAL_ENCRYPTION_KEY` 注入。

- API 响应只返回凭据的 key 列表（`credential_keys`），不返回明文值
- 更新凭据时通过 PATCH 请求单独提交，不与连接器配置混在一起
- 密钥丢失会导致已存储凭据无法解密，生产环境建议使用密钥管理服务

## 智能体使用

在智能体配置中关联连接器后，智能体在对话中会自动获得对应操作的工具能力。

- 每个操作被转换为一个 LangChain Tool，智能体可根据对话上下文自动调用
- 工具名称格式：`cn_{连接器slug}__{操作slug}`
- 权限校验：智能体必须拥有操作声明的 `read_scope`（只读）或 `write_scope`（写入）才能调用
- 未关联连接器的智能体不会注入任何连接器工具

## 工作流使用

工作流编辑器支持添加"连接器"步骤，用于在流程中调用连接器操作。

步骤配置包含：

- **connector_slug**：目标连接器
- **operation_slug**：目标操作
- **params**：操作参数，支持 `{{变量}}` 模板引用上游步骤输出
- **output_key**：将操作结果绑定到工作流上下文

## 写操作审批

写操作（`operation_type: "write"`）默认需要审批，不会直接执行：

1. **准备**：系统创建调用记录，状态为 `preparing`
2. **等待审批**：状态变为 `waiting_approval`，管理员在管理界面审核请求内容
3. **审批通过**：状态变为 `approved`，系统执行实际的外部 HTTP 调用
4. **对账**：执行完成后状态进入 `reconciled`，记录最终结果

未经审批的写操作不会产生任何外部请求。

## 安全边界

### SSRF 防护

所有连接器的 HTTP 调用经过统一的 SSRF 防护层：

- DNS 解析后校验目标地址，拦截私网段（10/172.16/192.168 等）
- 封锁云元数据服务地址（169.254.169.254）
- 禁止跟随重定向到受限地址

### 凭据隔离

- 凭据加密存储，API 不返回明文
- 不同连接器的凭据相互隔离
- 读取凭据需要管理员权限

### 调用去重

每次执行尝试拥有唯一的 `logical_call_key`，数据库唯一约束阻止相同调用的重复执行。并发场景下只有一个执行者能成功获取执行权。

### 崩溃恢复

执行尝试支持 lease 机制：worker 崩溃后，新 worker 可获取过期的 lease 并继续执行或标记失败，避免调用记录卡在中间状态。

## 故障与恢复

- **连接器不可用**：工作流步骤会明确失败并记录错误，不会静默跳过
- **外部系统超时**：操作支持配置 `retry_policy`，超过重试次数后标记失败
- **Worker 崩溃**：lease 过期后新 worker 自动接管，调用记录不会永久卡住
- **外部写入失败**：Yuxi 侧无法回滚已发送到外部系统的写操作，审批流程提供人工确认环节以减少误操作

## 限制

- 连接器仅支持 HTTP/HTTPS 协议的外部系统
- 不提供跨系统的分布式事务或自动补偿
- 写操作的外部回滚由外部系统负责
- Salesforce 和飞书多维表格 CRM 适配器依赖对应第三方 API 版本，API 变更时需更新适配器
- 高频调用场景下 `connector_usage_logs` 表会快速增长，建议定期归档
