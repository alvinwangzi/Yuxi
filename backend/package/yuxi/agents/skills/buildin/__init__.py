from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuiltinSkillSpec:
    slug: str
    source_dir: Path
    description: str = ""
    version: str = "1.0.0"
    tool_dependencies: tuple[str, ...] = ()
    mcp_dependencies: tuple[str, ...] = ()
    skill_dependencies: tuple[str, ...] = ()
    auto_install: bool = True


_SKILLS_ROOT = Path(__file__).resolve().parent

BUILTIN_SKILLS: list[BuiltinSkillSpec] = [
    BuiltinSkillSpec(
        slug="image-gen",
        source_dir=_SKILLS_ROOT / "image-gen",
        description="在 Agent 沙盒中生成图片并保存到 outputs，使用管理员配置的图片生成模型。",
        version="2026.09.12",
        tool_dependencies=("present_artifacts",),
    ),
    BuiltinSkillSpec(
        slug="html-preview",
        source_dir=_SKILLS_ROOT / "html-preview",
        description=(
            "使用 Markdown `html:preview` 围栏输出轻量静态 HTML/CSS 可视化，"
            "适合数值对比、流程、时间线、层级关系和关键指标。"
        ),
        version="2026.07.23",
    ),
    BuiltinSkillSpec(
        slug="chart-renderer",
        source_dir=_SKILLS_ROOT / "chart-renderer",
        description=(
            "使用 `chart:render` 围栏输出 ECharts 交互式图表，"
            "支持柱状图、折线图、饼图、散点图和雷达图。"
        ),
        version="2026.09.11",
    ),
    BuiltinSkillSpec(
        slug="deep-research",
        source_dir=_SKILLS_ROOT / "deep-research",
        description="深度研究编排方法论：澄清范围、拆解规划、并行调度子智能体调研、对抗式核验、综合成带引用的结构化报告。",
        version="2026.07.29",
        tool_dependencies=("web_search",),
        skill_dependencies=("html-preview",),
    ),
    BuiltinSkillSpec(
        slug="knowledge-base",
        source_dir=_SKILLS_ROOT / "knowledge-base",
        description="使用 Yuxi 知识库进行检索、打开文档、文档内定位和查看思维导图。",
        version="2026.06.24",
        tool_dependencies=(
            "list_kbs",
            "query_kb",
            "find_kb_document",
            "open_kb_document",
            "get_mindmap",
            "search_file",
            "download_kb_file",
        ),
    ),
    BuiltinSkillSpec(
        slug="mysql-reporter",
        source_dir=_SKILLS_ROOT / "mysql-reporter",
        description="基于 MySQL 数据库生成查询报表和可视化图表，适合分析业务指标、统计趋势，并用 Charts MCP 展示结果。",
        version="2026.06.05",
        mcp_dependencies=("mcp-server-chart",),
    ),
    BuiltinSkillSpec(
        slug="data-analysis",
        source_dir=_SKILLS_ROOT / "data-analysis",
        description="分析上传的 Excel/CSV 文件：查看结构、SQL 查询、统计摘要、导出结果。基于 DuckDB 内存分析引擎。",
        version="2026.09.11",
        tool_dependencies=("present_artifacts",),
    ),
    BuiltinSkillSpec(
        slug="academic-paper-review",
        source_dir=_SKILLS_ROOT / "academic-paper-review",
        description="对学术论文进行结构化同行评审级分析，覆盖方法论评估、贡献评价、文献定位和建设性反馈。",
        version="2026.09.11",
        tool_dependencies=("web_search", "present_artifacts"),
    ),
    BuiltinSkillSpec(
        slug="consulting-analysis",
        source_dir=_SKILLS_ROOT / "consulting-analysis",
        description="生成麦肯锡/BCG 级别的专业研究报告，两阶段工作流：先生成分析框架，再基于数据生成最终报告。",
        version="2026.09.11",
        tool_dependencies=("present_artifacts",),
    ),
    BuiltinSkillSpec(
        slug="code-documentation",
        source_dir=_SKILLS_ROOT / "code-documentation",
        description="为代码项目生成专业文档，支持 README、API 参考、架构文档、变更日志和开发者指南。",
        version="2026.09.11",
        tool_dependencies=("present_artifacts",),
    ),
    BuiltinSkillSpec(
        slug="frontend-design",
        source_dir=_SKILLS_ROOT / "frontend-design",
        description="创建高质量、有设计感的前端界面，避免千篇一律的 AI 风格。",
        version="2026.09.11",
        tool_dependencies=("present_artifacts",),
    ),
    BuiltinSkillSpec(
        slug="newsletter-generation",
        source_dir=_SKILLS_ROOT / "newsletter-generation",
        description="从多源研究内容生成专业的 Newsletter、邮件摘要、行业周报或内容简报。",
        version="2026.09.11",
        tool_dependencies=("web_search", "present_artifacts"),
    ),
    BuiltinSkillSpec(
        slug="web-design-guidelines",
        source_dir=_SKILLS_ROOT / "web-design-guidelines",
        description="基于 Vercel Web Interface Guidelines 审查 UI 代码合规性。",
        version="2026.09.11",
        tool_dependencies=("web_fetch",),
    ),
    BuiltinSkillSpec(
        slug="github-deep-research",
        source_dir=_SKILLS_ROOT / "github-deep-research",
        description="对 GitHub 仓库进行多轮深度研究，生成包含时间线、指标分析和 Mermaid 图表的结构化报告。",
        version="2026.09.11",
        tool_dependencies=("web_search", "present_artifacts"),
    ),
    BuiltinSkillSpec(
        slug="systematic-literature-review",
        source_dir=_SKILLS_ROOT / "systematic-literature-review",
        description="跨多篇论文进行系统性文献综述（SLR），搜索 arXiv 并输出 APA/IEEE/BibTeX 格式报告。",
        version="2026.09.11",
        tool_dependencies=("present_artifacts",),
    ),
    BuiltinSkillSpec(
        slug="music-generation",
        source_dir=_SKILLS_ROOT / "music-generation",
        description="通过 MiniMax 音乐 API 从风格/情绪提示和可选歌词生成歌曲（MP3）。",
        version="2026.09.11",
        tool_dependencies=("present_artifacts",),
    ),
    BuiltinSkillSpec(
        slug="podcast-generation",
        source_dir=_SKILLS_ROOT / "podcast-generation",
        description="将文字内容转换为双主持人对话式播客音频（MP3），支持 Volcengine 和 MiniMax TTS。",
        version="2026.09.11",
        tool_dependencies=("present_artifacts",),
    ),
    BuiltinSkillSpec(
        slug="video-generation",
        source_dir=_SKILLS_ROOT / "video-generation",
        description="通过结构化提示词和参考图片生成视频（MP4），支持 Gemini Veo 和 MiniMax Hailuo。",
        version="2026.09.11",
        tool_dependencies=("present_artifacts",),
    ),
    BuiltinSkillSpec(
        slug="dashi-ppt",
        source_dir=_SKILLS_ROOT / "dashi-ppt",
        description="制作 PPT、演示文稿、幻灯片、汇报材料时使用。基于预置视觉主题组合页面，生成可离线打开、可在浏览器编辑的 HTML 演示，支持导出 PPTX / PDF 文件。",
        version="0.4.13",
        tool_dependencies=("present_artifacts",),
    ),
]
