# Agent Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将定时任务从智能体管理页签独立为 `/scheduled-agents`，并调整左侧菜单顺序为智能体、定时任务、技能 · 连接器。

**Architecture:** 复用现有 `ScheduledAgentsView.vue`，只新增独立路由和导航入口；`AgentManageView.vue` 收敛为纯智能体管理页面。旧查询参数不做兼容跳转，访问 `/agent-manage?tab=schedules` 时按普通智能体管理页处理。

**Tech Stack:** Vue 3、Vue Router、Pinia、Vite、Ant Design Vue、pnpm。

---

### Task 1: 新增定时任务独立路由

**Files:**
- Modify: `web/src/router/index.js`

- [x] 在现有 AppLayout 路由集合中新增 `/scheduled-agents` 路由，使用独立名称并复用 `ScheduledAgentsView.vue`。
- [ ] 保持 `requiresAuth: true` 与现有 AppLayout 布局一致。
- [ ] 不新增旧地址重定向。
- [ ] 检查路由名称唯一且动态导入路径正确。

### Task 2: 调整左侧菜单顺序

**Files:**
- Modify: `web/src/layouts/AppLayout.vue`

- [x] 在 `mainList` 中保留“智能体”指向 `/agent-manage`。
- [ ] 紧随“智能体”添加“定时任务”指向 `/scheduled-agents`，使用现有任务相关图标 `ClipboardList`。
- [ ] 将“技能 · 连接器”保持指向 `/skills`，并确保它位于定时任务之后。
- [ ] 确认 `isNavItemActive` 能正确识别三个独立路径的选中态。

### Task 3: 收敛智能体管理页面

**Files:**
- Modify: `web/src/views/AgentManageView.vue`

- [x] 移除 `ScheduledAgentsView` 导入、`activeTab`、`schedulePanelRef`、页签配置、页签切换和离开前保存逻辑。
- [ ] 移除 `PageHeader` 的 `tabs`、`active-key`、`@change` 和相关定时任务状态绑定。
- [ ] 保留智能体统计信息、`AgentManagePanel` 及其加载状态。
- [ ] 保留页面标题“智能体管理”，使 `/agent-manage` 直接展示智能体管理内容。
- [ ] 删除不再使用的 `useRoute`、`useRouter`、`onBeforeRouteUpdate` 和 `watch` 导入/逻辑。

### Task 4: 验证导航与页面

**Files:**
- Test/verify: `web/src/router/index.js`, `web/src/layouts/AppLayout.vue`, `web/src/views/AgentManageView.vue`

- [ ] 运行 `pnpm lint`，确认无 ESLint 错误（当前仓库已有其他文件 lint 错误；本次修改文件已通过定向 ESLint）。
- [x] 运行 `pnpm build`，确认路由和组件编译成功。
- [ ] 检查 `/agent-manage` 只显示智能体管理。
- [ ] 检查 `/scheduled-agents` 可加载现有定时任务页面。
- [ ] 检查左侧菜单顺序为“智能体 → 定时任务 → 技能 · 连接器”，并验证三个路径的 active 状态。
- [x] 运行 `git diff --check`，确认无空白错误。
