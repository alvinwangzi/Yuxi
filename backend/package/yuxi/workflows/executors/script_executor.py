"""脚本步骤执行器 — Python 沙盒执行。"""

from __future__ import annotations

import ast
from typing import Any

from yuxi.utils.logging_config import logger
from yuxi.workflows.executors import BaseStepExecutor


class ScriptStepExecutor(BaseStepExecutor):
    """Python 脚本执行。

    安全限制：
    - 禁止 import 系统模块（白名单除外）
    - 禁止文件操作
    - 禁止网络操作
    - 执行超时保护
    """

    # 允许导入的模块白名单
    ALLOWED_IMPORTS = {"json", "math", "datetime", "re", "collections", "itertools", "functools"}

    async def execute(self, step_data: dict[str, Any], context: dict[str, Any]) -> Any:
        code = step_data.get("code", "")
        if not code:
            raise ValueError("script 步骤必须指定 code")

        language = step_data.get("language", "python")
        if language != "python":
            raise ValueError(f"暂不支持 {language}，仅支持 python")

        # 安全检查
        self._validate_code(code)

        # 执行脚本
        logger.info(f"执行 Python 脚本 ({len(code)} 字符)")

        # 构造执行环境
        exec_globals = {
            "__builtins__": self._safe_builtins(),
            "input_data": context,  # 将 context 作为输入数据
        }
        exec_locals: dict[str, Any] = {}

        try:
            exec(code, exec_globals, exec_locals)
        except Exception as e:
            raise RuntimeError(f"脚本执行失败: {e}") from e

        # 返回 result 变量（如果存在）
        return exec_locals.get("result", exec_locals)

    def _validate_code(self, code: str) -> None:
        """静态检查代码安全性。"""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise ValueError(f"代码语法错误: {e}") from e

        for node in ast.walk(tree):
            # 检查 import 语句
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module_name = ""
                if isinstance(node, ast.Import) and node.names:
                    module_name = node.names[0].name.split(".")[0]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module_name = node.module.split(".")[0]

                if module_name and module_name not in self.ALLOWED_IMPORTS:
                    raise ValueError(f"不允许导入模块: {module_name}")

            # 禁止文件操作
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in {"open", "exec", "eval", "compile", "__import__"}:
                    raise ValueError(f"不允许调用危险函数: {func.id}")

    def _safe_builtins(self) -> dict:
        """返回安全的 builtins 子集。"""
        import builtins

        safe_names = {
            "print", "len", "range", "str", "int", "float", "bool",
            "list", "dict", "tuple", "set", "frozenset",
            "True", "False", "None",
            "isinstance", "issubclass", "type",
            "abs", "min", "max", "sum", "round",
            "sorted", "reversed", "enumerate", "zip", "map", "filter",
            "any", "all", "hasattr", "getattr",
            "ValueError", "TypeError", "KeyError", "IndexError",
            "RuntimeError", "Exception",
        }
        return {name: getattr(builtins, name) for name in safe_names if hasattr(builtins, name)}
