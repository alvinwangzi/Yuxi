# Web 约定

修改本目录时应用根 [AGENTS.md](../AGENTS.md)；UI 改动读取[设计规范](../docs/develop-guides/design.md)相关章节，陌生模块查[架构](../ARCHITECTURE.md)。纯阅读不触发实现或测试流程。

- 普通 HTTP API 统一封装在 `src/apis`，组件不自行拼接。
- 复用 `src/assets/css/base.css` 变量与 `@lucide/vue`；一次性视觉需求不引入新依赖。
- 保持 loading、empty、error、断线恢复与终态投影一致；乐观 UI 不覆盖后端最终事实。
- `pnpm run lint:check` 只读检查，`pnpm run lint` 会修改文件。

UI 改动必须启动或复用开发服务并在真实页面验证，适用时覆盖浅/深色、响应式及 loading、empty、error。交付必要的脱敏最终截图或录屏，清理中间截图，不在源码目录遗留产物；无法验证时明确未覆盖范围。

前端代码提交前执行 lint、unit 和 build；命令与证据标准统一见[测试规范](../docs/develop-guides/testing-guidelines.md)。仅修改本目录规则或说明文档时按文档层级验证，根规则的提交前必跑检查仍适用。
