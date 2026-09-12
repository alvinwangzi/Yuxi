# 自定义分类管理系统设计

## 概述

为租户管理员提供自定义分类能力，包括智能体分类、技能分类和角色模板分类的管理。同时在角色模板页面支持管理员对角色卡片进行快速重新分类。所有功能均为管理权限（admin/superadmin）。

## 设计决策

- **方案选择**：统一 `custom_categories` 表，通过 `entity_type` 区分三种实体类型
- **分类关系**：管理员自定义分类完全替换现有硬编码分类，系统预置分类作为初始值可被编辑/删除
- **角色模板存储**：从文件系统驱动改为数据库驱动，Markdown 内容全部入库
- **关联方式**：所有实体通过 `category_id`（FK → `custom_categories.id`）关联，不使用 slug
- **设置入口**：在 SettingsModal 中新增「设计」Tab

## 数据模型

### `custom_categories` 表

```sql
CREATE TABLE IF NOT EXISTS custom_categories (
    id            SERIAL PRIMARY KEY,
    entity_type   VARCHAR(32) NOT NULL,   -- 'agent' | 'skill' | 'role_template'
    slug          VARCHAR(64) NOT NULL,
    label         VARCHAR(64) NOT NULL,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    is_builtin    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(entity_type, slug)
);
```

### `role_templates` 表

```sql
CREATE TABLE IF NOT EXISTS role_templates (
    id            SERIAL PRIMARY KEY,
    role_key      VARCHAR(255) NOT NULL UNIQUE,  -- 业务唯一标识（原文件路径）
    category_id   INTEGER NOT NULL REFERENCES custom_categories(id),
    name          VARCHAR(128) NOT NULL,
    description   TEXT,
    icon          VARCHAR(32) DEFAULT '👤',
    color         VARCHAR(32) DEFAULT 'blue',
    content       TEXT NOT NULL,                  -- Markdown 正文
    sort_order    INTEGER DEFAULT 0,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_role_templates_category_id ON role_templates(category_id);
```

### `agents` 表变更

新增 `category_id` 列（FK → `custom_categories.id`），保留旧 `category` 字符串列用于迁移过渡，后续版本移除。

### `skills` 表变更

新增 `category_id` 列（FK → `custom_categories.id`）。

### 初始数据 Seed

首次建表时从以下来源填充 `custom_categories`：

| entity_type | 来源 | 初始数量 |
|---|---|---|
| agent | `itemCategory.js` 的 9 个分类 | 9 |
| skill | 同 agent 的 9 个分类 | 9 |
| role_template | `CATEGORY_MAP` 的 20 个分类 | 20 |

`role_templates` 从文件系统扫描 277 个 `.md` 文件，解析 frontmatter + 正文后批量写入。

## Backend API

### 分类管理 API：`/api/system/categories`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/system/categories?entity_type=agent` | admin | 获取指定类型分类列表 |
| POST | `/api/system/categories` | admin | 新增分类 |
| PUT | `/api/system/categories/{id}` | admin | 编辑分类 |
| DELETE | `/api/system/categories/{id}` | admin | 删除分类（已关联实体需先迁移） |

**POST/PUT 请求体**：

```json
{
  "entity_type": "agent",
  "slug": "office",
  "label": "办公协同",
  "sort_order": 1
}
```

**删除约束**：若该分类下有 agent/skill/role_template 关联，返回 409 提示先迁移。

### 角色模板 API 改造

| 方法 | 路径 | 变化 |
|---|---|---|
| GET | `/api/roles` | 从 `role_templates` 表查询，JOIN `custom_categories` |
| GET | `/api/roles/categories` | 查 `custom_categories` WHERE `entity_type='role_template'` |
| GET | `/api/roles/{id}` | 按数据库 ID 查询（原为 `/{category}/{role_id}` 路径） |
| POST | `/api/roles/{id}/import` | 导入为 Agent（逻辑不变） |
| PUT | `/api/roles/{id}/category` | **新增**：更新角色模板分类，body: `{ "category_id": 5 }` |

