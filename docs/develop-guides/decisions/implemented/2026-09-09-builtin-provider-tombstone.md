# 内置模型供应商墓碑与设置入口收敛

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/models/providers/repository.py

## 问题

`ensure_builtin_model_providers_in_db` 在每次启动时补齐 `BUILTIN_PROVIDERS` 中缺失的条目，且只增不删。管理员删除内置供应商后（如 SiliconFlow、MiniMax），下一次 API 重启该供应商即被复活。此前仅从模板目录移除 MiniMax 条目，无法解决已部署环境中既有行被重建的问题。

## 决策

`model_providers` 表新增 `deleted_at` 墓碑列（业务 schema 版本 7 → 8）。内置供应商删除时保留行并写入 `deleted_at`，`list/get` 查询过滤墓碑行，启动 ensure 遇到墓碑直接跳过；同 id 重新创建前先物理清除墓碑行以释放唯一键。非内置供应商删除保持物理删除。模型供应商管理面板从智能体管理页移至设置弹窗（仅管理员可见），其页面位置与配置语义一致。

## 替代方案

仅从 `BUILTIN_PROVIDERS` 移除模板条目只能影响未部署环境；已部署环境的历史行仍会被 ensure 补回。启动时反向删除数据库中不在模板清单内的内置行，会把管理员编辑过的配置一并清除，破坏"只补不覆盖"契约。引入独立的删除标记表则把同一事实拆到两处，读写一致性由调用方维护，不如列级墓碑直接。

## 后果

墓碑行持续占用 `provider_id` 唯一键，重建同 id 供应商依赖创建路径的清理分支；直接操作数据库插入同 id 行会遇到唯一键冲突。`get_model_provider_with_tombstone` 只服务 ensure 与创建复活判断，其他调用方继续使用过滤后的查询。

## 验证

`backend/test/unit/services/test_model_provider_service.py` 覆盖三处 guard：repository 删除内置供应商写入 `deleted_at` 而非物理删除、ensure 跳过墓碑不重建、创建前物理清除墓碑。

真实环境验证：业务 schema 迁移执行后 `deleted_at` 列生效；将 `siliconflow-cn` 置为墓碑状态并重启 API，重启后该行 `deleted_at` 保持不变，供应商未复活。
