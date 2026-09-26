# 技能市场（Skill Marketplace）设计

## 概述

为 Yuxi 新增「技能市场」模块，整合系统内置技能与公司发布技能，面向本公司全员提供浏览、安装与更新能力。个人技能可提交至公司市场，经管理员审批后上架；已发布版本不可变，后续更新需提交新版本。安装后生成可编辑个人副本，固定版本，手动更新。

## 设计决策

- **归属模型**：公司独立管理获批版本（方案 A）。个人原件归个人，公司保留获批副本，个人修改或删除不影响公司发布版本。
- **版本策略**：可编辑草稿 + 不可变发布版本。审批冻结整个技能包（说明、脚本、资源）。
- **安装语义**：仅"安装"按钮，不提供 skill 文件下载。安装生成个人副本，固定版本，手动更新。
- **统计口径**：安装次数，每次操作累计，同一用户重复安装也计数，不按用户去重。
- **可见范围**：公司技能上架后全公司成员可见可装，其他公司不可见。
- **下架策略**：停止展示和新安装，保留已安装个人副本、历史版本、贡献记录和安装统计。
- **旧技能衔接**：现有个人/共享技能保持原有使用方式；非内置共享技能不自动进入市场，由管理员主动发布；系统内置技能纳入市场"系统内置"分组。
- **审批规则**：普通成员首次上架和更新版本需公司管理员审批；公司管理员自己发布可直接发布，无需交叉审批，但仍须填写发布说明、生成固定版本并记录发布人。

## 核心概念

| 概念 | 说明 |
|---|---|
| 我的技能 | 个人拥有、编辑和使用的技能，归 `source_scope='personal'` |
| 技能市场 | 展示系统内置技能和公司审批通过的技能 |
| 市场条目 | 市场中的一个技能条目，包含描述、分类、状态和安装统计 |
| 发布版本 | 从个人技能或管理员维护中提交的不可变固定内容，审批针对此内容 |
| 已安装副本 | 用户从市场安装后生成的个人技能副本，可独立编辑 |

## 数据模型

### `skills` 表变更

新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `author_uid` | `VARCHAR(64)` | 技能贡献者/作者，展示用，非外键约束 |
| `market_entry_id` | `INTEGER` | 若从市场安装，关联市场条目 ID；否则 NULL |
| `market_version_id` | `INTEGER` | 安装时对应的发布版本 ID；个人编辑后不更新此字段 |

`author_uid` 补充现有 `created_by`/`updated_by`（操作审计身份），独立表达贡献归属。

### `skill_market_entries` 表

```sql
CREATE TABLE IF NOT EXISTS skill_market_entries (
    id              SERIAL PRIMARY KEY,
    slug            VARCHAR(128) NOT NULL UNIQUE,
    title           VARCHAR(256) NOT NULL,
    description     TEXT NOT NULL,
    source_type     VARCHAR(16) NOT NULL DEFAULT 'company',  -- 'builtin' | 'company'
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',  -- 'pending' | 'approved' | 'rejected' | 'unpublished'
    category_id     INTEGER REFERENCES custom_categories(id),
    author_uid      VARCHAR(64),
    publisher_uid   VARCHAR(64),
    original_skill_id INTEGER,
    install_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

- `slug`：市场全局唯一标识，与个人技能 slug 可不同。
- `source_type='builtin'`：系统内置技能，初始化时批量写入，无需审批。
- `source_type='company'`：公司发布技能，需审批流程。
- `status='unpublished'`：下架状态，不再展示，不允许新安装。
- `original_skill_id`：提交来源的个人技能 ID；内置技能为 NULL。

### `skill_market_versions` 表

```sql
CREATE TABLE IF NOT EXISTS skill_market_versions (
    id              SERIAL PRIMARY KEY,
    entry_id        INTEGER NOT NULL REFERENCES skill_market_entries(id),
    version         VARCHAR(32) NOT NULL,
    release_notes   TEXT,
    content_snapshot JSONB NOT NULL,
    change_type     VARCHAR(16) NOT NULL,  -- 'major' | 'minor' | 'patch'
    submitted_by    VARCHAR(64) NOT NULL,
    submitted_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_by     VARCHAR(64),
    approved_at     TIMESTAMP,
    is_latest       BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(entry_id, version)
);
```

- `content_snapshot`：冻结的技能包内容（SKILL.md、脚本、资源文件元数据及内容）。
- `is_latest`：每个条目仅一个版本为 TRUE，发布新版时自动切换。
- `change_type`：提交时选择，用于生成版本号。

### `skill_market_submissions` 表

```sql
CREATE TABLE IF NOT EXISTS skill_market_submissions (
    id              SERIAL PRIMARY KEY,
    entry_id        INTEGER NOT NULL REFERENCES skill_market_entries(id),
    version_id      INTEGER NOT NULL REFERENCES skill_market_versions(id),
    submitter_uid   VARCHAR(64) NOT NULL,
    submission_note TEXT,
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',  -- 'pending' | 'approved' | 'rejected'
    reviewer_uid    VARCHAR(64),
    review_note     TEXT,
    submitted_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at     TIMESTAMP
);
```

- 每次提交新版本生成一条 submission 记录。
- 管理员直接发布时，`status` 直接为 `'approved'`，`reviewer_uid` 为发布管理员。

### `skill_installations` 表

```sql
CREATE TABLE IF NOT EXISTS skill_installations (
    id              SERIAL PRIMARY KEY,
    user_uid        VARCHAR(64) NOT NULL,
    entry_id        INTEGER NOT NULL REFERENCES skill_market_entries(id),
    installed_version_id INTEGER NOT NULL REFERENCES skill_market_versions(id),
    installed_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_uid, entry_id)
);
```

- 同一用户同一市场条目仅保留一条安装记录，更新版本时覆盖 `installed_version_id`。
- 安装次数统计使用 `skill_market_entries.install_count`，不从此表 COUNT。

## 状态流转

### 市场条目状态

```
pending → approved（审批通过 / 管理员直接发布）
pending → rejected（审批驳回）
approved → unpublished（管理员下架）
rejected → pending（重新提交）
```

### 提交审批流程

```
个人技能编辑 → 选择"提交到公司技能市场"
  → 填写市场描述、提交说明、选择更新类型
  → 系统生成版本号，冻结内容快照
  → 创建 skill_market_entries（status=pending）+ skill_market_versions + skill_market_submissions
  → 管理员审批：
      approved → 市场可见，is_latest=TRUE
      rejected → 市场不可见，可重新提交