### Agent / Skill 分类字段迁移

- Agent 创建/更新 API 新增 `category_id` 参数
- Skill 列表 API 返回 `category_id`
- 旧的 `category` 字符串参数标记为 deprecated

## 前端设计

### 设置面板「设计」Tab

#### SettingsModal.vue 变更

在侧边栏「OCR 配置」和「用户管理」之间新增：

```
🎨 设计
```

仅 `userStore.isAdmin` 可见。

#### 新建 `DesignSettingsSection.vue`

三个区块，结构一致：

- **标题** + 描述（如「管理智能体的分类标签」）
- **分类列表**：表格形式，每行显示 label、slug、排序，右侧编辑/删除按钮
- **新增按钮**：弹出内联表单（slug + label + sort_order）
- **编辑**：Modal 内编辑
- **删除**：`Modal.confirm` 二次确认

### 角色模板重新分类

#### RoleTemplatePanel.vue 改造

角色卡片上分类标签区域（当前 `role.category_name` 的 tag）：

1. **管理员可见时**：分类 tag 渲染为可点击按钮
2. **点击** → 弹出 `a-popover`，平铺展示所有 `role_template` 分类
3. **当前分类高亮**，点击其他分类 → 调用 `PUT /api/roles/{id}/category`
4. **成功** → 刷新卡片分类显示 + `message.success`
5. **普通用户**：分类 tag 只读，点击无反应

### 前端消费者改造

#### 新增 composable：`useCategories(entityType)`

- 从 `/api/system/categories?entity_type=xxx` 动态加载分类列表
- 提供 `categories`、`loading`、`refresh` 等响应式状态
- 管理员修改分类后自动刷新

#### 影响组件

| 组件 | 变化 |
|---|---|
| `AgentManagePanel.vue` | 分类标签栏从 `useCategories('agent')` 获取 |
| `AgentEditModal.vue` | 分类下拉选项从 API 获取 |
| `SkillCardList.vue` | 分类标签栏从 `useCategories('skill')` 获取 |
| `RoleTemplatePanel.vue` | 分类标签栏 + 卡片分类 tag 可点击重新分类 |
| `SettingsModal.vue` | 新增「设计」Tab |
| `itemCategory.js` | 硬编码保留为 fallback，不再作为 UI 数据源 |

## 数据库迁移

### 迁移步骤

1. `ensure_business_schema()` 中新增 `CREATE TABLE IF NOT EXISTS custom_categories`
2. `ensure_business_schema()` 中新增 `CREATE TABLE IF NOT EXISTS role_templates`
3. `ensure_business_schema()` 中新增 `ALTER TABLE agents ADD COLUMN IF NOT EXISTS category_id`
4. `ensure_business_schema()` 中新增 `ALTER TABLE skills ADD COLUMN IF NOT EXISTS category_id`
5. 一次性迁移脚本：seed 初始分类 → 扫描文件导入角色模板 → 回填 agents/skills 的 category_id
6. 回填逻辑：根据 `agents.category` 的旧 slug 匹配 `custom_categories` 中的 id

### 迁移后

- 后端 `roles/__init__.py` 的文件扫描逻辑废弃，改为从数据库读取
- 原 `.md` 文件保留在仓库作为版本管理备份，运行时不再读取

## 权限模型

- 分类 CRUD：仅 admin/superadmin
- 角色模板重新分类：仅 admin/superadmin
- 分类查看（所有用户）：分类列表对所有登录用户可见（用于筛选展示）

## 错误处理

- 删除分类时有关联实体 → 409 Conflict，提示「该分类下有 N 个实体，请先迁移」
- 分类 slug 重复 → 409 Conflict
- 角色模板重新分类传入无效 category_id → 400 Bad Request
