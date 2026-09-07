"""Image boundaries and untrusted classifier output, without external requests."""

import base64
import io
import json
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from models import Group, GuardEvent
from registries import engine
from services.moderation import ai, store
from services.moderation.schemas import AIConfig, AIVerdict, Policy


def photo(file_size=100):
    return [
        {
            "file_id": "private-file",
            "file_unique_id": "unique-photo",
            "width": 3200,
            "height": 1600,
            "file_size": file_size,
        }
    ]


async def test_downloaded_image_is_resized_and_encoded_locally(
    guard_bot, guard_message
):
    source = io.BytesIO()
    Image.new("RGBA", (3200, 1600), (255, 0, 0, 128)).save(source, "PNG")
    download = AsyncMock(return_value=bytearray(source.getvalue()))
    guard_bot.get_file.return_value.download_as_bytearray = download
    result = await ai.image_data(guard_bot, guard_message(text=None, photo=photo()))
    assert result.startswith("data:image/jpeg;base64,")
    with Image.open(io.BytesIO(base64.b64decode(result.split(",", 1)[1]))) as image:
        assert image.size == (1536, 768)
        assert image.mode == "RGB"
    guard_bot.get_file.assert_awaited_once_with("private-file")
    download.assert_awaited_once_with()


@pytest.mark.parametrize(
    "failure", ["declared_size", "downloaded_size", "invalid_image"]
)
async def test_image_rejects_oversized_or_invalid_downloads(
    failure, guard_bot, guard_message
):
    limit = 10 * 1024 * 1024
    guard_bot.get_file.return_value.download_as_bytearray = AsyncMock(
        return_value=bytearray(limit + 1)
        if failure == "downloaded_size"
        else b"not an image"
    )
    message = guard_message(
        text=None, photo=photo(limit + 1 if failure == "declared_size" else 100)
    )
    with pytest.raises((ValueError, UnidentifiedImageError)):
        await ai.image_data(guard_bot, message)
    if failure == "declared_size":
        guard_bot.get_file.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    ["refusal", "invalid_json", "extra_action", "http_error", "oversized", "redirect"],
)
async def test_classifier_rejects_provider_failures(failure):
    redirected = []

    async def redirect_target(request):
        redirected.append(request.headers.get("Authorization"))
        return web.json_response({})

    async def respond(request):
        if failure == "http_error":
            return web.Response(status=429)
        if failure == "oversized":
            return web.Response(body=b" " * 128001)
        if failure == "redirect":
            raise web.HTTPTemporaryRedirect("/elsewhere")
        verdict = {"category": "spam", "confidence": 1, "reason": "spam"}
        if failure == "extra_action":
            verdict["action"] = "ban"
        message = {
            "content": "not json" if failure == "invalid_json" else json.dumps(verdict)
        }
        if failure == "refusal":
            message["refusal"] = "cannot classify"
        return web.json_response({"choices": [{"message": message}]})

    app = web.Application()
    app.router.add_post("/v1/chat/completions", respond)
    app.router.add_post("/elsewhere", redirect_target)
    async with TestServer(app) as server:
        with pytest.raises(ValueError):
            await ai.classify(
                AIConfig(
                    base_url=str(server.make_url("/v1")),
                    api_key="fake-test-key",
                    text_model="test",
                ),
                Policy(ai_spam=True),
                "spam",
            )
    assert redirected == []


async def test_text_request_truncates_evidence_and_filters_usage():
    seen = []

    async def respond(request):
        seen.append(await request.json())
        return web.json_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"category": "safe", "confidence": 1, "reason": "safe"}
                            )
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": -1,
                    "total_tokens": "6",
                    "other": 100,
                },
            }
        )

    app = web.Application()
    app.router.add_post("/chat/completions", respond)
    async with TestServer(app) as server:
        verdict, usage = await ai.classify(
            AIConfig(
                base_url=str(server.make_url("/")),
                text_model="text-only",
                vision_model="vision",
            ),
            Policy(ai_spam=True),
            "x" * 20000,
        )
    assert verdict.category == "safe"
    assert usage == {"prompt_tokens": 5}
    assert seen[0]["model"] == "text-only"
    content = seen[0]["messages"][1]["content"]
    assert len(content) == 1
    assert len(json.loads(content[0]["text"])["message"]) == 16000


