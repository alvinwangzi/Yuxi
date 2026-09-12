"""变量模板解析 — 将 {{变量名}} 替换为 context 中的实际值。"""

from __future__ import annotations

import re
from typing import Any

# 匹配 {{变量名}} 和 {{变量名.子字段}}
_TEMPLATE_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def resolve_template(value: Any, context: dict[str, Any]) -> Any:
    """递归解析值中的 {{变量}} 模板。

    - 字符串中的 {{var}} 被替换为 context[var] 的字符串形式
    - 如果整个字符串就是一个 {{var}}（无其他文本），直接返回原始类型
    - dict/list 递归处理
    - 其他类型原样返回
    """
    if isinstance(value, str):
        return _resolve_string(value, context)
    if isinstance(value, dict):
        return {k: resolve_template(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_template(item, context) for item in value]
    return value


def _resolve_string(template: str, context: dict[str, Any]) -> Any:
    """解析字符串模板。若整个字符串就是一个变量引用，返回原始类型。"""
    # 整体匹配：{{var}} 无其他文本 → 返回原始值（保留类型）
    whole_match = _TEMPLATE_RE.fullmatch(template)
    if whole_match:
        return _lookup(whole_match.group(1), context)

    # 部分替换：{{var}} 嵌入文本中 → 全部转为字符串
    def _replacer(m: re.Match) -> str:
        val = _lookup(m.group(1), context)
        return "" if val is None else str(val)

    return _TEMPLATE_RE.sub(_replacer, template)


def _lookup(path: str, context: dict[str, Any]) -> Any:
    """按点分路径从 context 中查找 值。"""
    parts = path.split(".")
    current: Any = context
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def extract_variable_refs(value: Any) -> set[str]:
    """提取值中所有 {{变量名}} 引用的变量名集合。"""
    refs: set[str] = set()
    if isinstance(value, str):
        refs.update(_TEMPLATE_RE.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            refs.update(extract_variable_refs(v))
    elif isinstance(value, list):
        for item in value:
            refs.update(extract_variable_refs(item))
    return refs


def evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
    """简单条件表达式求值。

    支持:
    - "{{var}} contains keyword" — 字符串包含
    - "{{var}} == value" — 等值比较
    - "{{var}} > N" / "< N" / ">= N" / "<= N" — 数值比较
    - 纯 "{{var}}" — 真值判断
    """
    resolved = resolve_template(condition, context)
    if not isinstance(resolved, str):
        return bool(resolved)

    text = resolved.strip()

    # contains 检查
    m = re.match(r"^(.+?)\s+contains\s+(.+)$", text, re.IGNORECASE)
    if m:
        return m.group(2).strip() in m.group(1).strip()

    # 比较运算符
    for op, fn in [
        ("==", lambda a, b: a == b),
        ("!=", lambda a, b: a != b),
        (">=", lambda a, b: _to_float(a) >= _to_float(b)),
        ("<=", lambda a, b: _to_float(a) <= _to_float(b)),
        (">", lambda a, b: _to_float(a) > _to_float(b)),
        ("<", lambda a, b: _to_float(a) < _to_float(b)),
    ]:
        if op in text:
            parts = text.split(op, 1)
            if len(parts) == 2:
                return fn(parts[0].strip(), parts[1].strip())

    # 真值判断
    return bool(text)


def _to_float(value: Any) -> float:
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return 0.0