```

### 版本更新流程

```
已上架条目 → 作者或维护管理员修改草稿
  → 提交新版本（选择更新类型，填写发布说明）
  → 冻结新版本内容快照
  → 普通成员：进入审批；管理员：直接发布
  → 审批通过 → is_latest 切换到新版本
  → 已安装用户看到"可更新"提示
```

## Backend API

### 市场浏览 API：`/api/marketplace`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/marketplace/entries` | 登录用户 | 获取市场条目列表（仅 approved），支持分页和分类筛选 |
| GET | `/api/marketplace/entries/{slug}` | 登录用户 | 获取条目详情及版本列表 |
| GET | `/api/marketplace/entries/{slug}/versions` | 登录用户 | 获取条目所有发布版本 |

**列表查询参数**：

```
?category_id=5&source_type=company&page=1&page_size=20
```

### 市场安装 API

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/marketplace/entries/{slug}/install` | 登录用户 | 安装最新版本到个人技能 |
| PUT | `/api/marketplace/installations/{entry_id}/update` | 登录用户 | 更新已安装技能到最新版本 |

**安装行为**：

1. 检查用户是否已安装该条目（`skill_installations`）。
2. 若未安装：从 `content_snapshot` 创建个人技能（`source_scope='personal'`），写入 `skills` 表并关联 `market_entry_id` 和 `market_version_id`；插入 `skill_installations` 记录。
3. 若已安装且版本相同：仍递增 `install_count`（重复安装也计数），返回提示"已安装最新版本"。
4. 若已安装但版本较旧：更新个人技能内容到新版本，覆盖 `market_version_id`；若用户有本地修改（通过比较当前技能内容与安装时快照的哈希值检测），前端需先确认覆盖风险。
5. 每次安装或更新操作均递增 `skill_market_entries.install_count`，不区分首次或重复。
6. `skill_installations` 表仅记录当前安装状态（用户安装了哪个版本），不用于统计安装次数。

### 提交审批 API：`/api/marketplace/submissions`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/marketplace/submissions` | 登录用户 | 提交个人技能到市场（首次上架或新版本） |
| GET | `/api/marketplace/submissions/pending` | admin | 获取待审批列表 |
| POST | `/api/marketplace/submissions/{id}/approve` | admin | 审批通过 |
| POST | `/api/marketplace/submissions/{id}/reject` | admin | 审批驳回 |

**提交请求体**：

```json
{
  "original_skill_id": 42,
  "title": "数据分析助手",
  "description": "支持 CSV/Excel 数据清洗与可视化...",
  "category_id": 3,
  "submission_note": "新增数据透视表功能，兼容原有参数",
  "change_type": "minor"
}
```

- 首次提交：创建 `skill_market_entries`（status=pending）+ 首个版本。
- 已有条目：创建新版本，条目 status 保持 approved，新版本进入审批。

**审批请求体**：

```json
{
  "review_note": "功能完整，描述清晰，同意上架"
}
```

### 市场管理 API：`/api/marketplace/admin`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/marketplace/admin/entries` | admin | 管理员直接发布新技能 |
| PUT | `/api/marketplace/admin/entries/{slug}` | admin | 管理员更新市场条目描述/分类 |
| POST | `/api/marketplace/admin/entries/{slug}/publish-version` | admin | 管理员直接发布新版本 |
| PUT | `/api/marketplace/admin/entries/{slug}/unpublish` | admin | 下架技能 |

### 内置技能初始化

系统启动或迁移时，将现有内置技能写入 `skill_market_entries`：

- `source_type='builtin'`
- `status='approved'`（无需审批）
- 首个版本 `version='1.0.0'`，`change_type='minor'`，`submitted_by='system'`

