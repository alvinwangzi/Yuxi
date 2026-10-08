# 第三方业务系统连接器

连接器将受控外部操作提供给 Agent 和工作流。当前类型为 generic_rest、salesforce、feishu_bitable_crm；本地链路通过不表示目标组织已接入。外部账号、字段权限和独立写后回查由系统 Owner 验证。

## 配置与权限

管理员在“扩展 → 连接器”创建停用草稿，填写地址、字段、操作和 Vault 凭据，再明确读取/写入范围并启用。缺省范围为 deny，最终授权检查数据库中的当前用户、部门、角色、启用状态及版本。

凭据只在专用输入写入，编辑留空保持，不回填秘密。启用配置必须有完整认证配对；删除必需凭据应同时停用或补齐，同 key 同时 upsert/delete 被拒绝。key ring、迁移和轮换见[部署指南](./deployment.md)。

REST 配置示例不含真实凭据：

```json
{
  "base_url": "https://crm.example.com",
  "auth_type": "bearer",
  "allowed_origins": ["https://crm.example.com"],
  "static_headers": {"Accept": "application/json"},
  "timeout_seconds": 30,
  "max_response_bytes": 1048576
}
```

认证类型为 none/bearer/basic/api_key，对应 Vault 凭据 token、username/password、api_key；静态头不承担认证。来源和端口严格匹配，重定向、代理环境变量、路径穿越及不允许的地址被拒绝。私网须同时有显式来源与受控 CIDR。

## 操作与审批

操作配置 read/write、HTTP 方法、相对端点、参数 Schema、query/body 模板与输出映射。路径使用 `{{record_id}}`，映射为 `data.name` 等受限字段路径，不是 `$.name` 或脚本。Schema 只接受声明子集，保存拒绝外部引用、环、过深引用和未知关键字。

REST 管理员明确公开审批字段：

```json
{
  "type": "object",
  "properties": {
    "record_id": {"type": "string", "maxLength": 256, "x-approval-visible": true, "x-approval-target": true},
    "status": {"type": "string", "maxLength": 64, "x-approval-visible": true}
  },
  "required": ["record_id", "status"],
  "additionalProperties": false
}
```

required 写入先提交 invocation，再由调用者本人决定；管理员不能代批准另一用户调用。面板显示冻结目标、公开变更、字段、版本和有效期，真实目标未公开时不能批准。digest 绑定全部参数，不能借模型的 approval=true 绕过。子 Agent 不提供 required 写审批转交。

REST 读取可配置 `retry_policy: {"max_attempts":3}`，仅瞬时错误重试；所有尝试共享总 timeout，每次重新授权并提交 attempt。写不自动重试。`remote_idempotency: {"header_name":"Idempotency-Key"}` 将专用头绑定持久 invocation ID，不承诺远端 exactly-once。

管理写测试必须携带 Idempotency-Key；相同用户/连接器/操作/键的响应丢失重试复用调用，参数变化返回 conflict。required 测试返回 409 和 invocation/digest/摘要，批准后同键继续，不建立免审批路径。

## 预置系统

Salesforce 使用 server-to-server client credentials，由管理员配置 My Domain base_url、api_version、对象与读写字段；不提供 Session ID 或自由 SOQL。upsert 和外部业务键查询的 account_external_id_field 由配置拥有，模型仅提供键值。标准操作支持客户查询/读取/upsert、商机读取/更新，写后独立 GET 回查。

飞书使用企业自建应用 app_id/app_secret。先保存停用 Base 草稿与完整应用凭据，再只读发现同一 Base 的表；选择客户/商机表并保存后读取字段，配置调用参数名、field ID/type。未确认类型不能启用为写字段，输入 Schema 随映射更新，运行时仍校验真实字段类型。支持有限文本、数值、选择、毫秒日期、复选框和关联格式，不靠名称猜测类型。

飞书 filters 只接受映射字段的有限等值条件和有界分页，不提供任意 DSL 或跨 Base 参数。记录输出仅保留操作允许字段与记录身份，未配置列不进入模型/工作流。映射输出有独立预算，不能通过重复路径放大响应。官方协议与外部验证边界见[连接器决策](../develop-guides/decisions/proposed/2026-10-07-third-party-system-connectors.md)。

## 运行、审计与核对

调用状态为 prepared、awaiting_approval、running、succeeded、failed、rejected、cancelled、unknown；控制状态与 remote_outcome 分开。本地映射失败不能抹掉已确认 receipt，超时也不能假装远端没有写入。

Agent 使用正式 Request/FIFO/Run/checkpoint，恢复复用原调用。工作流持久保存定义、激活与等待项，waiting_agent/waiting_approval 释放 worker 槽位。unknown 暂停后续步骤；当前管理员在执行范围内凭独立回查证据核对，确认成功后原激活读取结果继续，不重发 HTTP。不能确认则保留 unknown。

取消不能撤回远端在途请求。未发送调用可取消，在途写仍需核对；失败/取消父工作流不会被迟到回调复活。管理列表支持分页与查询；调用详情展示绑定、版本、脱敏结果和各 attempt。本人回读也复核当前权限与可见 Run，管理读检查当前管理角色，不返回私人密文或原始结果。

删除清除活凭据并保留去重 tombstone/审计；未处置 running/unknown 写阻止删除。过期 payload 维护先 dry-run，执行保留 unknown 和身份记录；生产保留策略由 Owner 批准。

## 验证边界

readiness 只证明接流量前置条件。PG、HTTP、worker、浏览器和独立远端回读分别提供证据；HTTP 200、日志关键词或 Agent 自述不能单独证明完成。缺 Salesforce 测试组织/飞书 Base 时，外部 read/write/readback 为 Not run，本地协议测试不能替代目标接入、部署或业务效果。