@pytest.mark.parametrize("change", ["policy", "admin", "exemption", "grading"])
async def test_inflight_verdict_rechecks_current_authority_and_policy(
    change, guard_group, guard_bot, guard_ai_job, monkeypatch
):
    job = await guard_ai_job()

    async def classify(*args):
        if change == "policy":
            await store.save_policy(guard_group, {"ai_spam": False})
        elif change == "admin":
            guard_bot.admin_ids.add(2)
        elif change == "exemption":
            await store.put_record(guard_group, "exempt", "2", {})
        else:
            async with engine.new_session() as session:
                group = await session.get(Group, guard_group)
                group.sanity_limit = 6
                await session.commit()
        return AIVerdict(category="spam", confidence=1, reason="spam"), {
            "total_tokens": 17
        }

    monkeypatch.setattr(ai, "classify", classify)
    assert await ai.process(guard_bot, job) == "stale"
    guard_bot.delete_message.assert_not_awaited()
    assert await store.warnings(guard_group, 2) == []
    async with engine.new_session() as session:
        event = await session.scalar(
            select(GuardEvent).where(GuardEvent.action == "ai")
        )
        assert event.status == "stale"
        assert event.data["usage"]["total_tokens"] == 17


@pytest.mark.parametrize("confidence,decision", [(0.8, "review"), (0.99, "punish")])
async def test_ai_result_is_persisted_and_not_repeated(
    confidence, decision, guard_group, guard_bot, guard_ai_job, monkeypatch
):
    job = await guard_ai_job()
    classifier = AsyncMock(
        return_value=(
            AIVerdict(
                category="spam", confidence=confidence, reason="scam", evidence="claim"
            ),
            {"total_tokens": 12},
        )
    )
    monkeypatch.setattr(ai, "classify", classifier)
    assert await ai.process(guard_bot, job) == decision
    assert await ai.process(guard_bot, job) == "duplicate"
    classifier.assert_awaited_once()
    if decision == "review":
        guard_bot.delete_message.assert_not_awaited()
        review = (await store.records(guard_group, "review"))[0]["data"]
        assert review["state"] == "pending"
        assert review["confidence"] == confidence
        assert review["version"] == job["data"]["version"]
    else:
        guard_bot.delete_message.assert_awaited_once_with(guard_group, 10)
        assert len(await store.warnings(guard_group, 2)) == 1
    async with engine.new_session() as session:
        event = await session.scalar(
            select(GuardEvent).where(GuardEvent.action == "ai")
        )
        assert event.status == "success"
        assert event.data["decision"] == decision
        assert event.data["usage"] == {"total_tokens": 12}
        if decision == "punish":
            assert [r["status"] for r in event.data["results"]] == [
                "success",
                "success",
            ]


async def test_failed_call_consumes_budget_but_never_warns(
    guard_group, guard_bot, guard_ai_job, monkeypatch
):
    first = await guard_ai_job(policy={"ai_daily_limit": 1})
    classifier = AsyncMock(side_effect=TimeoutError("private provider detail"))
    monkeypatch.setattr(ai, "classify", classifier)
    assert await ai.process(guard_bot, first) == "failed"
    second = await guard_ai_job(policy={"ai_daily_limit": 1}, message_id=11)
    assert await ai.process(guard_bot, second) == "budget_exhausted"
    classifier.assert_awaited_once()
    guard_bot.delete_message.assert_not_awaited()
    assert await store.warnings(guard_group, 2) == []
    async with engine.new_session() as session:
        event = await session.scalar(
            select(GuardEvent).where(GuardEvent.action == "ai")
        )
        assert event.status == "failed"
        assert event.data == {"error": "TimeoutError"}


async def test_image_document_uses_caption_and_known_permitted_grade(
    guard_bot, guard_ai_job, monkeypatch
):
    job = await guard_ai_job(
        policy={"ai_spam": False, "ai_images": True},
        text=None,
        caption="normal art",
        document={
            "file_id": "known-image",
            "file_unique_id": "known",
            "mime_type": "image/png",
        },
    )
    image = "data:image/jpeg;base64,dGVzdA=="
    downloader = AsyncMock(return_value=image)
    monkeypatch.setattr(ai, "image_data", downloader)
    monkeypatch.setattr(
        ai,
        "known_image_grade",
        AsyncMock(return_value={"sanity_level": 5, "r18g": False}),
    )
    classifier = AsyncMock(
        return_value=(
            AIVerdict(
                category="image",
                confidence=1,
                reason="adult",
                sanity_level=6,
                r18g=True,
            ),
            {},
        )
    )
    monkeypatch.setattr(ai, "classify", classifier)
    assert await ai.process(guard_bot, job) == "allow"
    downloader.assert_awaited_once()
    assert classifier.call_args.args[2:4] == ("normal art", image)
    guard_bot.delete_message.assert_not_awaited()
