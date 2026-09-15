"""结束步骤执行器 — 工作流输出出口。

用模板渲染最终输出：
- template 支持 {变量名} 引用输入变量与上游步骤 output_key 写入的上下文值
- 未配置 template 时返回依赖步骤在 context 中的输出快照（仅含配置了 output_key 的上游）
"""

from __future__ import annotations

from typing import Any

from yuxi.workflows.executors import BaseStepExecutor
from yuxi.workflows.template import resolve_template


class EndStepExecutor(BaseStepExecutor):
    """输出出口步骤：渲染模板汇总最终输出。"""

    async def execute(self, step_data: dict[str, Any], context: dict[str, Any], **kwargs) -> Any:
        template = step_data.get("template", "")
        fmt = step_data.get("format", "markdown")

        if template:
            # 整体引用一个变量时 resolve_template 保留原始类型（JSON 输出场景），
            # 混合文本时已自动转为字符串
            rendered = resolve_template(template, context)
            return {"format": fmt, "content": rendered}

        # 无模板时回退：引擎只把配置了 output_key 的上游输出写入 context，
        # 此处仅收集这部分，保证出口有可观察结果而不猜测上游输出
        deps = step_data.get("depends_on", [])
        collected = {dep: context.get(dep) for dep in deps if dep in context}
        return {"format": fmt, "content": collected}
