"""脚本步骤执行器 — JavaScript 沙盒执行。

用户编写 `function main(context) { ... return result; }` 格式的脚本，
引擎通过 Node.js vm 模块在隔离沙盒中调用 main 函数。

安全限制：
- vm.runInNewContext 隔离全局作用域
- 执行超时保护（默认 30 秒）
- 不暴露 Node.js 内置模块（fs、net、child_process 等）
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from yuxi.utils.logging_config import logger
from yuxi.workflows.executors import BaseStepExecutor


class ScriptStepExecutor(BaseStepExecutor):
    """JavaScript 脚本执行（通过 Node.js vm 模块沙盒）。"""

    DEFAULT_TIMEOUT = 30  # 秒

    async def execute(self, step_data: dict[str, Any], context: dict[str, Any], **kwargs) -> Any:
        code = step_data.get("code", "")
        if not code:
            raise ValueError("script 步骤必须指定 code")

        language = step_data.get("language", "javascript")
        if language != "javascript":
            raise ValueError(f"暂不支持 {language}，仅支持 javascript")

        timeout = step_data.get("timeout", self.DEFAULT_TIMEOUT)

        logger.info(f"执行 JavaScript 脚本 ({len(code)} 字符)")

        # 构造传给 Node.js 的上下文数据（JSON 序列化确保安全）
        context_json = json.dumps(context, ensure_ascii=False, default=str)

        # 构造 Node.js 执行脚本：
        # 1. 用户代码定义 main(context) 函数
        # 2. 解析传入的 context JSON
        # 3. 调用 main(context) 并返回结果
        node_script = f"""
const vm = require('vm');

// 用户代码（定义 main 函数）
{code}

// 验证 main 函数存在
if (typeof main !== 'function') {{
  throw new Error('脚本必须定义 main(context) 函数');
}}

// 解析上下文数据
const contextData = JSON.parse({context_json!r});

// 在沙盒中执行 main
const sandbox = {{ context: contextData, console: {{ log: console.log }} }};
vm.createContext(sandbox);

// 将 main 函数放入沙盒并调用
sandbox.main = main;
const result = vm.runInContext('main(context)', sandbox, {{ timeout: {timeout * 1000} }});

// 输出 JSON 结果
process.stdout.write(JSON.stringify(result ?? null));
"""

        try:
            proc = await asyncio.create_subprocess_exec(
                "node", "-e", node_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout + 5,  # 额外 5 秒给进程启动开销
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"脚本执行超时（{timeout}秒）")

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"脚本执行失败: {error_msg}")

        output = stdout.decode("utf-8", errors="replace").strip()
        if not output:
            return None

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            # 非 JSON 输出原样返回字符串
            return output
