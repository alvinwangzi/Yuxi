"""技能安全扫描器 - 基于 NVIDIA SkillSpector 模式

静态分析技能内容，检测潜在安全风险。
覆盖 6 大类漏洞模式：Prompt 注入、数据外泄、权限提升、供应链风险、过度代理、危险代码。
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Severity(str, Enum):
    """风险严重度"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class Finding:
    """扫描发现"""
    rule_id: str
    category: str
    severity: Severity
    message: str
    file: str = ""
    line: int = 0
    snippet: str = ""


@dataclass
class ScanResult:
    """扫描结果"""
    score: int
    severity: str
    recommendation: str
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "severity": self.severity,
            "recommendation": self.recommendation,
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "category": f.category,
                    "severity": f.severity.value,
                    "message": f.message,
                    "file": f.file,
                    "line": f.line,
                    "snippet": f.snippet,
                }
                for f in self.findings
            ],
        }


# ── 风险评分权重 ──────────────────────────────────────────────────────────────

_SEVERITY_WEIGHT: dict[Severity, int] = {
    Severity.CRITICAL: 25,
    Severity.HIGH: 15,
    Severity.MEDIUM: 8,
    Severity.LOW: 3,
    Severity.INFO: 1,
}


def _compute_score(findings: list[Finding]) -> int:
    """计算风险评分 (0-100)"""
    total = sum(_SEVERITY_WEIGHT.get(f.severity, 0) for f in findings)
    return min(total, 100)


def _severity_label(score: int) -> str:
    if score >= 76:
        return "高风险"
    if score >= 51:
        return "中风险"
    if score >= 26:
        return "低风险"
    return "安全"


def _recommendation(score: int) -> str:
    if score >= 76:
        return "禁止审批通过，存在严重安全风险"
    if score >= 51:
        return "建议人工审查后决定是否通过"
    if score >= 26:
        return "存在轻微风险，可审批通过"
    return "未发现安全风险，可安全安装"


# ── Prompt 注入检测 ──────────────────────────────────────────────────────────

_PROMPT_INJECTION_PATTERNS: list[tuple[str, str, Severity, re.Pattern[str]]] = [
    ("P1", "指令覆盖", Severity.HIGH, re.compile(
        r"(?:ignore\s+(?:all\s+)?(?:previous|above|safety|system|content)\s*(?:instructions?|rules?|constraints?|guidelines?)"
        r"|forget\s+(?:all\s+)?(?:previous|above|safety|system|content)\s*(?:instructions?|rules?|constraints?|guidelines?)"
        r"|do\s+not\s+(?:follow|obey|adhere\s+to)\s*(?:your\s+)?(?:safety|system|content)\s*(?:rules?|guidelines?|instructions?))",
        re.IGNORECASE,
    )),
    ("P2", "隐藏指令", Severity.HIGH, re.compile(
        r"(?:hidden\s+(?:instruction|directive|command)|"
        r"(?:secret(?:ly)?\s+(?:do|execute|run|perform))|"
        r"(?:<!--.*?(?:instruction|directive|command).*?-->)|"
        r"(?:\[\[.*?(?:instruction|directive|command).*?\]\]))",
        re.IGNORECASE,
    )),
    ("P3", "数据外传指令", Severity.HIGH, re.compile(
        r"(?:send|transmit|exfiltrate|leak|post)\s+(?:all\s+)?(?:the\s+)?(?:conversation|context|chat|history|messages?|data|content)"
        r"(?:\s+(?:to|at|via)\s+(?:https?://|www\.))?",
        re.IGNORECASE,
    )),
    ("P5", "有害内容指令", Severity.CRITICAL, re.compile(
        r"(?:create|generate|produce|make|build)\s+(?:a\s+)?(?:bomb|weapon|virus|malware|exploit|backdoor|keylogger|ransomware)",
        re.IGNORECASE,
    )),
    ("P9", "空白填充", Severity.MEDIUM, re.compile(
        r"(?:\s{500,}|[\n\r]{100,})",
    )),
]


# ── 反拒绝检测 ────────────────────────────────────────────────────────────────

