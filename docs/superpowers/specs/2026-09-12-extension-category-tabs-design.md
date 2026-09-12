# 技能/智能体/工具 二级分类标签栏设计

## 目标

在技能、智能体、工具、MCP 四个扩展管理页面中，新增水平可滚动的二级分类标签栏，替代/补充现有的平铺展示方式，帮助用户快速按业务场景筛选内容。

## 分类体系（四页面共用）

| key | 显示名 | 含义 |
|-----|--------|------|
| `all` | 全部 | 不过滤 |
| `office` | 办公协同 | 文档处理、邮件、日程、会议、表单、审批 |
| `dev` | 开发工具 | 编码、调试、部署、版本控制、数据库管理 |
| `data` | 数据分析 | 数据查询、可视化、报表、金融数据 |
| `content` | 内容创作 | 写作、翻译、设计、音视频、PPT/文档排版 |
| `info` | 信息资讯 | 新闻、搜索、知识检索、行业动态、舆情 |
| `business` | 商业运营 | CRM、营销、电商、项目管理、财务 |
| `productivity` | 效率工具 | 自动化、reminders、工作流编排 |
| `other` | 其他 | 未匹配到以上分类 |

## 分类推断规则

### 技能（Skills）

基于 `slug`、`name`、`tool_dependencies`、`mcp_dependencies` 的关键词匹配（不区分大小写）：

| 分类 | 关键词 |
|------|--------|
| `office` | excel, word, docx, pdf, ppt, xlsx, email, imap, smtp, calendar, sheet, 表格, 文档, 邮件, 日程, 会议 |
| `dev` | code, git, deploy, debug, terminal, shell, sql, mysql, postgres, api, docker, 代码, 部署, 调试 |
| `data` | data, chart, analytics, query, stock, finance, wind, 数据, 分析, 报表, 金融, 股票 |
| `content` | write, translate, image, video, audio, blog, article, markdown, 写作, 翻译, 设计, 文稿 |
| `info` | search, news, web, rss, crawl, monitor, alert, 搜索, 新闻, 资讯, 舆情, 监控 |
| `business` | crm, marketing, sales, ecommerce, shop, finance, invoice, project, 营销, 销售, 电商, 财务, 项目, 运营, 客户 |
| `productivity` | automate, workflow, reminder, schedule, task, 自动化, 工作流, 提醒, 任务 |

匹配优先级：按上表顺序，命中第一个分类即停止。均未命中则归入 `other`。

### 工具（Tools）

映射已有 `category` 字段：
- `buildin` → `productivity`
- `knowledge` → `productivity`
- `mysql` → `data`
- `debug` → `dev`

### 智能体（Agents）

基于 `name` + `description` 关键词匹配，规则同技能。

### MCP 服务

基于 `name` + `description` + `tags` 关键词匹配，规则同技能。

## UI 设计

### 位置

在每个页面的 `PageShoulder`（搜索栏）下方、卡片列表上方，新增一行水平可滚动的分类标签栏。

### 交互

- 默认选中「全部」
- 每个标签显示：分类名 + 该分类下的数量（如 `办公协同 12`）
- 点击切换分类，与搜索关键词联动（先按分类过滤，再按关键词搜索）
- 分类栏可水平滚动（溢出时）
- 无匹配时显示空状态

### 样式

复用现有 `.tab-item` / `.tab-item.active` 设计令牌，与 PageHeader 中的 tab 样式保持一致。

## 实现范围

### 新增文件

| 文件 | 说明 |
|------|------|
| `web/src/utils/itemCategory.js` | 分类推断工具函数（三页面共用） |

### 修改文件

| 文件 | 改动 |
|------|------|
| `web/src/components/extensions/SkillCardList.vue` | 新增分类标签栏；「推荐套件」保持不变，始终显示在分类过滤结果之上 |
| `web/src/components/extensions/ToolsCardList.vue` | 下拉选择器替换为水平标签栏 |
| `web/src/components/extensions/McpCardList.vue` | 新增分类标签栏 |
| `web/src/components/model-management/AgentManagePanel.vue` | 新增分类标签栏 |

### 不变的部分

- 技能页面的「推荐套件」区域保持不变
- 批量管理模式不受分类影响
- 后端无需改动（纯前端推断）

## 验收标准

1. 四个页面均显示分类标签栏，默认选中「全部」
2. 点击分类标签后，仅显示该分类下的卡片，数量角标正确
3. 分类过滤与搜索关键词联动正常
4. 工具页原有下拉选择器被标签栏替代，功能等价
5. 无回归：批量管理、推荐套件、详情跳转等现有功能不受影响
