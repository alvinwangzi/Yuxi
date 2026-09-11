---
name: podcast-generation
description: "当用户要求生成、创建或制作播客时使用。将文字内容转换为双主持人对话式播客音频，支持中英文。"
---

# Podcast Generation Skill

## Overview

This skill generates high-quality podcast audio from text content. The workflow includes creating a structured JSON script (conversational dialogue) and executing audio generation through text-to-speech synthesis.

## Core Capabilities

- Convert any text content (articles, reports, documentation) into podcast scripts
- Generate natural two-host conversational dialogue (male and female hosts)
- Synthesize speech audio using text-to-speech
- Mix audio chunks into a final podcast MP3 file
- Support both English and Chinese content

## Workflow

### Step 1: Understand Requirements

When a user requests podcast generation, identify:

- Source content: The text/article/report to convert into a podcast
- Language: English or Chinese (based on content)
- Output location: Where to save the generated podcast

### Step 2: Create Structured Script JSON

Generate a structured JSON script file in `workspace/` with naming pattern: `{descriptive-name}-script.json`

The JSON structure:
```json
{
  "locale": "en",
  "lines": [
    {"speaker": "male", "paragraph": "dialogue text"},
    {"speaker": "female", "paragraph": "dialogue text"}
  ]
}
```

### Step 3: Execute Generation

Call the Python script:
```bash
python /home/gem/skills/podcast-generation/scripts/generate.py \
  --script-file workspace/script-file.json \
  --output-file outputs/generated-podcast.mp3 \
  --transcript-file outputs/generated-podcast-transcript.md
```

Parameters:

- `--script-file`: Absolute path to JSON script file (required)
- `--output-file`: Absolute path to output MP3 file (required)
- `--transcript-file`: Absolute path to output transcript markdown file (optional, but recommended)

> - Execute the script in one complete call. Do NOT split the workflow into separate steps.
> - The script handles all TTS API calls and audio generation internally.
> - Do NOT read the Python file, just call it with the parameters.
> - Always include `--transcript-file` to generate a readable transcript for the user.
> - The TTS provider and its concurrency are selected automatically from environment variables — you do not choose or tune them.

## Script JSON Format

The script JSON file must follow this structure:

```json
{
  "title": "The History of Artificial Intelligence",
  "locale": "en",
  "lines": [
    {"speaker": "male", "paragraph": "Welcome back to another episode."},
    {"speaker": "female", "paragraph": "Hey everyone! Today we have an exciting topic to discuss."},
    {"speaker": "male", "paragraph": "That's right! We're going to talk about..."}
  ]
}
```

Fields:
- `title`: Title of the podcast episode (optional, used as heading in transcript)
- `locale`: Language code - "en" for English or "zh" for Chinese
- `lines`: Array of dialogue lines
  - `speaker`: Either "male" or "female"
  - `paragraph`: The dialogue text for this speaker

## Script Writing Guidelines

When creating the script JSON, follow these guidelines:

### Format Requirements
- Only two hosts: male and female, alternating naturally
- Target runtime: approximately 10 minutes of dialogue (around 40-60 lines)
- Start with a natural greeting

### Tone & Style
- Natural, conversational dialogue - like two friends chatting
- Use casual expressions and conversational transitions
- Avoid overly formal language or academic tone
- Include reactions, follow-up questions, and natural interjections

### Content Guidelines
- Frequent back-and-forth between hosts
- Keep sentences short and easy to follow when spoken
- Plain text only - no markdown formatting in the output
- Translate technical concepts into accessible language
- No mathematical formulas, code, or complex notation
- Make content engaging and accessible for audio-only listeners
- Exclude meta information like dates, author names, or document structure

## Specific Templates

Read the following template file only when matching the user request.

- [Tech Explainer](templates/tech-explainer.md) - For converting technical documentation and tutorials

## Output Format

- Two hosts: one male, one female
- Natural conversational dialogue
- Target duration: approximately 10 minutes
- Alternating speakers for engaging flow

## Output Handling

After generation:

- Podcasts and transcripts are saved in `outputs/`
- Share both the podcast MP3 and transcript MD with user using `present_artifacts` tool
- Provide brief description of the generation result (topic, duration, hosts)
- Offer to regenerate if adjustments needed

## Requirements

The following environment variables must be set:
- For Volcengine: `VOLCENGINE_TTS_APPID` and `VOLCENGINE_TTS_ACCESS_TOKEN`
- For MiniMax: `MINIMAX_API_KEY`
- `VOLCENGINE_TTS_CLUSTER`: Volcengine TTS cluster (optional, defaults to "volcano_tts")
- `VOLCENGINE_TTS_VOICE_TYPE_MALE`: Volcengine male voice type (optional, defaults to `zh_male_yangguangqingnian_moon_bigtts`)
- `VOLCENGINE_TTS_VOICE_TYPE_FEMALE`: Volcengine female voice type (optional, defaults to `zh_female_sajiaonvyou_moon_bigtts`)

Voice type overrides are trimmed; unset or blank values use the listed defaults.

## Notes

- **Always execute the full pipeline in one call** - no need to test individual steps or worry about timeouts
- The script JSON should match the content language (en or zh)
- Technical content should be simplified for audio accessibility in the script
- Complex notations (formulas, code) should be translated to plain language in the script
- Long content may result in longer podcasts

## Providers (Volcengine / MiniMax)

Auto-selected by environment variables:

- `VOLCENGINE_TTS_APPID` + `VOLCENGINE_TTS_ACCESS_TOKEN` set → Volcengine TTS (default).
- Only `MINIMAX_API_KEY` set → MiniMax TTS (`/v1/t2a_v2`).
- Force with `PODCAST_GENERATION_PROVIDER=volcengine|minimax`.

MiniMax overrides: `MINIMAX_API_HOST` (default `https://api.minimaxi.com`),
`MINIMAX_TTS_MODEL` (default `speech-2.6-hd`), `MINIMAX_TTS_VOICE_MALE`
(default `male-qn-qingse`), `MINIMAX_TTS_VOICE_FEMALE` (default `female-tianmei`).

Concurrency is owned by each provider internally — MiniMax runs single-threaded
to reduce rate-limit failures, Volcengine uses 4 workers. There is no
caller-facing concurrency knob; transient rate limits are handled by automatic
retry with backoff.
