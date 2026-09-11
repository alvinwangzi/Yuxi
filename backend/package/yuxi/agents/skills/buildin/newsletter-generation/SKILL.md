---
name: newsletter-generation
description: "从多源研究内容生成专业的 Newsletter、邮件摘要、行业周报或内容简报。支持按主题研究、内容策展和专业排版，适用于邮件分发或网页发布。"
---

# Newsletter Generation Skill

## Overview

This skill generates professional, well-researched newsletters that combine curated content from multiple sources with original analysis and commentary. It follows modern newsletter best practices from publications like Morning Brew, The Hustle, TLDR, and Benedict Evans.

The output is a complete, ready-to-publish newsletter in Markdown format, suitable for email distribution platforms, web publishing, or conversion to HTML.

## When to Use This Skill

- User asks to generate a newsletter, email digest, or content roundup
- User requests a curated summary of news or developments on a topic
- User wants to create a recurring newsletter format
- User asks to compile recent developments in a field into a briefing
- User asks for a "weekly roundup", "monthly digest", or "morning briefing"

## Newsletter Workflow

### Phase 1: Planning

#### Step 1.1: Understand Newsletter Requirements

| Parameter | Description | Default |
|-----------|-------------|---------|
| **Topic(s)** | Primary subject area(s) to cover | Required |
| **Format** | Daily digest, weekly roundup, deep-dive, or industry briefing | Weekly roundup |
| **Target Audience** | Technical, executive, general, or niche community | General |
| **Tone** | Professional, conversational, witty, or analytical | Conversational-professional |
| **Length** | Short (5-min read), medium (10-min), long (15-min+) | Medium |
| **Sections** | Number and type of content sections | 4-6 sections |

#### Step 1.2: Define Newsletter Structure

**Daily Digest**: Top Story (1) → Quick Hits (3-5) → Stat/Quote → What to Watch

**Weekly Roundup**: Editor's Note → Top Stories (2-3) → Trends & Analysis → Quick Bites (4-6) → Tools & Resources → Closing

**Deep-Dive**: Introduction → Background → Key Developments → Expert Perspectives → What's Next → Further Reading

**Industry Briefing**: Executive Summary → Market Developments → Company News → Product Updates → Regulatory Changes → Data & Metrics → Outlook

### Phase 2: Research & Curation

#### Step 2.1: Multi-Source Research

Use `web_search` for thorough research. **The quality of the newsletter depends directly on the quality and recency of research.**

**Search Strategy**:
```
# Current news and developments
"[topic] news [current month] [current year]"
"[topic] latest developments"

# Trends and analysis
"[topic] trends [current year]"
"[topic] analysis expert opinion"

# Data and statistics
"[topic] statistics [current year]"
"[topic] market data latest"
```

> **IMPORTANT**: Always check the current date to ensure search queries use the correct temporal context.

#### Step 2.2: Source Evaluation and Selection

| Criterion | Priority |
|-----------|----------|
| **Recency** | Prefer content from the last 7-30 days |
| **Authority** | Prioritize primary sources, official announcements |
| **Uniqueness** | Select stories that offer fresh perspective |
| **Relevance** | Every item must connect to the newsletter's topic(s) |
| **Actionability** | Prefer content readers can act on |
| **Diversity** | Mix of news, analysis, data, and practical resources |

#### Step 2.3: Deep Content Extraction

For key stories, use `web_fetch` to read full articles and extract:
1. **Core facts** — What happened, who is involved, when
2. **Context** — Why this matters, background information
3. **Data points** — Specific numbers, metrics, or statistics
4. **Quotes** — Relevant expert quotes or official statements
5. **Implications** — What this means for the reader

### Phase 3: Writing

#### Step 3.1: Section Writing Guidelines

**Top Stories / Featured Items**:
- **Headline**: Compelling, clear, benefit-oriented (not clickbait)
- **Hook**: Opening sentence that makes the reader care
- **Body**: Key facts and context (2-4 paragraphs)
- **Why it matters**: Connect to the reader's world
- **Source link**: Always attribute and link to the original source

**Quick Bites / Brief Items**:
- **Format**: Bold headline + 2-3 sentence summary + source link
- **Focus**: One key takeaway per item

**Analysis / Commentary Sections**:
- **Structure**: Observation → Context → Implication → Actionable takeaway
- **Evidence**: Every claim backed by data or sourced information

#### Step 3.2: Writing Standards

| Principle | Implementation |
|-----------|---------------|
| **Scannable** | Use headers, bold text, bullet points, short paragraphs |
| **Engaging** | Lead with the most interesting angle |
| **Concise** | Every sentence earns its place |
| **Accurate** | Every fact is sourced, every number verified |
| **Attributive** | Always credit original sources with inline links |

**Tone Calibration by Audience**:

| Audience | Tone |
|----------|------|
| **Technical** | Precise, assumed expertise |
| **Executive** | Impact-focused, strategic |
| **General** | Accessible, analogies |

### Phase 4: Assembly & Polish

#### Step 4.1: Quality Checklist

- [ ] **Every factual claim has a source link**
- [ ] **Date references use the actual current date**
- [ ] **Content is current** — All items from within expected timeframe
- [ ] **No duplicate stories**
- [ ] **Consistent formatting** throughout
- [ ] **Balanced coverage** — Not dominated by a single source
- [ ] **Engaging opening** — First 2 sentences make the reader want to continue
- [ ] **Clear closing** — Memorable or actionable note

## Newsletter Output Template

```markdown
# [Newsletter Name]

*[Tagline] — [Full date]*

---

[Preview sentence]

## Top Stories

### [Headline 1]
[Hook — why this matters in 1-2 sentences.]
[Body — 2-4 paragraphs covering key facts, context, and implications.]
**Why it matters:** [1 paragraph connecting to reader's interests.]
[Source](URL)

## Trends & Analysis

### [Trend Title]
[Original commentary backed by data from research.]
**The bottom line:** [One-sentence takeaway.]

## Quick Bites
- **[Headline]** — [2-3 sentence summary.] [Source](URL)

## Tools & Resources
- **[Tool Name]** — [What it does and why it's useful.] [Link](URL)

## One More Thing
[Closing thought, insightful quote, or forward-looking statement.]

---

*[Newsletter Name] curates the most important [topic] news and analysis.*
*All sources are linked inline. Views and commentary are original.*
```

## Output Handling

- Save the newsletter to `outputs/newsletter-{topic}-{date}.md`
- Present the newsletter to the user using `present_artifacts`
- Offer to adjust sections, tone, length, or focus areas

## Notes

- This skill works best in combination with `deep-research` for comprehensive topic coverage
- Always use the current date for temporal context in searches and date references
- For recurring newsletters, suggest maintaining a consistent structure
- When curating, quality beats quantity — 5 excellent items beat 15 mediocre ones
- Attribute all content properly — newsletters build trust through transparent sourcing
- If the user provides specific URLs or articles to include, incorporate them alongside curated findings
