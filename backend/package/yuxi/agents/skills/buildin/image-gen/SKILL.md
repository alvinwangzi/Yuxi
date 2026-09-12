---
name: image-gen
description: "在 Agent 沙盒中生成图片并保存到 outputs。当用户要求生成图片、海报、插画、文生图时使用此技能。"
---

# 图片生成技能

当用户要求生成图片、海报、插画、文生图时，使用此技能组织图片生成流程。

## 第一步：需求采集

生成前必须收集以下关键信息。用户不一定一次性提供全部，根据已有信息判断缺失项，**一次性询问所有缺失的关键信息**，避免多轮追问。

### 必须明确的信息

| 维度 | 说明 | 示例 |
|------|------|------|
| **主体内容** | 画面核心元素 | "一只橘猫坐在窗台上看雨"、"产品白底图" |
| **用途场景** | 图片用在哪里 | 社交媒体头像、公众号封面、PPT 配图、手机壁纸、海报、印刷品 |

### 影响质量的关键信息（用户未提供时使用合理默认值）

| 维度 | 默认值 | 可选范围 |
|------|--------|----------|
| **画风风格** | 根据主体自动判断 | 写实摄影、日系动漫、扁平插画、油画水彩、3D 渲染、赛博朋克、中国风水墨、像素风… |
| **画面比例** | 1:1（方形） | 1:1 方图、16:9 横屏、9:16 竖屏、4:3、3:4、2:3 人像 |
| **画质等级** | 标准 | 标准（快速出图）、高清（细节更丰富） |
| **氛围色调** | 根据主体自动判断 | 明亮温暖、暗色调、冷色系、复古暖色、高对比… |
| **其它约束** | 无 | 特定颜色、排除元素、参考风格、文字叠加等 |

### 采集原则

- 用户说"帮我画个猫"→ 至少追问**用途场景**（决定比例和风格），其余可用默认值。
- 用户说"帮我做一张公众号封面"→ 比例已知（通常 2.35:1 或 16:9），追问**主体内容和风格**。
- 用户说"画一张赛博朋克风的城市夜景做壁纸"→ 主体、风格、用途齐备，直接生成，不要追问。
- 如果用户明确说"随便""你决定""快速出一张"，使用全部默认值直接生成。

## 第二步：模型选择

根据采集到的信息，从 `IMAGE_GEN_MODELS`（JSON 数组）中选择最合适的模型。

**可用模型环境变量**：
- `IMAGE_GEN_API_KEY` / `IMAGE_GEN_BASE_URL` / `IMAGE_GEN_MODEL`：默认模型
- `IMAGE_GEN_MODELS`：全部可用模型 JSON 数组，每项含 `model`、`base_url`、`api_key`（可选）、`display_name`（可选）

**选择策略**：

| 用户需求 | 选择逻辑 |
|----------|----------|
| 未指定质量要求 | 使用默认 `IMAGE_GEN_MODEL` |
| "高清""高质量""精细" | 从列表中选 `display_name` 或 `model` 含 `pro`/`max`/`hd`/`quality` 的模型 |
| "快速""草稿""先看看效果" | 选名称含 `lite`/`fast`/`turbo`/`draft` 的模型，或直接用默认 |
| 明确指定模型名 | 从列表中精确匹配 `model` 字段 |
| 只配了一个模型 | 直接用，无需选择 |

不同模型可能属于不同供应商（`base_url` 不同），切换时必须同时切换 `base_url` 和 `api_key`。

## 第三步：提示词构造

根据采集到的信息构造英文 prompt（大多数图片模型对英文 prompt 效果更好）。

**Prompt 构造公式**：
```
[主体描述], [风格], [氛围/光影], [画质修饰], [构图/镜头]
```

**各维度常用修饰词**：

