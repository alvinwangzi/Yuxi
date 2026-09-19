# Backend 约定

修改本目录时应用根 [AGENTS.md](../AGENTS.md)；陌生模块先读[架构](../ARCHITECTURE.md)对应章节。纯阅读不触发实现或测试流程。

## 后端补充边界

- 跨 repository 用例只有一个 service 事务 Owner；需要经 HTTP 返回的一次性 secret 必须支持幂等安全重放，凭据撤销保留阻止同一请求复活 secret 的 tombstone。
- 写入事实、提交事务、发布队列或事件的顺序必须显式；通知不能早于 owning transaction 的 commit point。
- AgentRun 的状态转换、lease、输出和终态投影由 repository/service 统一维护，调用方不得拼装并行真相。
- 内部值依赖 Python 类型、同进程契约与已有约束，不重复 hostile validation。
- Schema 演进由 `storage-migrator` 拥有，必须幂等、可在现有数据上执行；API 与 worker 只校验版本。不可逆操作先明确数据影响。

## 实现

- Python 使用 3.12+ 语法，主流程优先早返回；公开高层方法在上，实现细节逐层下沉。拆函数须服务明确复用、隔离副作用或实质降低认知负担。
- 常量放在最小合理作用域；跨函数复用、协议标识与配置约束使用模块级常量。
- 命名表达业务意图；不跨模块导入下划线开头的私有标识，确需共享时改为公开命名。
- 清理本次修改产生的无用 import、变量、函数与分支；原有无关死代码只报告，不顺手处理。
- 小型状态或摘要需求直接读取来源，不重建事件流或调试视图。
- 不同语义的代码段之间留空行；异常仅在能增加稳定语义、执行清理或决定策略时捕获。

## 验证

按[测试规范](../docs/develop-guides/testing-guidelines.md)选择最小相关集合及后端 lint；命令是按风险选择的入口，不因阅读本文件自动全跑。

并发、事务、锁、lease、Schema 与 PostgreSQL 专属语义须在真实 PostgreSQL 上验证；API 用真实 HTTP integration，关键 Run/worker/文件副作用用 E2E。提交前必跑检查仍适用，具体命令只在测试规范维护。
