"""工作流引擎 — DAG 编排、步骤类型、变量模板。"""

# 步骤类型注册表
STEP_TYPES: dict[str, str] = {
    "start": "工作流输入入口（定义输入变量，必须是唯一起点）",
    "llm": "调用大模型（需选角色/Agent 配置）",
    "tool": "调用已注册工具（含 MCP 工具）",
    "http": "HTTP API 调用",
    "condition": "条件分支",
    "approval": "人工审批（暂停等待确认）",
    "script": "Python 脚本执行",
    "output": "格式化输出 + 交付（页面展示/文件/消息推送）",
    "end": "工作流输出出口（汇总最终输出，唯一终点）",
}

VALID_STEP_TYPES = frozenset(STEP_TYPES.keys())
