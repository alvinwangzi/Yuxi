---
name: github-deep-research
description: "对 GitHub 仓库进行多轮深度研究，结合 GitHub API、联网搜索和内容提取，生成包含执行摘要、时间线、指标分析和 Mermaid 图表的结构化 Markdown 报告。当用户提供 GitHub 仓库 URL 或要求分析开源项目时使用。"
---

# GitHub Deep Research Skill

Multi-round research combining GitHub API, `web_search`, `web_fetch` to produce comprehensive markdown reports.

## Research Workflow

- Round 1: GitHub API
- Round 2: Discovery
- Round 3: Deep Investigation
- Round 4: Deep Dive

## Core Methodology

### Query Strategy

**Broad to Narrow**: Start with GitHub API, then general queries, refine based on findings.

```
Round 1: GitHub API
Round 2: "{topic} overview"
Round 3: "{topic} architecture", "{topic} vs alternatives"
Round 4: "{topic} issues", "{topic} roadmap", "site:github.com {topic}"
```

**Source Prioritization**:
1. Official docs/repos (highest weight)
2. Technical blogs (Medium, Dev.to)
3. News articles (verified outlets)
4. Community discussions (Reddit, HN)
5. Social media (lowest weight, for sentiment)

### Research Rounds

**Round 1 - GitHub API**

Enter the skill directory and execute `scripts/github_api.py`:

```bash
cd /home/gem/skills/github-deep-research
python scripts/github_api.py <owner> <repo> summary
python scripts/github_api.py <owner> <repo> readme
python scripts/github_api.py <owner> <repo> tree
```

**Available commands** (the last argument of `github_api.py`):
- summary, info, readme, tree, languages, contributors, commits, issues, prs, releases

If `GITHUB_TOKEN` environment variable is set, the script uses it for higher rate limits.

**Round 2 - Discovery** (3-5 `web_search`)
- Get overview and identify key terms
- Find official website/repo
- Identify main players/competitors

**Round 3 - Deep Investigation** (5-10 `web_search` + `web_fetch`)
- Technical architecture details
- Timeline of key events
- Community sentiment
- Use `web_fetch` on valuable URLs for full content

**Round 4 - Deep Dive**
- Analyze commit history for timeline
- Review issues/PRs for feature evolution
- Check contributor activity

## Report Structure

Follow template in `assets/report_template.md`:

1. **Metadata Block** - Date, confidence level, subject
2. **Executive Summary** - 2-3 sentence overview with key metrics
3. **Chronological Timeline** - Phased breakdown with dates
4. **Key Analysis Sections** - Topic-specific deep dives
5. **Metrics & Comparisons** - Tables, growth charts
6. **Strengths & Weaknesses** - Balanced assessment
7. **Sources** - Categorized references
8. **Confidence Assessment** - Claims by confidence level
9. **Methodology** - Research approach used

### Mermaid Diagrams

Include diagrams where helpful:

**Timeline (Gantt)**:
```mermaid
gantt
    title Project Timeline
    dateFormat YYYY-MM-DD
    section Phase 1
    Development    :2025-01-01, 2025-03-01
```

**Architecture (Flowchart)**:
```mermaid
flowchart TD
    A[User] --> B[Coordinator]
    B --> C[Planner]
```

## Confidence Scoring

| Confidence | Criteria |
|------------|----------|
| High (90%+) | Official docs, GitHub data, multiple corroborating sources |
| Medium (70-89%) | Single reliable source, recent articles |
| Low (50-69%) | Social media, unverified claims, outdated info |

## Output

Save report as: `outputs/research_{topic}_{YYYYMMDD}.md`

### Formatting Rules

- Chinese content: Use full-width punctuation（，。：；！？）
- Technical terms: Provide Wiki/doc URL on first mention
- Tables: Use for metrics, comparisons
- Mermaid: For architecture, timelines, flows

## Best Practices

1. **Start with official sources** - Repo, docs, company blog
2. **Verify dates from commits/PRs** - More reliable than articles
3. **Triangulate claims** - 2+ independent sources
4. **Note conflicting info** - Don't hide contradictions
5. **Always include inline citations** - Use `[citation:Title](URL)` format immediately after each claim

## Allowed Tools

- terminal: execute `scripts/github_api.py`
- web_search: discover information about the project
- web_fetch: extract full content from valuable URLs
- present_artifacts: present the final report

## Notes

- Set `GITHUB_TOKEN` in the sandbox environment for higher API rate limits (optional, unauthenticated requests still work with lower limits)
- The script has a `requests` → `urllib` fallback, so no pip install is needed
- This skill complements `deep-research` — use both for comprehensive project analysis
