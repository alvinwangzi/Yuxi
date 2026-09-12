# 工作流编辑器采用 Vue Flow 画布交互

状态：implemented
类型：feature
Owner：web/src/views/WorkflowEditorView.vue

## 问题

工作流编辑器此前按图可视化思路（G6）渲染流程，交互停留在展示层面：节点摆放、依赖表达与编辑面板割裂，效果粗糙且不符合用户对"编排"的直觉。用户明确反馈："把节点放到画布上，然后用线把节点连接起来，更容易让人理解"，即要求 Dify 式的拖放 + 连线画布体验，而不是数据可视化图谱。

## 决策

用 Vue Flow（`@vue-flow/core`）重写 `WorkflowEditorView`。事实 Owner 分工：`WorkflowEditorView.vue` 拥有画布数据流、同步与持久化链路；`web/src/components/workflow/WorkflowNode.vue` 拥有自定义节点的渲染与配色。

- 画布是唯一编辑入口：左侧 palette 拖拽添加节点、节点自由拖动、Handle 连线表达 `depends_on`、选中节点后右侧表单编辑属性。
- 数据流单向：`flowElements` → `steps` 同步（watch），表单修改只做定点回写对应节点，不允许反向重建 `flowElements`，避免双向 watch 递归与用户摆放位置被重置。
- 连线必须经 `addEdges()` 写入（自动生成 edge id）；带自环与重复边防护。
- 节点位置持久化到 step 对象的 `position` 字段（后端 `validate_definition` 校验 id/type/depends_on/环，允许 JSONB 额外字段）；无 `position` 的旧数据按 depends_on 拓扑分层布局（同层并排、跨层左→右）。
- 初始视口用 `onNodesInitialized` 钩子做一次 `fitView`（节点尺寸测量完成后才生效）；删除键兼容 `Backspace` 与 `Delete`。

第二轮迭代（连线删除、圆弧、固定边界节点）：

- 自定义 `WorkflowEdge`（type: `workflow`）渲染贝塞尔曲线，并在连线中点用 `EdgeLabelRenderer` 挂常驻删除按钮（低透明度、hover 高亮红色），点击派发 Vue Flow `removeEdges`，随 watch 自动 markDirty。
- Start/End 是**真实业务步骤**而非纯视觉锚点：step `type` 为 `start`/`end`，与 llm/tool/http 等同处 `definition.steps`，连线即真实 `depends_on`。分工：`WorkflowNode.vue` 拥有边界节点渲染（胶囊样式、Play/Flag 图标、条件 Handle）；`WorkflowEditorView.vue` 拥有迁移与同步；`backend/package/yuxi/workflows/`（`__init__.py` 类型表、`dag.py` 校验、`executors/start_executor.py`、`executors/end_executor.py`）拥有后端类型注册、校验与执行语义。
- 固定存在性由迁移保证：`ensureTerminalSteps` 在加载时对缺边界的旧数据一次性补齐（入度 0 业务步骤挂到 start、出度 0 业务步骤汇入 end）；只缺其一（用户已接管连线）时只补节点不挂线。之后连线完全由用户管理，不做派生 reconcile。
- 边界节点不可删除（节点 `deletable: false` + 面板隐藏删除按钮 + `removeStep` 防护）；`onConnect` 拒绝流入 start / 流出 end 作为兜底。
- 职责归属：Start 节点面板编辑输入变量（写入 `definition.variables`，运行时由引擎注入 context）；End 节点面板编辑输出格式 `format`（markdown/text/json，后端默认 markdown）与输出模板 `template`（`{{变量}}` 语法；整体引用变量保留原始类型，留空则回退收集上游 `output_key` 结果）。
- 后端校验：start/end 各最多一个；start 不得有 `depends_on`。start 执行器 no-op（输入变量已由引擎注入 context）；end 执行器渲染模板输出 `{format, content}`。

第三轮迭代（补齐全部业务节点面板字段——此前除 llm/tool 外各节点面板只有名称+类型空壳）：