| 维度 | 修饰词示例 |
|------|-----------|
| 风格 | photorealistic, anime style, flat illustration, oil painting, watercolor, 3D render, cyberpunk, Chinese ink painting |
| 画质 | high detail, 4K, 8K resolution, ultra HD, masterpiece, best quality |
| 光影 | soft lighting, golden hour, dramatic shadows, neon glow, natural light |
| 构图 | close-up, wide angle, bird's eye view, centered composition, rule of thirds |
| 氛围 | warm tones, cool palette, vintage mood, minimalist, vibrant colors |

**尺寸映射**（根据用户选择的比例传入 `size` 参数，如果 API 支持）：

| 比例 | 推荐 size |
|------|-----------|
| 1:1 | 1024x1024 |
| 16:9 | 1024x576 或 1920x1080 |
| 9:16 | 576x1024 或 1080x1920 |
| 4:3 | 1024x768 |
| 3:4 | 768x1024 |

如果 API 不支持 `size` 参数，在 prompt 中注明比例要求（如 "square format"、"widescreen landscape"）。

## 第四步：执行生成

使用可用的执行工具在沙盒中运行脚本：

```python
import json
import os
import requests
from pathlib import Path

# 读取模型配置
api_key = os.environ["IMAGE_GEN_API_KEY"]
base_url = os.environ["IMAGE_GEN_BASE_URL"].rstrip("/")
model = os.environ["IMAGE_GEN_MODEL"]

# 若需要切换模型，从 IMAGE_GEN_MODELS 中选取
available = json.loads(os.environ.get("IMAGE_GEN_MODELS", "[]"))
# chosen = next((m for m in available if m["model"] == "target-model"), None)
# if chosen:
#     model = chosen["model"]
#     base_url = chosen.get("base_url", base_url).rstrip("/")
#     api_key = chosen.get("api_key", api_key)

# 构造请求
prompt = "a cute orange cat sitting on the windowsill watching the rain, anime style, soft lighting, warm tones, high detail"

request_body = {
    "model": model,
    "prompt": prompt,
}

# 如果 API 支持 size 参数，取消下面的注释
# request_body["size"] = "1024x1024"

response = requests.post(
    f"{base_url}/images/generations",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json=request_body,
    timeout=120,
)
response.raise_for_status()

# 解析响应（兼容 URL 和 base64 两种返回格式）
result = response.json()
image_data = result["images"][0]
image_url = image_data.get("url")
b64_data = image_data.get("b64_json")

output_path = Path("outputs/generated-image.png")
output_path.parent.mkdir(parents=True, exist_ok=True)

if image_url:
    img_resp = requests.get(image_url, timeout=120)
    img_resp.raise_for_status()
    output_path.write_bytes(img_resp.content)
elif b64_data:
    import base64
    output_path.write_bytes(base64.b64decode(b64_data))
else:
    raise RuntimeError("API 返回中既无 url 也无 b64_json")

print(output_path.as_posix())
```

然后调用 `present_artifacts`，传入保存后的 outputs 虚拟路径，让前端展示图片产物。

## 第五步：交付

- 简要说明图片已生成，描述使用了什么模型和关键参数。
- 不要把外部临时 URL 当作最终结果展示给用户。
- 如果生成失败，明确告知错误原因（如 API 超时、模型不支持该尺寸等），并建议替代方案。

## 环境变量缺失时的处理

如果 `IMAGE_GEN_API_KEY` 或 `IMAGE_GEN_BASE_URL` 缺失，说明管理员尚未在模型供应商页面配置 image 类型模型。应明确提示用户需要先在管理后台配置图片生成模型，而不是猜测或使用硬编码的 API 地址。

## 关键约束

- 不要把外部生成接口返回的临时 URL 当作最终结果直接展示给用户。
- 不要调用后端 MinIO 上传工具；图片生成和下载都应在沙盒内完成。
- 如果 `IMAGE_GEN_API_KEY` 缺失，应明确提示用户需要在管理后台配置图片生成模型。
- 保存到 outputs 后必须调用 `present_artifacts`，否则前端不会自动展示生成图片。
- 大多数图片生成模型对英文 prompt 效果更好，构造 prompt 时默认使用英文。
