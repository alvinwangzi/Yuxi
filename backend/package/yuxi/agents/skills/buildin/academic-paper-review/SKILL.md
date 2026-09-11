---
name: academic-paper-review
description: "对学术论文进行结构化同行评审级分析，覆盖方法论评估、贡献评价、文献定位和建设性反馈。当用户提供论文 URL、上传 PDF、arXiv 链接，或要求「评审」「分析」「总结」研究论文时使用。"
---

# Academic Paper Review Skill

## Overview

This skill produces structured, peer-review-quality analyses of academic papers and research publications. It follows established academic review standards used by top-tier venues (NeurIPS, ICML, ACL, Nature, IEEE) to provide rigorous, constructive, and balanced assessments.

The review covers **summary, strengths, weaknesses, methodology assessment, contribution evaluation, literature positioning, and actionable recommendations** — all grounded in evidence from the paper itself.

## When to Use This Skill

- User provides a paper URL (arXiv, DOI, conference proceedings, journal link)
- User uploads a PDF of a research paper or preprint
- User asks to "review", "analyze", "critique", "assess", or "summarize" a research paper
- User wants to understand the strengths and weaknesses of a study
- User requests a peer-review-style evaluation of academic work

## Review Methodology

### Phase 1: Paper Comprehension

#### Step 1.1: Identify Paper Metadata

| Field | Description |
|-------|-------------|
| **Title** | Full paper title |
| **Authors** | Author list and affiliations |
| **Venue / Status** | Publication venue, preprint server, or submission status |
| **Year** | Publication or submission year |
| **Domain** | Research field and subfield |
| **Paper Type** | Empirical, theoretical, survey, position paper, systems paper, etc. |

#### Step 1.2: Deep Reading Pass

1. **Abstract & Introduction** — Identify the claimed contributions and motivation
2. **Related Work** — Note how authors position their work relative to prior art
3. **Methodology** — Understand the proposed approach, model, or framework in detail
4. **Experiments / Results** — Examine datasets, baselines, metrics, and reported outcomes
5. **Discussion & Limitations** — Note any self-identified limitations
6. **Conclusion** — Compare concluded claims against actual evidence presented

#### Step 1.3: Key Claims Extraction

```
Claim 1: [Specific claim about contribution or finding]
Evidence: [What evidence supports this claim in the paper]
Strength: [Strong / Moderate / Weak]
```

### Phase 2: Critical Analysis

#### Step 2.1: Literature Context Search

Use `web_search` and `web_fetch` to understand the research landscape:

```
Search queries:
- "[paper topic] state of the art [current year]"
- "[key method name] comparison benchmark"
- "[authors] previous work [topic]"
- "[specific technique] limitations criticism"
```

#### Step 2.2: Methodology Assessment

| Criterion | Questions to Ask | Rating |
|-----------|-----------------|--------|
| **Soundness** | Is the approach technically correct? Are there logical flaws? | 1-5 |
| **Novelty** | What is genuinely new vs. incremental improvement? | 1-5 |
| **Reproducibility** | Are details sufficient to reproduce? Code/data available? | 1-5 |
| **Experimental Design** | Are baselines fair? Are ablations adequate? | 1-5 |
| **Statistical Rigor** | Are results statistically significant? Error bars reported? | 1-5 |
| **Scalability** | Does the approach scale? Computational costs discussed? | 1-5 |

#### Step 2.3: Contribution Significance Assessment

| Level | Description | Criteria |
|-------|-------------|----------|
| **Landmark** | Fundamentally changes the field | New paradigm, widely applicable breakthrough |
| **Significant** | Strong contribution advancing the state of the art | Clear improvement with solid evidence |
| **Moderate** | Useful contribution with some limitations | Incremental but valid improvement |
| **Marginal** | Minimal advance over existing work | Small gains, narrow applicability |
| **Below threshold** | Does not meet publication standards | Fundamental flaws, insufficient evidence |

#### Step 2.4: Strengths and Weaknesses Analysis

For each strength or weakness:
- **What**: Specific observation
- **Where**: Section/figure/table reference
- **Why it matters**: Impact on the paper's claims or utility

### Phase 3: Review Synthesis

Produce the final review using the template below.

## Review Output Template

```markdown
# Paper Review: [Paper Title]

## Paper Metadata
- **Authors**: [Author list]
- **Venue**: [Publication venue or preprint server]
- **Year**: [Year]
- **Domain**: [Research field]
- **Paper Type**: [Empirical / Theoretical / Survey / Systems / Position]

## Executive Summary
[2-3 paragraph summary of core contribution, approach, and main findings.
State overall assessment upfront.]

## Summary of Contributions
1. [First claimed contribution — one sentence]
2. [Second claimed contribution — one sentence]

## Strengths
### S1: [Concise strength title]
[Detailed explanation with specific references]

## Weaknesses
### W1: [Concise weakness title]
[Detailed explanation with specific references and improvement suggestions]

## Methodology Assessment
| Criterion | Rating (1-5) | Assessment |
|-----------|:---:|------------|
| Soundness | X | [Brief justification] |
| Novelty | X | [Brief justification] |
| Reproducibility | X | [Brief justification] |
| Experimental Design | X | [Brief justification] |
| Statistical Rigor | X | [Brief justification] |
| Scalability | X | [Brief justification] |

## Questions for the Authors
1. [Specific question about methodology or claims]

## Literature Positioning
[How does this work relate to the current state of the art?]

## Recommendations
**Overall Assessment**: [Accept / Weak Accept / Borderline / Weak Reject / Reject]
**Confidence**: [High / Medium / Low]
**Contribution Level**: [Landmark / Significant / Moderate / Marginal / Below threshold]

### Actionable Suggestions for Improvement
1. [Specific, constructive suggestion]
```

## Review Principles

- **Always suggest how to fix** — Don't just point out problems; propose solutions
- **Give credit where due** — Acknowledge genuine contributions even in flawed papers
- **Be specific** — Reference exact sections, equations, figures, and tables
- **Separate minor from major** — Distinguish fatal flaws from fixable issues
- Do NOT dismiss work based on author reputation or affiliation
- Flag potential ethical concerns (bias in datasets, dual-use implications) constructively

## Adaptation by Paper Type

| Paper Type | Focus Areas |
|------------|-------------|
| **Empirical** | Experimental design, baselines, statistical significance, ablations |
| **Theoretical** | Proof correctness, assumption reasonableness, tightness of bounds |
| **Survey** | Comprehensiveness, taxonomy quality, coverage of recent work |
| **Systems** | Architecture decisions, scalability evidence, real-world deployment |
| **Position** | Argument coherence, evidence for claims, impact potential |

## Output Format

- Save the review to `outputs/review-{paper-topic}.md`
- Present the review to the user using `present_artifacts`

## Notes

- This skill complements `deep-research` — load both when the user wants the paper reviewed in the context of the broader field
- For papers behind paywalls, work with whatever content is accessible
- Adapt the review depth to the user's needs: brief assessment for quick triage vs. full review for submission preparation
- When reviewing multiple papers comparatively, maintain consistent criteria across all reviews