- 按后端执行器实际读取的字段逐一补齐前端面板：script（`code` 等宽字体编辑区 + `language` 选择）、approval（`approval_prompt`）、http（`headers`/`body` JSON 编辑 + `timeout`）、condition（`then_step`/`else_step` 下拉选择）、llm（`model_spec` 轻量模式）、output（`delivery` 多选交付渠道）。
- 修复 tool 步骤前后端字段名不一致：前端 `tool_args` → `tool_params`（对齐 `tool_executor.py` 读取的字段名）。
- 所有业务步骤统一加 `output_key` 配置区（引擎 `_execute_step` 据此决定是否将步骤输出写入 context 供下游引用）。
- `onDrop` 按步骤类型初始化默认字段（`getStepDefaults`），确保 Vue 响应式能追踪后续赋值。
- 步骤编辑面板宽度 320px → 380px 以适配更多字段。

## 替代方案

- 继续 G6：图分析与大规模图渲染强，但拖放建图、连线、编辑面板联动需要自研大量编辑器语义，且已验证的用户反馈是效果粗糙、不直观。
- 自研 SVG 画布：需要自己实现拖拽、缩放、连线吸附、选择框等基础能力，维护成本远高于收益。
- React Flow：同类成熟方案，但本项目前端是 Vue 3，引入 React 运行时不成比例。

## 后果

