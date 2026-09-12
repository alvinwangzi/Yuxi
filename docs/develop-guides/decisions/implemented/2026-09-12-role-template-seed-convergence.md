# 角色模板库：软删除表结构对齐 role_key 与目录驱动 seed 收敛

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/storage/postgres/manager.py

## 问题

角色模板页面（/roles）点击即 500：`GET /api/roles` 返回 500，而 `/api/roles/categories` 正常。容器日志显示 `InFailedSQLTransactionError: current transaction is aborted` 发生在同请求后续的 `SELECT count(*) FROM role_templates` 上。

因果链由三处缺陷叠加：

1. v10 迁移把 `role_template_deletions` 建成 `(category, role_id)` 结构，而 `role_template_repository.get_deleted_role_keys()` 查询 `role_key` 列 → UndefinedColumnError；
2. repository 的 `get_deleted_role_keys()` 用 `except Exception: return set()` 吞掉异常，但 PostgreSQL 事务已进入 aborted 状态，吞异常并未消除事务污染；
3. 同请求后续的计数查询在 aborted 事务上执行 → InFailedSQLTransactionError → 500。

页面无数据的根因是 v10 初版 seed 三重缺陷：目录路径多一层 storage、非递归扫描（277 个模板 md 全在子目录、一级目录为空）、误 seed 的 20 个 role_template 分类与实际角色目录（`yuxi.agents.roles.CATEGORY_MAP`）大面积不匹配。且该 seed 位于 `custom_categories` COUNT==0 守卫内，对版本号已是 10 的存量库永远不再执行，无法自愈。

前端另有 5 处契约不匹配（分类字段 `label`、列表参数 `category_id`、role_key 拆分、管理端 URL、`res.success` 响应判定），使页面即使拿到数据也无法完成分类过滤、详情、导入、重分类交互。

## 决策

- `role_template_deletions` 表结构收敛为 `(role_key, deleted_by, deleted_at)`，唯一约束 `uq_role_template_deletions(role_key)`，与 Repository 的 role_key 语义对齐（`role_key = "目录/角色id"`，角色 id 本身可含子目录路径）。
- `get_deleted_role_keys()` 移除吞异常：表由 schema 迁移保证存在，查询失败让异常直接抛出，避免 aborted 事务把一个可诊断错误放大成整请求 500。
- 新增 `PostgresManager.repair_role_template_seed(conn)`：目录驱动、幂等的收敛函数——检测到旧 `(category, role_id)` 结构的软删除表直接重建；`role_templates` 为空时按 `CATEGORY_MAP` 补齐 role_template 内置分类并递归导入全部角色目录模板（icon/color 取 frontmatter）；导入后清理已无模板引用的内置分类（用户自建分类不受影响）。
- `ensure_business_schema` 与 `storage_migration.main()` 的 `business_version == 10` 分支都调用该收敛函数：fresh schema 与存量库走同一条收敛路径，存量库无需推进版本号即可自愈。
- role_key 含 `/`，`role_router` 的重分类路由参数改为 `{role_key:path}`。
- 前端 `RoleTemplatePanel.vue` / `workflow_api.js` / `useCategories.js` 对齐后端真实契约：分类展示 `label`、过滤用 `category_id`、`splitRoleKey` 拆 role_key、管理端 URL `/api/roles`、统一 `res.success` 判定。

## 替代方案

- 只修表结构不动 seed：500 消失但列表仍为空，用户无法验收角色模板库。
- 在 repository 层捕获 UndefinedColumnError 后重建表：把 schema 演进责任塞进请求路径，违背"持久化查询属于 repositories、schema 归迁移器"的边界，且每次请求都可能触发 DDL。
- 推进到 v11 重跑 seed：要求所有环境重新执行迁移并推进版本，只为修复 v10 自身缺陷代价不成比例；旧结构检测与重建本身就必须幂等，收敛函数已覆盖该需求。
- 前端维持错误契约并加兼容层（label/name 双读）：掩盖契约不匹配，后续每个消费方都要重复兼容，而不是在事实 Owner 处闭合。

## 后果

