---
name: video-generation
description: "当用户要求生成、创建或想象视频时使用。支持结构化提示词和参考图片引导生成。"
---

# Video Generation Skill

## Overview

This skill generates high-quality videos using structured prompts and a Python script. The workflow includes creating JSON-formatted prompts and executing video generation with optional reference image.

## Core Capabilities

- Create structured JSON prompts for AIGC video generation
- Support reference image as guidance or the first/last frame of the video
- Generate videos through automated Python script execution

## Workflow

### Step 1: Understand Requirements

When a user requests video generation, identify:

- Subject/content: What should be in the video
- Style preferences: Art style, mood, color palette
- Technical specs: Aspect ratio, composition, lighting
- Reference image: Any image to guide generation

### Step 2: Create Structured Prompt

Generate a structured JSON file in `workspace/` with naming pattern: `{descriptive-name}.json`

### Step 3: Create Reference Image (Optional when image-generation skill is available)

Generate reference image for the video generation.

- If only 1 image is provided, use it as the guided frame of the video

### Step 4: Execute Generation

Call the Python script:
```bash
python /home/gem/skills/video-generation/scripts/generate.py \
  --prompt-file workspace/prompt-file.json \
  --reference-images /path/to/ref1.jpg \
  --output-file outputs/generated-video.mp4 \
  --aspect-ratio 16:9
```

Parameters:

- `--prompt-file`: Absolute path to JSON prompt file (required)
- `--reference-images`: Absolute paths to reference image (optional)
- `--output-file`: Absolute path to output video file (required)
- `--aspect-ratio`: Aspect ratio of the generated video (optional, default: 16:9)

> Do NOT read the python file, instead just call it with the parameters.

## Video Generation Example

User request: "Generate a short video clip depicting a sunset over the ocean"

Step 1: Create a JSON prompt file with the following content:

```json
{
  "title": "Ocean Sunset",
  "background": {
    "description": "Golden hour sunset over a calm ocean. Warm orange and purple hues reflect on gentle waves.",
    "era": "contemporary",
    "location": "open ocean horizon"
  },
  "camera": {
    "type": "Wide establishing shot",
    "movement": "Slow push-in",
    "angle": "Eye level, horizon centered",
    "focus": "Sharp horizon, soft sky gradient"
  },
  "audio": [
    {
      "type": "Gentle ocean waves",
      "volume": 0.7
    },
    {
      "type": "Soft ambient pad music",
      "volume": 0.3
    }
  ]
}
```

Step 2: Use the image-generation skill to generate a reference image (optional)

Step 3: Use the generate.py script to generate the video
```bash
python /home/gem/skills/video-generation/scripts/generate.py \
  --prompt-file workspace/ocean-sunset.json \
  --output-file outputs/ocean-sunset.mp4 \
  --aspect-ratio 16:9
```

> Do NOT read the python file, just call it with the parameters.

## Output Handling

After generation:

- Videos are saved in `outputs/`
- Share generated videos (come first) with user as well as generated image if applicable, using `present_artifacts` tool
- Provide brief description of the generation result
- Offer to iterate if adjustments needed

## Notes

- Always use English for prompts regardless of user's language
- JSON format ensures structured, parsable prompts
- Reference images enhance generation quality significantly
- Iterative refinement is normal for optimal results

## Providers (Gemini / MiniMax / Volcengine)

Auto-selected by environment variables (CLI unchanged):

- `GEMINI_API_KEY` set → Gemini Veo (default, unchanged).
- Only `MINIMAX_API_KEY` set → MiniMax video (`/v1/video_generation`, async 3-step poll/download).
- Only `ARK_API_KEY` set → Volcengine 方舟（C-Dance/即梦）。
- Force with `VIDEO_GENERATION_PROVIDER=gemini|minimax|volcengine`.

MiniMax overrides: `MINIMAX_API_HOST` (default `https://api.minimaxi.com`),
`MINIMAX_VIDEO_MODEL` (default `MiniMax-Hailuo-2.3`). The first reference image is used
as MiniMax `first_frame_image`. MiniMax ignores `--aspect-ratio` (it uses resolution/duration).

Volcengine overrides: `ARK_BASE_URL` (default `https://ark.cn-beijing.volces.com/api/v3`),
`VOLC_VIDEO_MODEL` (default `doubao-seaweed-t2v-pro-0801`).
