---
name: code-documentation
description: "为代码项目生成专业文档，支持 README 生成、API 参考文档、内联代码注释、架构文档、变更日志和开发者指南。当用户要求「写文档」「生成 README」「生成 API 文档」或「写开发者指南」时使用。"
---

# Code Documentation Skill

## Overview

This skill generates professional, comprehensive documentation for software projects, codebases, libraries, and APIs. It follows industry best practices from projects like React, Django, Stripe, and Kubernetes.

The output ranges from single-file READMEs to multi-document developer guides, always matched to the project's complexity and the user's needs.

## When to Use This Skill

- User asks to "document", "create docs", or "write documentation" for any code
- User requests a README, API reference, or developer guide
- User shares a codebase or repository and wants documentation generated
- User asks to improve or update existing documentation
- User needs architecture documentation, including diagrams
- User requests a changelog or migration guide

## Documentation Workflow

### Phase 1: Codebase Analysis

#### Step 1.1: Project Discovery

| Field | How to Determine |
|-------|-----------------|
| **Language(s)** | Check file extensions, `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, etc. |
| **Framework** | Look at dependencies for known frameworks |
| **Build System** | Check for `Makefile`, `CMakeLists.txt`, `webpack.config.js`, etc. |
| **Package Manager** | npm/yarn/pnpm, pip/uv/poetry, cargo, go modules, etc. |
| **Project Structure** | Map out the directory tree |
| **Entry Points** | Find main files, CLI entry points, exported modules |
| **Existing Docs** | Check for existing README, docs/, wiki |

#### Step 1.2: Code Structure Analysis

Use sandbox tools to explore the codebase:

```bash
# Get directory structure
ls uploads/project-dir/

# Read key files
cat uploads/project-dir/package.json
cat uploads/project-dir/pyproject.toml

# Search for public API surfaces
grep -r "export " uploads/project-dir/src/
grep -r "def " uploads/project-dir/src/ --include="*.py"
```

#### Step 1.3: Identify Documentation Scope

| Project Size | Recommended Documentation |
|-------------|--------------------------|
| **Single file / script** | Inline comments + usage header |
| **Small library** | README with API reference |
| **Medium project** | README + API docs + examples |
| **Large project** | README + Architecture + API + Contributing + Changelog |

### Phase 2: Documentation Generation

#### Step 2.1: README Generation

```markdown
# Project Name
[One-line project description]

## Features
- [Key feature 1]

## Quick Start
### Prerequisites
### Installation
### Basic Usage

## API Reference
## Configuration
## Examples
## Development
### Setup
### Testing
### Building
## Contributing
## License
```

#### Step 2.2: API Reference Generation

For each public API surface, document:
- Function/method signature with parameters table
- Return type and description
- Throws/exceptions
- Usage examples

#### Step 2.3: Architecture Documentation

For medium-to-large projects, include:
- System diagram (Mermaid)
- Component overview
- Data flow description
- Design decisions with context/decision/rationale/trade-offs

#### Step 2.4: Inline Code Documentation

Generate language-appropriate inline documentation:

| Language | Doc Format | Style Guide |
|----------|-----------|-------------|
| Python | Google-style docstrings | PEP 257 |
| TypeScript/JavaScript | TSDoc / JSDoc | TypeDoc conventions |
| Go | GoDoc comments | Effective Go |
| Rust | Rustdoc (`///`) | Rust API Guidelines |
| Java | Javadoc | Oracle Javadoc Guide |

### Phase 3: Quality Assurance

#### Step 3.1: Documentation Completeness Check

- [ ] **What it is** — Clear project description
- [ ] **Why it exists** — Problem it solves
- [ ] **How to install** — Copy-paste-ready commands
- [ ] **How to use** — At least one minimal working example
- [ ] **API surface** — All public functions, classes documented
- [ ] **Configuration** — All env vars, config files documented
- [ ] **Error handling** — Common errors and resolutions
- [ ] **Contributing** — Dev environment setup and submission process

#### Step 3.2: Quality Standards

| Standard | Check |
|----------|-------|
| **Accuracy** | Every code example works with the described API |
| **Completeness** | No public API surface left undocumented |
| **Consistency** | Same formatting and structure throughout |
| **Freshness** | Documentation matches current code |
| **Accessibility** | No jargon without explanation |

#### Step 3.3: Cross-reference Validation

- All mentioned file paths exist in the project
- All referenced functions and classes exist in the code
- All code examples use correct function signatures
- Version numbers match the project's actual version

## Documentation Style Guide

1. **Lead with the "why"** — Before explaining how, explain why
2. **Progressive disclosure** — Start simple, add complexity gradually
3. **Show, don't tell** — Prefer code examples over lengthy explanations
4. **Active voice** — "The function returns X" not "X is returned by the function"
5. **Present tense** — "The server starts on port 8080"
6. **Second person** — "You can configure..." not "Users can configure..."

## Output Handling

- Save documentation files to `outputs/`
- For multi-file documentation, maintain the project directory structure
- Present generated files to the user using `present_artifacts`
- Offer to iterate on specific sections or adjust the level of detail

## Notes

- Always analyze the actual code before writing documentation — never guess at API signatures
- When existing documentation exists, preserve its structure unless the user asks for a rewrite
- For large codebases, prioritize documenting the public API surface and key abstractions first
- Documentation should be written in the same language as the project's existing docs; default to Chinese if none exist
- When generating changelogs, use the [Keep a Changelog](https://keepachangelog.com/) format
- This skill works well in combination with `deep-research` for documenting third-party integrations