- 旧结构软删除表重建会丢弃其中记录；实际该表从未成功写入过数据（INSERT 同样引用不存在语义的列），无真实数据损失面，丢失仅使被删角色重新可见。
- `repair_role_template_seed` 在 API/worker 启动与 storage-migrator 运行时都会执行；稳态下只有一条 COUNT 查询的成本（模板非空即返回），不构成启动负担。
- role_template 内置分类的唯一事实来源从迁移硬编码列表变为 `yuxi.agents.roles.CATEGORY_MAP`（目录驱动）；新增角色目录自动补齐分类与模板，但删除目录不会自动清理已导入模板，清理仍走管理接口的软删除/硬删除。
- 前端 `splitRoleKey` 假设 role_key 首段为目录、其余为角色 id；role_key 结构若变化需同步该函数与后端路由。

## 验证

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| `/api/roles` 返回 200 且含全部目录角色模板 | aborted 事务导致 500 或列表缺模板 | `backend/server/routers/role_router.py` 的 list + `backend/package/yuxi/repositories/role_template_repository.py` | 浏览器实测页面渲染 277 张角色卡片；psql `SELECT count(*) FROM role_templates` = 277 | `get_deleted_role_keys` 查询失败时同请求后续语句报 InFailedSQLTransactionError（修复前复现） | Passed |
| 软删除表结构与 Repository 的 role_key 查询对齐 | UndefinedColumnError 被吞后事务污染 | `repair_role_template_seed` 的旧结构检测 + `get_deleted_role_keys` | psql `\d role_template_deletions`：仅 role_key/deleted_by/deleted_at，唯一约束 `uq_role_template_deletions` | 对仍持旧结构的库执行列表接口，旧代码在正确原因（缺 role_key 列）上失败 | Passed |
| 分类与模板按角色目录收敛且幂等 | 重复导入、分类与目录不匹配、误 seed 分类残留 | `backend/package/yuxi/storage/postgres/manager.py` 的 `repair_role_template_seed` | storage-migrator 执行后日志"角色模板库 seed 收敛完成"；psql 验证 20 个 role_template 内置分类全部有模板引用、无孤儿内置分类；API 容器重启后 ensure_business_schema 再走一遍收敛路径，数据不变 | 对模板非空库重复执行 repair 只产生 COUNT 查询即返回 | Passed |
| 含 `/` 的 role_key 重分类路由可达 | FastAPI 按 `/` 切分路径参数导致 404 | `backend/server/routers/role_router.py` 的 `{role_key:path}` | 浏览器对 `game-development/unity/...` 等深层 role_key 执行重分类成功 | 去掉 `:path` 修饰后同请求 404（FastAPI 默认语义） | Passed |
| 前端列表/分类过滤/详情/导入全链路可用 | 字段与参数契约不匹配导致静默失效 | `web/src/components/roles/RoleTemplatePanel.vue` / `web/src/apis/workflow_api.js` / `web/src/composables/useCategories.js` | 浏览器 E2E：20 个中文分类标签带计数、切换销售部过滤出 9 张卡片、详情抽屉渲染 frontmatter 内容、导入创建 Agent 成功、清理测试数据后数据库一致 | 分类 label 缺失时标签空白；category_id 参数名错误时过滤退化为全量 | Passed |
| 既有单测与契约脚本不回归 | 新增查询破坏 fake-conn 测试或契约校验 | `backend/test/unit/storage/test_postgres_manager_schema.py` / `scripts/verify_engineering_contracts.py` | 修改后 test_postgres_manager_schema + test_lifespan 与 checkout HEAD 版 manager.py 基线逐项一致（12 failed / 9 passed，失败预先存在：`_RecordingConnection.execute` 返回 None，HEAD 代码的 `SELECT COUNT(*) FROM custom_categories` scalar 读取同样崩溃）；stash 全部修改后 summary_graph_config/tool_approval 6 失败在 HEAD 同样复现；分批跑全部 unit 共 21 失败，归因均为预先存在或工作区其他任务修改（sandbox 3 失败在单独 stash `agents/backends/sandbox/provider.py` 后全绿），本次修改新增失败 0 | 在 fake conn 上对本次新增查询 scalar 读（与 HEAD 同模式崩溃，非本次引入） | Passed |

未验证范围：`repair_role_template_seed` 无自动化测试覆盖——现有 fake-conn 测试模式（execute 返回 None）与 ensure_business_schema 中任何 scalar 读取不兼容，该批测试在 HEAD 上已失败，属预先存在缺口而非本次引入；本次正确性由真实 PostgreSQL 迁移 + 浏览器 E2E 证明。旧结构重建的"已有软删除数据"分支因线上无此类数据未实测。前端 5 处契约修复以真实页面交互验证，未新增前端单测。