_ANTI_REFUSAL_PATTERNS: list[tuple[str, str, Severity, re.Pattern[str]]] = [
    ("AR1", "拒绝抑制", Severity.HIGH, re.compile(
        r"(?:never\s+refuse|always\s+comply|do\s+not\s+refuse|you\s+must\s+(?:always|never)\s+(?:comply|obey|follow))",
        re.IGNORECASE,
    )),
    ("AR2", "免责声明抑制", Severity.HIGH, re.compile(
        r"(?:no\s+disclaimers?|do\s+not\s+(?:warn|disclaimer|moralize|preach)|"
        r"(?:omit|skip|ignore)\s+(?:all\s+)?(?:warnings?|disclaimers?|ethical\s+commentary))",
        re.IGNORECASE,
    )),
    ("AR3", "安全策略废止", Severity.HIGH, re.compile(
        r"(?:you\s+have\s+no\s+restrictions|ignore\s+your\s+guidelines|"
        r"do\s+anything\s+now|DAN\s+mode|jailbreak)",
        re.IGNORECASE,
    )),
]


# ── 数据外泄检测 ──────────────────────────────────────────────────────────────

_DATA_EXFIL_PATTERNS: list[tuple[str, str, Severity, re.Pattern[str]]] = [
    ("E1", "外部传输", Severity.MEDIUM, re.compile(
        r"(?:requests?|urllib|httpx|aiohttp)\.(?:post|put|get|request)\s*\("
        r"(?:.*?https?://)",
        re.IGNORECASE,
    )),
    ("E2", "环境变量收集", Severity.HIGH, re.compile(
        r"(?:os\.environ|os\.getenv|process\.env|System\.getenv)"
        r"(?:\s*\[?\s*(?:['\"](?:API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)['\"])?\s*\]?)",
        re.IGNORECASE,
    )),
    ("E3", "文件系统枚举", Severity.MEDIUM, re.compile(
        r"(?:os\.listdir|os\.walk|os\.scandir|pathlib\.Path\.(?:glob|rglob|iterdir))"
        r"(?:\s*\(\s*(?:['\"](?:/|~|\.|C:\\))?)",
        re.IGNORECASE,
    )),
    ("E4", "上下文泄露", Severity.HIGH, re.compile(
        r"(?:conversation|context|chat|history|messages?)\s*(?:\.|->)?\s*(?:content|text|data)"
        r"(?:.*?(?:send|transmit|post|upload|exfiltrate))",
        re.IGNORECASE,
    )),
]


# ── 权限提升检测 ──────────────────────────────────────────────────────────────

_PRIV_ESC_PATTERNS: list[tuple[str, str, Severity, re.Pattern[str]]] = [
    ("PE2", "sudo/root 执行", Severity.MEDIUM, re.compile(
        r"(?:sudo|su\s+-|runas)\s+(?:-\w+\s+)*(?:bash|sh|python|node|exec)",
        re.IGNORECASE,
    )),
    ("PE3", "凭证访问", Severity.HIGH, re.compile(
        r"(?:\.ssh|\.aws|\.gcp|\.azure|id_rsa|id_dsa|\.pem|\.key|credentials|\.netrc)",
        re.IGNORECASE,
    )),
]


# ── 供应链风险检测 ────────────────────────────────────────────────────────────

_SUPPLY_CHAIN_PATTERNS: list[tuple[str, str, Severity, re.Pattern[str]]] = [
    ("SC2", "外部脚本获取", Severity.HIGH, re.compile(
        r"(?:curl|wget)\s+.*?\|\s*(?:bash|sh|python|node)",
        re.IGNORECASE,
    )),
    ("SC3", "混淆代码", Severity.HIGH, re.compile(
        r"(?:base64\.b64decode|base64\.decode|atob|Buffer\.from\([^)]*base64\))"
        r"(?:\s*\(\s*['\"][A-Za-z0-9+/=]{20,}['\"]\s*\))",
        re.IGNORECASE,
    )),
]


# ── 过度代理检测 ──────────────────────────────────────────────────────────────

_EXCESSIVE_AGENCY_PATTERNS: list[tuple[str, str, Severity, re.Pattern[str]]] = [
    ("EA1", "无限制工具访问", Severity.HIGH, re.compile(
        r"(?:unrestricted|unlimited|full|complete|all)\s+(?:tool|function|action|capability)\s+(?:access|use)",
        re.IGNORECASE,
    )),
    ("EA2", "自主决策", Severity.HIGH, re.compile(
        r"(?:autonomous|automatic|self-?directed)\s+(?:decision|action|execution|operation)"
        r"(?:.*?(?:without\s+human|without\s+approval|without\s+confirmation))?",
        re.IGNORECASE,
    )),
]


# ── 危险代码 AST 检测 ─────────────────────────────────────────────────────────

_DANGEROUS_CALLS: dict[str, tuple[str, Severity]] = {
    "exec": ("AST1", Severity.CRITICAL),
    "eval": ("AST2", Severity.HIGH),
    "__import__": ("AST3", Severity.HIGH),
    "compile": ("AST6", Severity.MEDIUM),
}

