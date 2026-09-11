---
name: systematic-literature-review
description: "跨多篇论文进行系统性文献综述（SLR），搜索 arXiv 并输出 APA/IEEE/BibTeX 格式报告。当用户要求对某个主题做文献调研、综述、跨论文比较或注释 bibliography 时使用。不适用于单篇论文评审（用 academic-paper-review）。"
---

# Systematic Literature Review Skill

## Overview

This skill produces a structured **systematic literature review (SLR)** across multiple academic papers on a research topic. Given a topic query, it searches arXiv, extracts structured metadata from each paper in parallel, synthesizes themes across the full set, and emits a final report with consistent citations.

**Distinct from `academic-paper-review`:** that skill does deep peer review of a single paper. This skill does breadth-first synthesis across many papers.

## When to Use This Skill

- A literature survey on a topic ("survey transformer attention variants")
- A synthesis across multiple papers ("what do recent papers say about X")
- A systematic review with consistent citation format ("do an SLR on Z in APA format")
- An annotated bibliography on a topic
- An overview of research trends in a field over a time window

Do **not** use this skill when:
- The user provides exactly one paper and asks to review it (use `academic-paper-review`)
- The user asks a factual question that does not require synthesizing multiple sources
- The user wants general web research without academic rigor

## Workflow

### Phase 1: Plan

Confirm the following with the user:

- **Topic**: the research area in plain English (e.g. "transformer attention variants")
- **Scope**: how many papers (default 20, hard upper bound 50), optional time window, optional arXiv category
- **Citation format**: APA, IEEE, or BibTeX (default APA)
- **Output location**: default `outputs/`

If the user says "50+ papers", cap at 50 and explain that synthesis quality degrades past that.

### Phase 2: Search arXiv

Enter the skill directory and call the bundled search script:

```bash
cd /home/gem/skills/systematic-literature-review
python scripts/arxiv_search.py "<topic>" \
  --max-results <N> \
  [--category <cat>] \
  [--sort-by relevance] \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD]
```

**IMPORTANT — extract 2-3 core keywords before searching.** Do not pass the user's full topic description as the query. Reduce the topic to its 2-3 most essential terms.

**Query phrasing — keep it short.** The script wraps multi-word queries in double quotes for phrase matching on arXiv:

| User says | Good query | Bad query |
|---|---|---|
| "diffusion models in computer vision" | `"diffusion models" --category cs.CV` | `"diffusion models in computer vision"` |
| "transformer attention variants" | `"transformer attention"` | `"transformer attention variants in NLP"` |

The script prints a JSON array to stdout. Each paper has: `id`, `title`, `authors`, `abstract`, `published`, `updated`, `categories`, `pdf_url`, `abs_url`.

**Sort strategy**: Always use `relevance` sorting. `submittedDate` only when user explicitly asks for chronological order.

**Run the search exactly once.** Do not retry with modified queries. If results are genuinely empty, tell the user and suggest broadening the topic.

**Do not save the search results to a file** — the JSON stays in your context for Phase 3.

### Phase 3: Extract metadata in parallel

**You MUST delegate extraction to subagents via the `task` tool — do not extract metadata yourself.**

Split papers into batches of ~5, then for each batch, call the `task` tool. Each subagent receives the paper abstracts as text and returns structured JSON.

**Concurrency limit: at most 3 subagents per turn.**

**Round strategy**:

| Paper count | Batches | Rounds | Per-round count |
|---|---|---|---|
| 1–5 | 1 | 1 | 1 |
| 6–10 | 2 | 1 | 2 |
| 11–15 | 3 | 1 | 3 |
| 16–20 | 4 | 2 | 3 + 1 |
| 21–30 | 5-6 | 2 | 3 + 2/3 |
| 31–50 | 7-10 | 3-4 | 3+3+... |

**Never dispatch more than 3 subagents in the same turn.**

**What each subagent receives**:

```
Execute this task: extract structured metadata and key findings from the
following arXiv papers.

Papers:
[Paper 1]
arxiv_id: 1706.03762
title: Attention Is All You Need
authors: Ashish Vaswani, Noam Shazeer, ...
published: 2017-06-12
abstract: <full abstract text>

For each paper, return a JSON object with these fields:
- arxiv_id (string)
- title (string)
- authors (list of strings)
- published_date (string, YYYY-MM-DD)
- research_question (1 sentence)
- methodology (1-2 sentences)
- key_findings (3-5 bullet points)
- limitations (1-2 sentences)

Return as a JSON array, one object per paper, in the same order as input.
```

**Parsing subagent results**: strip the `Task Succeeded. Result: ` prefix before parsing JSON. If a batch fails, note which papers were affected and continue.

### Phase 4: Synthesize and format

**Cross-paper synthesis**: identify:
- **Themes**: 3-6 recurring research directions
- **Convergences**: findings that multiple papers agree on
- **Disagreements**: where papers reach different conclusions
- **Gaps**: what the collective literature does not yet address

**Citation formatting**: read **only** the template file matching the user's format:
- [templates/apa.md](templates/apa.md) — APA 7th (default)
- [templates/ieee.md](templates/ieee.md) — IEEE numeric
- [templates/bibtex.md](templates/bibtex.md) — BibTeX (`@misc` for arXiv, not `@article`)

### Phase 5: Save and present

Save the full report to `outputs/slr-<topic-slug>-<YYYYMMDD>.md`. Then call `present_artifacts` with that path.

**In the chat message**, show a short preview:
1. **Executive summary** — 3-5 sentences from the top of the report
2. **Themes list** — bullet list of identified themes
3. **Paper count + pointer to file**

Do **not** dump the full 2000+ word report inline.

## Examples

**Example 1**: "Do a systematic literature review of recent transformer attention variants, 20 papers, APA format."
→ Phase 1: confirm topic, scope (20), format (APA)
→ Phase 2: `arxiv_search.py "transformer attention" --max-results 20 --sort-by relevance --start-date 2023-01-01`
→ Phase 3: 20 papers → round 1 (3 subagents) + round 2 (1 subagent)
→ Phase 4: read `templates/apa.md`, write report
→ Phase 5: save to `outputs/slr-transformer-attention-20260911.md`, present

**Example 2**: "Survey a few papers on diffusion models for me."
→ Ask: "How many papers — 10, 20, or 30? Any citation format preference (APA is default)?"
→ Proceed with user's answer

## Notes

- **Subagent dependency**: Phase 3 requires the `task` tool (subagent system). If subagents are unavailable, tell the user and offer to narrow the request.
- **arXiv only, by design**. This skill does not query Semantic Scholar, PubMed, or Google Scholar.
- **Hard upper bound of 50 papers**.
- **Synthesis, not listing**. A report that only lists papers one after another is a failure mode.

## Allowed Tools

- terminal: execute `scripts/arxiv_search.py`
- task: delegate metadata extraction to subagents (Phase 3)
- present_artifacts: present the final report
- web_search / web_fetch: supplement with additional context if needed