- 新增前端依赖 `@vue-flow/core`。
- 画布与表单的职责不对称：画布是主编辑入口，表单属性编辑需逐字段定点回写节点数据；后续新增节点属性时必须同时维护 `syncStepsFromFlow` 与对应回写逻辑。
- workflow definition 的 step JSONB 中出现 `position` 额外字段；后端 DAG 校验不感知该字段，前端布局逻辑拥有它。
- 拓扑分层布局只作为无 `position` 数据时的初始 fallback，用户拖动后以保存的位置为准。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| Handle 连线生成依赖并在保存后持久化到 `depends_on` | 手动 push 无 id 的边被丢弃、自环/重复边入库 | `web/src/views/WorkflowEditorView.vue` 的 `onConnect` | Chrome DevTools 模拟 mousedown→mousemove→mouseup 连线后保存，`docker compose exec -T postgres psql -U postgres -d yuxi` 查询 definition | 自环与重复边不生成新边；保存后数据库含双依赖 step | Passed |
| 节点拖动位置随保存持久化并在刷新后恢复 | 拖动后位置丢失或被布局算法重置 | `syncStepsFromFlow` / `syncFlowFromSteps` | 拖动节点→保存→刷新页面，位置一致（psql 中 `position` 字段与画布一致） | 拖动后不保存刷新，恢复保存时位置 | Passed |
| 拖拽 palette 节点添加到画布并参与保存 | drop 后无节点或类型丢失 | `onDrop` / `onDragStart` | HTML5 DnD 浏览器验证：拖入节点→保存→psql 验证 steps 增长 | 空 dataTransfer 不产生节点 | Passed |
| 删除节点/边并清理关联依赖 | 删除节点后残留悬空 depends_on | `removeStep` / Vue Flow `delete-key-code` | Backspace/Delete 删边；面板删除节点后边数 6→4，保存后 psql 无悬空引用 | 删除源节点后目标节点仍引用其 id | Passed |
| 连线可通过中点删除按钮移除且联动未保存状态 | 按钮点击不派发 remove、状态不置脏 | `web/src/components/workflow/WorkflowEdge.vue` | 浏览器点击连线中点 × 按钮 → 边消失、出现"未保存"；`deletable: false` 的边界连线不渲染按钮 | 边界连线删除按钮可点 | Passed |
| 前端 lint 与既有单测不回归 | 新组件破坏既有测试 | `web/` | `npx eslint` 两个新文件通过；`pnpm test:unit` 340/343 通过 | — | 3 个失败（401 登录跳转、milvus 类型标签、侧边栏项目分组）无任何测试引用本次新增文件，属工作区其他改动的预先存在失败 |
| 保存走后端 DAG 校验且不被额外字段拒绝 | `position` 字段触发校验失败 | `backend/package/yuxi/workflows/dag.py` | 带 position 的 definition 保存成功（HTTP 200 + psql 确认） | — | Passed |
| 缺边界的旧数据加载时一次性迁移补齐 start/end 并挂线 | 迁移后无边界节点、挂线错挂、重复迁移 | `WorkflowEditorView.vue` 的 `ensureTerminalSteps` | 加载无边界 definition → 画布 9 节点（含 start/end 胶囊）、入度 0 步骤挂 start、出度 0 步骤汇入 end；保存后 psql 中 steps 含 `type: start/end` 且无 `__start__` 残留；刷新后迁移不重复触发 | 只缺 end 时迁移再挂线（用户已接管连线） | Passed |
| 边界节点不可删除且 Start/End 面板编辑各自职责属性 | 边界节点被删除、面板显示删除按钮、变量/输出修改不入库 | `WorkflowEditorView.vue` / `WorkflowNode.vue` | Backspace 与面板删除按钮对 start/end 无效（面板无删除按钮）；Start 面板"添加变量"生成变量名/默认值输入行、输入后出现"未保存"；End 面板暴露输出格式（默认 Markdown）与输出模板 | 面板对 start/end 显示删除按钮 | Passed |
| 后端 DAG 校验约束边界节点、start/end 执行器语义正确 | 重复 start/end 入库、start 带依赖通过校验、end 模板渲染破坏原始类型 | `backend/package/yuxi/workflows/dag.py` / `backend/package/yuxi/workflows/executors/end_executor.py` | api 容器内 python 断言：合法定义（start→A/B→C→end）校验无错且 Kahn 分层 `[start]→[a,b]→[c]→[end]`；重复 start/end、start 带 depends_on 均被拒绝；end executor 模板渲染 / 无模板回退收集上游 / `{{x}}` 整体引用 dict 保留原始类型全部通过 | start 带 depends_on 的定义校验通过 | Passed |
| 真实运行链路：输入变量 → 业务步骤 → End 模板输出端到端可观察 | run 永远 failed、输入变量丢失、业务输出/End 输出未落库 | `backend/package/yuxi/services/run_worker.py` 的 `process_workflow_run` / `backend/package/yuxi/workflows/engine.py` | 临时工作流（slug `wf-run-e2e-test`：start 变量 topic/audience → script 步骤 `output_key: prepared` → end 模板 `output_key: result`）经真实 HTTP 触发运行（POST `/api/workflows/2/run`）→ ARQ worker 执行 → run #2 `completed`，psql 确认 `context` 含输入变量、`prepared`（script 输出）与 `result.content`（end 模板同时渲染业务输出与两个输入变量，值逐一正确） | run 在任一环节失败时停在 failed 且 error_message 可见 | Passed（需修复三处链路缺陷，见下） |
| 全部 7 种业务节点面板字段与后端执行器读取字段对齐 | 面板只有名称+类型空壳、字段名前后端不一致 | `WorkflowEditorView.vue` 的步骤编辑表单区 | 9 步骤工作流（含 llm/tool/http/condition/approval/script/output 各类型）逐一点击节点，DevTools snapshot 确认每种面板渲染出对应字段（script 含代码编辑区+语言选择、http 含 headers/body/timeout、condition 含 then/else 下拉、approval 含审批提示、output 含交付渠道多选、所有业务步骤含 output_key）；eslint 无报错 | 面板对 script 节点不显示代码编辑区 | Passed |

运行链路验证时修复的三处预先存在缺陷（均导致运行必然失败，修复后链路闭合）：

- `run_worker.py`：`WorkflowEngine(definition=..., input_variables=...)` 传了引擎不接收的参数、`engine.execute()` 缺必填参数 → 构造器只传回调，`execute(definition, input_variables)` 传参。
- `workflow_service.py`：`append_run_stream_event` 调用使用不存在的 `event=`/`data=` 参数名 → 修正为 `event_type=`/`payload=`。
- `run_worker.py`：`pg_manager.async_session_factory` 属性不存在 → 修正为 `pg_manager.AsyncSession`。

未验证范围：`WorkflowStepRun`（步骤级运行记录）全仓库无创建逻辑，`step_runs` 恒为空——运行结果目前仅通过 `run.context` 可观察，步骤级状态/输出落地是已知缺口；SSE 工作流事件的前端消费；移动端视口下的画布手势。
