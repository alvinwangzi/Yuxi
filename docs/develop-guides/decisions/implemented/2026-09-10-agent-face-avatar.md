# 智能体默认头像使用本地生成的 Notion 风格人像 SVG

状态：implemented
类型：feature
Owner：web/src/utils/agentFaceAvatar.js

## 问题

智能体未上传头像时，前端 `generatePixelAvatar(agent.id)` 生成 DiceBear 外部 API URL（`https://api.dicebear.com/10.x/glyphs/svg?seed=<agent.id>`）作为 FallbackAvatar 的 defaultSrc。该实现存在三个缺陷：依赖外网 api.dicebear.com，网络受限时加载失败并退化为首字母占位；图案由 agent.id 哈希决定，与智能体标题、描述没有语义关联；图案是抽象字形，不是可辨识的人头像。

## 决策

`web/src/utils/agentFaceAvatar.js` 拥有智能体默认头像的参数决策、企业场景词典与 SVG 生成。它以 name 与 description 拼接串的确定性哈希为 seed 生成 64×64 Notion 风格人像 SVG data URI：配饰按「标题优先、描述其次」匹配企业场景词典，多词命中按词典固定类别顺序取首个，无命中时哈希决定（含无配饰）；肤色、发型、背景色由哈希从参数池选取。词典围绕十种配饰组织为十类场景域：审核与合规（check）、开发工程（terminal）、设计创意（palette）、营销传播（megaphone）、外部信息与检索（globe）、写作与文档（pen）、数据与量化（chart）、调研与归档（clipboard）、研究与咨询（glasses）、领导与管理（briefcase）；初始词表参考 The Agency 智能体角色清单对照企业常见部门扩充，覆盖客服、人事、财务、法务、运维、销售、运营、工程开发、设计、营销、管理等企业常见智能体角色；check 置于 terminal 前使「测试工程师」「安全工程师」仍归质检，而「前端工程师」「算法工程师」落入开发工程；briefcase 置于最后使含业务领域词的管理者（销售总监、首席财务官）先归业务域，纯管理身份词（CEO、总监、经理）落入领导管理。完整词表由 `agentFaceAvatar.js` 拥有并在单测中逐条断言，本记录维护词表归属与组织原则，词表条目本身随测试演进。

五处智能体头像消费方的 defaultSrc 使用 `generateAgentFaceAvatar`：`AgentView.vue` 与 `AgentManagePanel.vue`（name + description）、`AgentEditModal.vue`（编辑态与新建态实时预览，空态 `v-if` 与 is-empty 判定放宽为「icon 为空且预览为空」才进入空态）、`AgentChatComponent.vue`（getSubagentRunName + run.description）、`ThreadStatsComponent.vue` 仪表盘审计表智能体列（agent_name，该记录无 description）。用户头像（UserInfoComponent 与 ThreadStatsComponent 用户列）继续由 `web/src/utils/pixelAvatar.js` 拥有；`web/src/components/common/FallbackAvatar.vue` 的三级降级链保持原样，上传头像的智能体仍优先显示上传图。名字与描述只参与哈希与词典匹配，注入 SVG 的内容仅来自固定常量池，无注入面。

## 替代方案

- 后端生成 SVG 存 MinIO 并写入 icon 字段：头像成为持久数据、后端消费方可见；需要修改创建流程，改名或改描述后头像不随更新需额外同步，且当前消费方全部在前端。拒绝。
- 保留 DiceBear 仅切换人脸风格模板：改动最小；仍依赖外网，且 seed 只能基于 id，无法按标题、描述语义映射。拒绝。
- 构建期预生成固定 SVG 资源集供前端按哈希选取：运行时零计算；组合有限，无法对任意标题、描述做关键词语义映射，并引入构建流程耦合。拒绝。
- 扩展现有 pixelAvatar.js：文件数最少；用户与智能体头像逻辑耦合，与「只改智能体头像」的范围不一致。拒绝。
- LLM 分析标题、描述选择头像参数：语义最准；增加延迟、成本与故障面，与前端运行时生成冲突。拒绝。

## 后果

- 词典精确子串匹配较宽，描述偶然包含通用词（如分析、内容）时配饰可能偏离预期；由标题优先与固定类别裁决限制影响，接受。
- data URI 使每个头像节点携带约 2-3KB 内联字符串；智能体数量级为几十，接受。
- 仪表盘审计表记录无 agent description，该列头像仅由名称决定，接受。
- 名称或描述编辑后头像即时跟随，无历史数据迁移；智能体头像不再请求 api.dicebear.com。
- 未来出现后端消费方（如分享卡片）需在 Python 侧复刻生成器；当前无该 consumer，未预留抽象。
- 新增词典关键词必须满足：同词在更靠前类别已有条目时属于顺序变更，需同步更新逐条断言测试；新增关键词如果是其他类别关键词的子串会被固定顺序裁决吸收，逐条断言会暴露归属争议。

