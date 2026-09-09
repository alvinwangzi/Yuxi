"""登录验证码服务。

用户连续输错密码达到阈值后，要求输入数学运算验证码，防止暴力破解。
验证码答案存入 Redis，带 TTL 自动过期。
"""

from __future__ import annotations

import io
import random
import uuid

from PIL import Image, ImageDraw, ImageFont

from yuxi.storage.redis import get_async_redis_client
from yuxi.repositories.user_repository import UserRepository

# 验证码触发阈值：连续失败次数达到此值后要求输入验证码
CAPTCHA_THRESHOLD = 3

# 验证码有效期（秒）
CAPTCHA_TTL = 300

# 验证码图片尺寸
CAPTCHA_IMAGE_WIDTH = 260
CAPTCHA_IMAGE_HEIGHT = 80

_CAPTCHA_KEY_PREFIX = "yuxi:captcha:"


def _captcha_key(captcha_id: str) -> str:
    return f"{_CAPTCHA_KEY_PREFIX}{captcha_id}"


def generate_captcha_challenge() -> tuple[str, int]:
    """生成数学运算验证码。

    返回 (表达式文本, 正确答案)。
    """
    ops = ["+", "-"]
    op = random.choice(ops)
    if op == "+":
        a = random.randint(1, 30)
        b = random.randint(1, 30)
        answer = a + b
    else:
        a = random.randint(10, 50)
        b = random.randint(1, a)
        answer = a - b
    return f"{a} {op} {b} = ?", answer


def _generate_captcha_image(expression: str) -> bytes:
    """将验证码表达式渲染为 PNG 图片字节。"""
    width = CAPTCHA_IMAGE_WIDTH
    height = CAPTCHA_IMAGE_HEIGHT
    image = Image.new("RGB", (width, height), _light_background())
    draw = ImageDraw.Draw(image)

    # 干扰线（浅色，不遮挡文字）
    for _ in range(3):
        draw.line(
            [
                (random.randint(0, width), random.randint(0, height)),
                (random.randint(0, width), random.randint(0, height)),
            ],
            fill=_random_color(190, 230),
            width=1,
        )

    # 干扰点（浅色）
    for _ in range(20):
        draw.point(
            (random.randint(0, width), random.randint(0, height)),
            fill=_random_color(170, 220),
        )

    # 逐字符绘制表达式
    font = _load_font(38)
    x = 16
    for char in expression:
        y = random.randint(12, 28)
        draw.text((x, y), char, fill=_random_color(10, 80), font=font)
        x += random.randint(20, 28)

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _light_background() -> tuple[int, int, int]:
    return (random.randint(235, 250), random.randint(235, 250), random.randint(235, 250))


def _random_color(low: int, high: int) -> tuple[int, int, int]:
    return (random.randint(low, high), random.randint(low, high), random.randint(low, high))


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """尝试加载 TrueType 字体，失败则使用默认字体。"""
    candidates = [
        # Docker 容器（Debian/Ubuntu 基础镜像）
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        # Windows 本地开发
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


async def store_captcha_answer(captcha_id: str, answer: int) -> None:
    """将验证码答案存入 Redis，带 TTL。"""
    redis = await get_async_redis_client()
    await redis.set(_captcha_key(captcha_id), str(answer), ex=CAPTCHA_TTL)


async def generate_captcha() -> tuple[str, bytes]:
    """生成完整验证码：创建挑战、渲染图片、存储答案。

    返回 (captcha_id, 图片 PNG 字节)。
    """
    captcha_id = uuid.uuid4().hex
    expression, answer = generate_captcha_challenge()
    image_bytes = _generate_captcha_image(expression)
    await store_captcha_answer(captcha_id, answer)
    return captcha_id, image_bytes


async def get_captcha_answer(captcha_id: str) -> str | None:
    """从 Redis 获取验证码答案。"""
    redis = await get_async_redis_client()
    return await redis.get(_captcha_key(captcha_id))


async def delete_captcha(captcha_id: str) -> None:
    """删除已使用的验证码。"""
    if not captcha_id:
        return
    redis = await get_async_redis_client()
    await redis.delete(_captcha_key(captcha_id))


async def check_captcha_required(db, login_identifier: str) -> bool:
    """检查指定登录标识是否需要验证码（失败次数 >= 阈值）。"""
    user_repository = UserRepository(db)
    user = await user_repository.get_by_login_identifier(login_identifier)
    if not user:
        return False
    return user.login_failed_count >= CAPTCHA_THRESHOLD
