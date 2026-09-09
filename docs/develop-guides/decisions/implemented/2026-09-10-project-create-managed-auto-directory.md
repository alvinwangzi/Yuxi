# 新建项目默认 managed 自动创建目录

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/services/project_service.py

## 问题

手动新建项目此前强制 linked 模式：用户必须从 Workspace 根开始浏览并选中一个已存在目录。两个缺陷叠加造成真实事故：

1. WorkspacePathPicker 在 directory 模式下单击目录 = 进入浏览 + 选中，且默认只禁选根 `/`，用户创建 P2 时误选了 `projects` 受控根目录本身（在 P2 内发消息会作用于整个 projects 子树）。
2. 后端 `create_workspace_directory` 拒绝在 projects 子树内写入（`_reject_projects_subtree_write`，防未注册目录产生"创建后不可见"问题），因此弹窗内"新建文件夹"必然 400 失败——用户没有顺畅的"为项目创建专属目录"路径，只能误绑已有目录。

## 决策

- 后端 `create_project_view` 支持 managed 模式的手动创建：自动分配 `projects/<时间戳>_<project_id前8位>` 目录，提交事务后立即用 `ensure_bound_user_workdir` 物化；物化失败显式 500，不伪装成功。
- 幂等重放：managed 只比较名称与模式（workdir 由服务端分配）；名称不匹配返回 409；重放时目录缺失则补物化。
- 前端 AppLayout 新建项目弹窗移除目录选择器，只填项目名（mode=managed），提示"项目目录将自动创建在个人空间的 projects 文件夹下"。
- ProjectSelectionSection 双模式：从历史对话入口预填目录时走 linked 绑定（保留选择器与 root-path 限制），普通新建走 managed 自动创建。
- WorkspacePathPicker 新增 `rootPath` 导航上限：面包屑不显示 root 之上层级，越界导航被忽略；越界的预填路径（历史 linked 目录）面包屑安全回退为根单项。

## 替代方案

1. 放开 `_reject_projects_subtree_write`，允许弹窗内新建文件夹——被否：同一 API 的其他调用方（个人空间页面）会在 projects 下产生未注册的不可见目录，老可见性问题回归；且"先建目录再绑定"仍比"只填名字"多一步。
2. managed 目录改用项目名命名（P2 → projects/P2）——被否：`normalize_managed_workdir_path` 的受控命名被沙盒路径解析、workdir 边界校验等多处依赖，扩展命名格式风险大；时间戳命名与 implicit 项目语义一致。
3. 仅前端禁选 projects 根（上一轮修复）——必要但不充分：没解决"用户必须有目录才能建项目"的根本负担。

## 后果

- 新建项目零目录决策负担；项目名与文件夹名无对应关系（与既有 implicit 语义一致）。
- linked 仍是复用已有目录的合法路径，后端不禁止绑定 projects 子树（`Workdir.open_existing` 语义不变），选择约束由前端 rootPath/unselectable 承担。
- managed 重放协议放宽为"只比较名称与模式"，与 linked 的全字段比较不同，两套语义并存。

## 验证

- `test/unit/services/test_project_service.py` 23 passed：含新增自动物化、重放补物化、重放名称冲突 409、物化失败 500、非法目录入参 422 五组用例。
- 前端 ESLint 三文件通过；`workspace_action_semantics.test.js` 4 passed。
- 数据库确认：重建的 P2 为 `managed` + `projects/2026-09-10_00-12-34_9b96c78c`，workdir 目录已物化；旧 linked P2 已 deleted。
