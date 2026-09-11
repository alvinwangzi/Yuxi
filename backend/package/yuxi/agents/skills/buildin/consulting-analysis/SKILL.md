---
name: consulting-analysis
description: "生成麦肯锡/BCG 级别的专业研究报告，覆盖市场分析、消费者洞察、财务分析、行业调研、竞品情报和投資尽调等。两阶段工作流：先生成分析框架，再基于数据生成最终报告。"
---

# Professional Research Report Skill

## Overview

This skill produces professional, consulting-grade research reports in Markdown format, covering domains such as **market analysis, consumer insights, brand strategy, financial analysis, industry research, competitive intelligence, investment research, and macroeconomic analysis**. It operates across two distinct phases:

1. **Phase 1 — Analysis Framework Generation**: Given a research subject, produce a rigorous analysis framework including chapter skeleton, per-chapter data requirements, analysis logic, and visualization plan.
2. **Phase 2 — Report Generation**: After data has been collected by other skills, synthesize all inputs into a final polished report.

The output adheres to McKinsey/BCG consulting voice standards. The report language follows the `output_locale` setting (default: `zh_CN` for Chinese).

## Data Authenticity Protocol

**Strict Adherence Rule**: All data presented in the report and visualized in charts MUST be derived directly from the provided **Data Summary** or **External Search Findings**.
- **NO Hallucinations**: Do not invent, estimate, or simulate data. If data is missing, state "Data not available" rather than fabricating numbers.
- **Traceable Sources**: Every major claim and chart must be traceable back to the input data package.

## When to Use This Skill

- User asks for a market analysis, consumer insight report, financial analysis, industry research, or any consulting-grade analytical report
- User provides a research subject and needs a structured analysis framework before data collection
- User provides data summaries, analysis frameworks, or chart files to be synthesized into a report
- The task involves transforming research findings into structured strategic narratives

---

# Phase 1: Analysis Framework Generation

## Phase 1 Inputs

| Input | Description | Required |
|-------|-------------|----------|
| **Research Subject** | The topic or question to be analyzed | Yes |
| **Scope / Constraints** | Geographic scope, time range, industry segment, target audience, etc. | Optional |
| **Specific Angles** | Any particular angles or hypotheses the user wants explored | Optional |
| **Domain** | The analytical domain: market, finance, industry, brand, consumer, investment, etc. | Inferred |

## Phase 1 Workflow

### Step 1.1: Understand the Research Subject

- Parse the research subject to identify the **core entity**
- Identify the **analytical domain** (marketing, finance, industry, competitive, consumer, investment, macro, etc.)
- Determine the **natural analytical dimensions** based on domain:

| Domain | Typical Dimensions |
|--------|--------------------|
| Market Analysis | Market size, growth trends, segmentation, growth drivers, competitive landscape, consumer profiling |
| Brand Analysis | Brand positioning, market share, consumer perception, marketing strategy, competitor comparison |
| Consumer Insights | Demographic profiling, purchase behavior, decision journey, pain points, scenario analysis |
| Financial Analysis | Macro environment, industry trends, company fundamentals, financial metrics, valuation, risk assessment |
| Industry Research | Value chain analysis, market size, competitive landscape, policy environment, technology trends |
| Investment Due Diligence | Business model, financial health, management assessment, market opportunity, risk factors |
| Competitive Intelligence | Competitor identification, strategic comparison, SWOT analysis, differentiated positioning |

### Step 1.2: Select Analysis Frameworks & Models

Based on the identified domain and research subject, select **2-4** most relevant professional analysis frameworks:

#### Strategic & Environmental Analysis
| Framework | Best For |
|-----------|----------|
| **SWOT Analysis** | Brand assessment, competitive positioning, strategic planning |
| **PEST / PESTEL Analysis** | Macro-environment scanning, market entry assessment |
| **Porter's Five Forces** | Industry competitive landscape, entry barrier assessment |
| **VRIO Analysis** | Core competency assessment, resource advantage analysis |

#### Market & Growth Analysis
| Framework | Best For |
|-----------|----------|
| **STP Analysis** | Market segmentation, target market selection, brand positioning |
| **BCG Matrix** | Product portfolio management, resource allocation decisions |
| **TAM-SAM-SOM** | Market sizing, opportunity quantification |
| **Product Life Cycle** | Product strategy formulation, market timing decisions |

#### Consumer & Behavioral Analysis
| Framework | Best For |
|-----------|----------|
| **Consumer Decision Journey** | Consumer behavior path mapping, touchpoint optimization |
| **AARRR Funnel** | User growth analysis, conversion rate optimization |
| **RFM Model** | Customer value segmentation, precision marketing |
| **Jobs-to-be-Done** | Demand insight, product innovation direction |

#### Financial & Valuation Analysis
| Framework | Best For |
|-----------|----------|
| **DuPont Analysis** | Profitability decomposition, financial health diagnosis |
| **DCF** | Enterprise/project valuation |
| **Comparable Company Analysis** | Relative valuation, peer benchmarking |

#### Selection Principles
1. **Domain-First**: Select **2-4** most relevant frameworks
2. **Complementary**: Choose complementary rather than overlapping frameworks
3. **Depth over Breadth**: Better to deeply apply 2 frameworks than superficially stack 6
4. **Data-Feasible**: Selected frameworks must be supportable by downstream data collection

### Step 1.3: Design Chapter Skeleton

Each chapter must include:
1. **Chapter Title** — Professional, concise, subject-based
2. **Analysis Objective** — What this chapter aims to reveal
3. **Analysis Logic** — The reasoning chain or framework
4. **Core Hypothesis** — Preliminary hypotheses to be validated

### Step 1.4: Define Data Query Requirements Per Chapter