## 验证

- `cd web; pnpm test:unit`：285 个测试，282 通过，3 失败均为预存问题并与本次改动无关——`api_boundary.test.js:89`（401 会话清理断言）、`database_create_flow.test.js:62`（知识库类型标签期望）、`projectConversationGroups.test.js:86`（读取用户在途未提交的 `ConversationNavSection.vue` 源文本）。`agentFaceAvatar.test.js` 9/9 通过（确定性、词典全部关键词逐条断言命中各自配饰、标题优先裁决、工程/设计/营销角色命中与质检词优先顺序、管理身份命中公文包与业务词优先顺序、兜底取值合法、空输入空串、data URI 结构、新增配饰 SVG 特征断言），`dashboard_thread_stats.test.js` 断言更新后通过。
- `cd web; pnpm lint:check`：全局存在 1 个预存错误（`HomeView.vue:475` 'err' is defined but never used，非改动文件）；对 8 个改动文件范围化 eslint：0 错误。
- `cd web; pnpm build`：vite build 成功。
- 真实页面验证（Vite dev server localhost:5173，登录用户 alvin）：
  - /agent-manage 列表：6 个智能体（智能助手、深度研究、调研探索员、事实核查员、通用任务、网页检索）全部渲染本地 data URI 人像 SVG，配饰与名称语义一致（深度研究=眼镜、事实核查员=核验徽记、网页检索=地球仪、调研探索员=剪贴板）。
  - 新建智能体弹窗（词典扩充后复验）：输入「前端开发工程师」预览为带终端窗口配饰（terminal：提示符括号与光标）的人像；「UI 设计师」命中调色盘（palette）；「新媒体营销助手」命中扩音喇叭（megaphone）；「测试工程师」仍命中核验徽记（check）而非 terminal，顺序裁决生效。
  - 新建智能体弹窗（领导管理类扩充后复验）：输入「CEO 战略助手」预览为带公文包配饰（briefcase：包体、提手与扣带线）的人像；「技术总监」命中 briefcase；「销售总监」仍命中柱状图（chart），业务词优先于管理词。
  - 新建智能体弹窗：输入「合同审核助手」实时出现带核验徽记（check）的人像预览，`img src` 为 `data:image/svg+xml` 且不含 dicebear；单字输入实时更新（哈希兜底路径）；真实键盘删除后预览 img 移除、`.agent-icon-upload` 进入 is-empty 空态。
  - /dashboard 会话分析审计表：智能体列 7/7 头像为本地 SVG data URI；用户列保持既有行为（alvin=MinIO 上传头像，user/officer=既有 DiceBear 用户头像）。
  - 子智能体运行列表头像（AgentChatComponent）：环境无子智能体运行数据，未在真实页面验证；由单元测试与代码审查覆盖。
  - 头像 src 均为 data URI，无对外网 api.dicebear.com 的智能体头像请求。
- `python scripts/verify_engineering_contracts.py`：本记录转入 implemented 后复跑通过。
- `python -m unittest scripts.test_verify_engineering_contracts`：61 个测试，1 失败（`test_projection_is_derived_from_current_owners`：Windows 下路径分隔符反斜杠与正斜杠差异，比较对象为既有 `2026-08-15-valid-decision.md`，预存环境性失败，与本次改动无关）。
- backend pytest unit（standing order）：`docker compose exec -T api uv run --no-sync --group test pytest test/unit -m "not slow"`：1943 通过，7 失败（`test_summary_graph_config.py` 6 项、`test_tool_approval.py` 1 项、`test_context_compression_service.py` 1 项），全部为 backend agents/context compression 主题预存失败，与本次前端改动零交集；`uv run` 不带 `--no-sync` 时因容器内 `__editable__.yuxi-0.7.3.pth` 权限问题无法启动，属环境问题。
- 负向案例：词典全部关键词逐条断言命中各自类别（含工程、设计、营销、管理扩充词）；「写作助手」+「数据统计」标题优先命中 pen；「财务分析助手」命中 chart；「测试工程师」含「工程师」（terminal）仍命中 check，证明词典顺序裁决；「销售总监」含「总监」（briefcase）仍命中 chart，证明业务词优先于管理词；无词典命中输入输出合法配置；空输入返回空串并落入 FallbackAvatar 首字母兜底；新建态清空名称回空态（is-empty 生效）；审计表断言同时覆盖智能体列切换与既有 uid 列保持。
