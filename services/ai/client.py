"""Bounded Chat Completions requests with a shared limit per provider."""

import asyncio
import json
import weakref
from contextlib import asynccontextmanager

import aiohttp

MAX_RESPONSE_BYTES = 128000
_limiters = weakref.WeakKeyDictionary()


class _ProviderLimiter:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.active = 0
        self.limit = 1

    async def acquire(self, limit):
        async with self.condition:
            self.limit = limit
            while self.active >= self.limit:
                await self.condition.wait()
            self.active += 1

    async def release(self):
        async with self.condition:
            self.active -= 1
            self.condition.notify_all()


@asynccontextmanager
async def provider_slot(config):
    catalogue = _limiters.setdefault(asyncio.get_running_loop(), {})
    limiter = catalogue.setdefault(config.provider_id, _ProviderLimiter())
    await limiter.acquire(config.concurrency)
    try:
        yield
    finally:
        await limiter.release()


def check_input_budget(messages, limit):
    """Apply a conservative local estimate without a provider-specific tokenizer.

    Count every UTF-8 byte of the full message JSON, including inline image data,
    plus chat framing. This deliberately overestimates typical text tokenization;
    provider token usage remains authoritative. Remote media and other modalities
    cannot be estimated locally, so bounded requests must not send them unchecked.
    """
    if limit is None:
        return
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    continue
                if part.get("type") == "image_url":
                    image = part.get("image_url")
                    url = image.get("url", "") if isinstance(image, dict) else ""
                    if url.startswith("data:image/") and ";base64," in url:
                        continue
                raise ValueError("设置输入上限时仅支持文本和内嵌图片，无法估算远程媒体或其他媒体的输入用量")
    estimated = len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    estimated += 16 * len(messages) + 3
    if estimated > limit:
        raise ValueError(f"请求输入估算为 {estimated} Token，超过模型输入上限 {limit}；未发送请求")


async def complete(config, messages):
    if "text" not in config.output_types:
        raise ValueError("审核模型必须支持文本输出")
    for message in messages:
        content = message.get("content")
        parts = content if isinstance(content, list) else [{"type": "text"}]
        for part in parts:
            modality = {"text": "text", "image_url": "image", "input_audio": "audio",
                        "video_url": "video", "file": "file"}.get(part.get("type"))
            if modality is None or modality not in config.input_types:
                raise ValueError("模型不支持请求中的输入类型")
    check_input_budget(messages, config.max_input_tokens)
    payload = {"model": config.model, "messages": messages}
    if config.max_output_tokens is not None:
        payload["max_tokens"] = config.max_output_tokens
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    async with provider_slot(config):
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=config.timeout)) as session,
            session.post(
                config.base_url + "/chat/completions",
                json=payload,
                headers=headers, allow_redirects=False,
            ) as response,
        ):
            if response.status != 200:
                raise ValueError(f"模型返回 HTTP {response.status}")
            try:
                raw = await response.content.readexactly(MAX_RESPONSE_BYTES + 1)
            except asyncio.IncompleteReadError as exc:
                raw = exc.partial
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("模型响应过大")
            payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("模型响应必须为对象")
    value = payload["choices"][0]["message"]
    if not isinstance(value, dict) or value.get("refusal"):
        raise ValueError("模型消息无效或拒绝审核")
    usage = payload.get("usage", {})
    if usage is None:
        usage = {}
    if not isinstance(usage, dict):
        raise ValueError("模型用量必须为对象")
    usage = {key: value for key, value in usage.items()
             if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
             and isinstance(value, int) and value >= 0}
    return value["content"], usage