_DANGEROUS_MODULES: dict[str, tuple[str, Severity]] = {
    "subprocess": ("AST4", Severity.HIGH),
    "os": ("AST5", Severity.HIGH),
    "shutil": ("AST5", Severity.HIGH),
}


def _scan_text(content: str, filename: str = "") -> list[Finding]:
    """扫描文本内容（SKILL.md 等）"""
    findings: list[Finding] = []

    all_patterns = (
        _PROMPT_INJECTION_PATTERNS
        + _ANTI_REFUSAL_PATTERNS
        + _DATA_EXFIL_PATTERNS
        + _PRIV_ESC_PATTERNS
        + _SUPPLY_CHAIN_PATTERNS
        + _EXCESSIVE_AGENCY_PATTERNS
    )

    for rule_id, name, severity, pattern in all_patterns:
        for match in pattern.finditer(content):
            line_no = content[:match.start()].count("\n") + 1
            snippet = content[match.start() : match.end()]
            if len(snippet) > 80:
                snippet = snippet[:80] + "..."
            findings.append(Finding(
                rule_id=rule_id,
                category="Prompt 注入" if rule_id.startswith("P") or rule_id.startswith("AR")
                else "数据外泄" if rule_id.startswith("E")
                else "权限提升" if rule_id.startswith("PE")
                else "供应链风险" if rule_id.startswith("SC")
                else "过度代理",
                severity=severity,
                message=f"检测到{name}模式",
                file=filename,
                line=line_no,
                snippet=snippet,
            ))

    return findings


def _scan_python(source: str, filename: str = "") -> list[Finding]:
    """扫描 Python 源码（AST 分析）"""
    findings: list[Finding] = []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        # 检测危险函数调用
        if isinstance(node, ast.Call):
            func = node.func
            func_name: str | None = None

            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                func_name = func.attr

            if func_name and func_name in _DANGEROUS_CALLS:
                rule_id, severity = _DANGEROUS_CALLS[func_name]
                findings.append(Finding(
                    rule_id=rule_id,
                    category="危险代码",
                    severity=severity,
                    message=f"检测到 {func_name}() 调用",
                    file=filename,
                    line=node.lineno,
                    snippet=func_name + "(...)",
                ))

        # 检测危险模块导入
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _DANGEROUS_MODULES:
                    rule_id, severity = _DANGEROUS_MODULES[alias.name]
                    findings.append(Finding(
                        rule_id=rule_id,
                        category="危险代码",
                        severity=severity,
                        message=f"导入危险模块 {alias.name}",
                        file=filename,
                        line=node.lineno,
                        snippet=f"import {alias.name}",
                    ))

        if isinstance(node, ast.ImportFrom):
            if node.module and node.module in _DANGEROUS_MODULES:
                rule_id, severity = _DANGEROUS_MODULES[node.module]
                findings.append(Finding(
                    rule_id=rule_id,
                    category="危险代码",
                    severity=severity,
                    message=f"从危险模块 {node.module} 导入",
                    file=filename,
                    line=node.lineno,
                    snippet=f"from {node.module} import ...",
                ))

    return findings


def scan_skill_content(
    skill_md: str,
    scripts: dict[str, str] | None = None,
) -> ScanResult:
    """扫描技能内容

    Args:
        skill_md: SKILL.md 文件内容
        scripts: 脚本文件名 -> 内容映射

    Returns:
        ScanResult 扫描结果
    """
    findings: list[Finding] = []

    # 扫描 SKILL.md
    findings.extend(_scan_text(skill_md, filename="SKILL.md"))

    # 扫描 Python 脚本
    if scripts:
        for name, content in scripts.items():
            findings.extend(_scan_text(content, filename=name))
            if name.endswith(".py"):
                findings.extend(_scan_python(content, filename=name))

    score = _compute_score(findings)
    return ScanResult(
        score=score,
        severity=_severity_label(score),
        recommendation=_recommendation(score),
        findings=findings,
    )


def scan_skill_directory(skill_dir: Path) -> ScanResult:
    """扫描技能目录

    Args:
        skill_dir: 技能目录路径

    Returns:
        ScanResult 扫描结果
    """
    skill_md = ""
    scripts: dict[str, str] = {}

    skill_md_path = skill_dir / "SKILL.md"
    if skill_md_path.exists():
        skill_md = skill_md_path.read_text(encoding="utf-8")

    scripts_dir = skill_dir / "scripts"
    if scripts_dir.is_dir():
        for py_file in scripts_dir.glob("*.py"):
            scripts[py_file.name] = py_file.read_text(encoding="utf-8")

    return scan_skill_content(skill_md, scripts)