## 前端设计

### 导航入口

在左侧菜单或扩展市场区域新增「技能市场」入口，与现有「技能·连接器」并列。

### 技能市场页面

#### 布局

- **顶部**：页面标题 + 描述 + 搜索框 + 分类筛选
- **分类标签栏**：复用 `useCategories('skill')` 分类体系
- **内容区**：两个 Tab 或分组
  - **系统内置**：展示 `source_type='builtin'` 的条目
  - **公司精选**：展示 `source_type='company'` 且 `status='approved'` 的条目

#### 技能卡片

每张卡片展示：

- 标题、描述摘要、分类标签
- 贡献者/作者（`author_uid` 对应显示名）
- 当前版本号
- 安装次数
- 操作按钮：
  - 未安装：显示「安装」
  - 已安装且为最新：显示「已安装」
  - 已安装但有新版本：显示「可更新」

#### 技能详情页（抽屉或弹窗）

- 完整描述
- 版本列表（版本号、发布时间、发布说明）
- 贡献者信息
- 安装/更新按钮

### 提交到市场

在「技能·连接器」个人技能卡片上增加「提交到公司技能市场」操作：

1. 点击后弹出提交表单
2. 填写：市场标题、市场描述、提交说明、更新类型（首次/修复/新增/不兼容）
3. 系统自动生成版本号并预览
4. 确认后提交，进入审批队列

### 管理员审批界面

在系统管理区域新增「技能审批」面板（仅 admin 可见）：

- 待审批列表：技能名称、提交者、版本号、提交说明、提交时间
- 点击展开详情：查看技能内容、版本差异
- 操作：通过（填写审批说明）/ 驳回（填写驳回原因）

### 我的已安装技能

在「技能·连接器」个人技能列表中，从市场安装的技能卡片增加标识：

- 显示市场来源标签（如"来自技能市场"）
- 显示当前安装版本
- 有新版本时显示「可更新」提示

## 数据库迁移

### 迁移步骤

1. `skills` 表新增 `author_uid`、`market_entry_id`、`market_version_id` 列。
2. 创建 `skill_market_entries` 表。
3. 创建 `skill_market_versions` 表。
4. 创建 `skill_market_submissions` 表。
5. 创建 `skill_installations` 表。
6. 初始化内置技能市场条目：扫描现有内置技能，写入 `skill_market_entries` 和首个 `skill_market_versions`。
7. 回填现有技能的 `author_uid`：从 `created_by` 字段迁移。

### 迁移后

- 现有个人技能和共享技能使用方式不变。
- 内置技能同时存在于 `skills` 表和 `skill_market_entries` 表。
- 新增市场功能不影响现有 `source_scope` 过滤逻辑。

## 权限模型

| 操作 | 权限 |
|---|---|
| 浏览市场条目 | 所有登录用户 |
| 安装市场技能 | 所有登录用户 |
| 提交个人技能到市场 | 所有登录用户 |
| 审批提交 | admin / superadmin |
| 管理员直接发布 | admin / superadmin |
| 下架市场技能 | admin / superadmin |
| 编辑已安装的个人副本 | 技能所有者 |

## 错误处理

| 场景 | HTTP 状态 | 提示 |
|---|---|---|
| 提交时标题或描述为空 | 400 | 请填写市场标题和描述 |
| 提交时 slug 已存在 | 409 | 该技能已在市场中，请提交新版本 |
| 审批时 submission 不存在 | 404 | 提交记录不存在 |
| 重复审批 | 409 | 该提交已处理 |
| 安装已下架技能 | 403 | 该技能已下架，无法安装 |
| 更新到最新版本但已是最新 | 200 | 已是最新版本 |
| 管理员下架时有安装记录 | 200 | 下架成功，已安装用户可继续使用 |

## 验收场景

### 场景 1：普通成员首次提交

1. 用户创建个人技能并编辑内容
2. 点击「提交到公司技能市场」，填写描述和说明
3. 系统创建 pending 状态的条目和首个版本
4. 管理员在审批面板看到该提交
5. 管理员审批通过，条目变为 approved，市场可见
6. 其他用户可在市场浏览并安装

### 场景 2：版本更新

1. 已上架技能的作者修改草稿
2. 提交新版本，选择"新增功能"，填写发布说明
3. 系统生成新版本号（如 1.0.0 → 1.1.0），冻结内容
4. 审批通过后，市场显示最新版本
5. 已安装用户看到「可更新」提示
6. 用户手动更新，若有本地修改则确认覆盖风险

### 场景 3：管理员直接发布

1. 管理员创建或选择技能
2. 直接发布到市场，填写描述和发布说明
3. 系统跳过审批，直接 approved
4. 市场可见，安装次数开始累计

### 场景 4：下架

1. 管理员下架某公司技能
2. 市场不再展示该技能
3. 已安装用户的个人副本保留，可继续使用和编辑
4. 历史版本、贡献记录和安装统计保留

### 场景 5：内置技能

1. 系统启动时初始化内置技能市场条目
2. 用户可在市场「系统内置」分组浏览
3. 安装内置技能生成个人副本
4. 安装次数累计