| Field | Description |
|-------|-------------|
| **Data Metric** | The specific metric or data point needed |
| **Data Type** | Quantitative, Qualitative, or Mixed |
| **Suggested Sources** | Industry reports, financial statements, government statistics, etc. |
| **Search Keywords** | Suggested search queries for data collection agents |
| **Priority** | P0 (Required) / P1 (Important) / P2 (Supplementary) |
| **Time Range** | The time period the data should cover |

### Step 1.5: Define Visualization & Content Structure Per Chapter

| Field | Description |
|-------|-------------|
| **Visualization Type** | Chart type: Line, bar, pie, scatter, radar, heatmap, etc. |
| **Visualization Title** | Descriptive title for the chart |
| **Visualization Data Mapping** | Which data indicators map to X/Y axes or segments |
| **Argument Structure** | The planned "What → Why → So What" narrative outline |

### Step 1.6: Output Complete Analysis Framework

Assemble all outputs into a single structured document.

## Phase 1 Quality Checklist

- [ ] Framework covers all natural dimensions for the identified domain
- [ ] 2-4 professional analysis frameworks are selected and explicitly mapped to chapters
- [ ] Each chapter has clear Analysis Objective, Analysis Logic, and Core Hypothesis
- [ ] Data requirements are specific, measurable, and include search keywords
- [ ] Every chapter has at least one visualization plan
- [ ] Data priorities (P0/P1/P2) are assigned realistically

---

# Phase 1→2 Handoff: Data Collection & Chart Generation

After the analysis framework is generated, it is handed off to **other data collection skills** (e.g., `deep-research`, `data-analysis`) to:

1. Execute the **Search Keywords** from each chapter's data requirements
2. Collect quantitative data, qualitative insights, and source URLs
3. Generate charts based on the **Visualization & Content Plan**
4. Return a **Data Package** containing Data Summary, Chart Files, and External Search Findings

> **This skill does NOT perform data collection.** It only produces the framework (Phase 1) and the final report (Phase 2).

---

# Phase 2: Report Generation

## Phase 2 Inputs

| Input | Description | Required |
|-------|-------------|----------|
| **Analysis Framework** | The framework document produced in Phase 1 | Yes |
| **Data Summary** | Collected data organized per chapter | Yes |
| **Chart Files** | Local file paths for generated chart images | Optional |
| **External Search Findings** | URLs and summaries for inline citations | Optional |

## Phase 2 Workflow

### Step 2.1: Receive and Validate Inputs
### Step 2.2: Map Report Structure
### Step 2.3: Generate Chapter Charts (Pre-Report Visualization)

If chart files are not provided but a visualization skill is available, generate charts first. Use ONLY numbers from the Data Summary — do NOT invent data.

### Step 2.4: Write the Report

Follow the **"Visual Anchor → Data Contrast → Integrated Analysis"** flow per sub-chapter:

1. **Visual Evidence Block**: Embed charts using `![Description](path)`
2. **Data Contrast Table**: Markdown comparison table for key metrics
3. **Integrated Narrative Analysis**: "What → Why → So What" (min. 200 words per sub-chapter)

### Step 2.5: Final Structure Self-Check

Confirm: `Abstract → Introduction → Body Chapters → Conclusion → References`

## Formatting & Tone Standards

### Consulting Voice
- **Tone**: McKinsey/BCG — Authoritative, Objective, Professional
- **Number Formatting**: Use English commas for thousands separators
- **Data emphasis**: **Bold** important viewpoints and key numbers

### Titling Constraints
- **Forbidden Prefixes**: Do NOT use "Chapter", "Part", "Section" as prefixes
- **Forbidden Words**: "Decoding", "DNA", "Secrets", "Mindscape", "Unlocking"

### Insight Depth
Every insight must connect **Data → User Psychology → Strategy Implication**.

### References
- **Inline**: Use markdown links for sources
- **References section**: Formatted per **GB/T 7714-2015**

## Report Structure Template

```markdown
# [Report Title]

## Abstract
[Executive summary with key takeaways]

## 1. Introduction
[Background, objectives, methodology]

## 2. [Body Chapter Title]
### 2.1 [Sub-chapter Title]
![Chart Description](chart_file_path)

| Metric | Brand A | Brand B |
|--------|---------|--------|

[Integrated narrative analysis: What → Why → So What, min. 200 words]

## N+1. Conclusion
[Pure objective synthesis, NO bullet points, neutral tone]

## N+2. References
[1] Author. Title[EB/OL]. URL, Date.
```

## Quality Checklists

### Phase 2 Quality Checklist
- [ ] **NO HALLUCINATION**: All numbers verified against Data Summary
- [ ] All sections present in correct order
- [ ] Every sub-chapter follows "Visual Anchor → Data Contrast → Integrated Analysis"
- [ ] Every sub-chapter ends with min. 200-word analytical paragraph
- [ ] All insights follow "Data → User Psychology → Strategy Implication" chain
- [ ] References follow GB/T 7714-2015
- [ ] Conclusion uses flowing prose — no bullet points

## Settings

```
output_locale = zh_CN  # configurable per user request
reasoning_locale = en
```

## Output Format

- **Phase 1**: Output the complete Analysis Framework in Markdown
- **Phase 2**: Output the complete Report in Markdown
- Save to `outputs/` and present using `present_artifacts`

## Notes

- This skill operates in **two phases** of a multi-step agentic workflow
- **Data collection** is performed by other skills (`deep-research`, `data-analysis`, etc.)
- **ZERO HALLUCINATION POLICY**: Each statement, chart, and number must be supported by input data
- The Conclusion section must contain **NO** detailed recommendations — those belong in body chapters
- When the research subject is ambiguous, default to the broadest reasonable scope and note assumptions
