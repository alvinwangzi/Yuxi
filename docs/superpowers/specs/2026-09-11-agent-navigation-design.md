# 智能体相关导航拆分设计

## 目标

将定时任务从智能体管理页签中独立出来，并调整左侧导航顺序：

1. 智能体
2. 定时任务
3. 技能 · 连接器

## 路由设计

- `/agent-manage` 仅展示智能体管理，不再包含定时任务页签。
- 新增 `/scheduled-agents`，直接承载现有定时任务页面。
- 不保留 `/agent-manage?tab=schedules` 的兼容跳转；该地址按普通智能体管理页面处理。
- `/skills` 保持现有技能、工具、MCP 与渠道页面功能不变。

## 组件与导航变更

- `AppLayout.vue` 将“定时任务”作为“智能体”后的平级导航项，并将“技能 · 连接器”紧随其后。
- `AgentManageView.vue` 删除定时任务页签、页签切换状态和定时任务面板，仅保留 `AgentManagePanel`。
- `router/index.js` 新增独立的 `/scheduled-agents` 路由，复用 `ScheduledAgentsView.vue`。
- 原有定时任务业务组件、API、自动保存和权限行为保持不变。

## 验证

- 检查路由可加载且无重复路由名称。
- 验证左侧菜单顺序和选中态。
- 验证 `/agent-manage` 只显示智能体管理。
- 验证 `/scheduled-agents` 可正常加载定时任务列表与编辑功能。
- 运行前端 lint/build 或项目现有的最小相关测试。
