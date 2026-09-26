"""模型服务异常到用户可见中文文案的映射，原始错误全文作为排查详情返回。"""

import re

_DETAIL_MAX_LENGTH = 2000

_CONTEXT_LIMIT_RE = re.compile(
    r"exceed_context_size_error"
    r"|context_length_exceeded"
    r"|exceeds? the (?:available )?context (?:size|length)"
    r"|maximum context length"
    r"|context length (?:is )?exceeded",
    re.IGNORECASE,
)
_REQUESTED_TOKENS_RE = re.compile(r"request(?:ed)? \(?(\d+) tokens\)?", re.IGNORECASE)
_LIMIT_TOKENS_RE = re.compile(r"context (?:size|length)\s*(?:is)?\s*\(?(\d+) tokens\)?", re.IGNORECASE)
_STATUS_CODE_RE = re.compile(r"Error code: (\d{3})")

_AUTH_RE = re.compile(
    r"invalid_api_key|invalid api key|incorrect api key|api key not valid|unauthorized|authentication",
    re.IGNORECASE,
)
_MODEL_NOT_FOUND_RE = re.compile(r"model_not_found|no such model|model not found|does not exist", re.IGNORECASE)
_RATE_LIMIT_RE = re.compile(r"rate.?limit|too many requests|insufficient_quota|quota", re.IGNORECASE)
_CONNECTION_RE = re.compile(
    r"timed out|timeout|connection (?:error|refused|reset|closed)|failed to establish",
    re.IGNORECASE,
)
_SERVER_ERROR_RE = re.compile(r"internal server error|bad gateway|service unavailable|overloaded", re.IGNORECASE)

_CONTEXT_MESSAGE = "建议新建对话或精简引用的资料后重试；如有需要，可在模型配置中调大上下文窗口。"


def _extract_status(exc: BaseException, raw: str) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    match = _STATUS_CODE_RE.search(raw)
    return int(match.group(1)) if match else None


def _extract_token_numbers(text: str) -> tuple[int | None, int | None]:
    requested = _REQUESTED_TOKENS_RE.search(text)
    limit = _LIMIT_TOKENS_RE.search(text)
    return (
        int(requested.group(1)) if requested else None,
        int(limit.group(1)) if limit else None,
    )


def _context_message(text: str) -> str:
    requested, limit = _extract_token_numbers(text)
    if requested and limit:
        detail = f"（本次请求约 {requested} tokens，上限 {limit} tokens）"
    elif limit:
        detail = f"（上限 {limit} tokens）"
    elif requested:
        detail = f"（本次请求约 {requested} tokens）"
    else:
        detail = ""
    return f"对话内容超出模型的上下文窗口限制{detail}。{_CONTEXT_MESSAGE}"


def friendly_model_error(exc: BaseException) -> tuple[str, str]:
    """返回（用户可见中文文案, 原始错误详情），供错误消息持久化与流式 chunk 使用。"""
    raw = str(exc) or exc.__class__.__name__
    text = raw.lower()
    status = _extract_status(exc, raw)

    if _CONTEXT_LIMIT_RE.search(text):
        message = _context_message(raw)
    elif status == 401 or _AUTH_RE.search(text):
        message = "模型服务认证失败，请检查模型配置中的 API Key 是否正确有效。"
    elif status == 404 or _MODEL_NOT_FOUND_RE.search(text):
        message = "未找到指定的模型，请检查智能体所配置的模型名称与供应商是否正确。"
    elif status == 429 or _RATE_LIMIT_RE.search(text):
        message = "模型服务请求过于频繁或已超出配额，请稍后重试。"
    elif _CONNECTION_RE.search(text):
        message = "连接模型服务失败或请求超时，请检查网络连接与模型服务地址后重试。"
    elif (status and status >= 500) or _SERVER_ERROR_RE.search(text):
        message = "模型服务暂时不可用，请稍后重试；若持续出现请联系管理员。"
    elif status:
        message = f"模型服务返回异常（HTTP {status}），请稍后重试；若持续出现请联系管理员。"
    else:
        message = "处理本次请求时出现异常，请稍后重试；若持续出现请联系管理员。"

    return message, raw[:_DETAIL_MAX_LENGTH]
