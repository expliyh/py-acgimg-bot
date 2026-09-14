from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from models import Illustration
from services.image_push import _caption, send_illustration_photo


def _illustration(*, source_type: str = "pixiv") -> Illustration:
    return Illustration(
        id="123456",
        title="测试插画",
        author_id="42",
        author_name="作者",
        page_count=2,
        sanity_level=5,
        r18g=False,
        x_restrict=0,
        tags=[],
        caption=None,
        is_ai=False,
        file_urls=["https://storage.example/123456-0.jpg", "https://storage.example/123456-1.jpg"],
        compressed_file_ids=["cached-photo-0", "cached-photo-1"],
        original_file_ids=[None, None],
        origin_urls=["https://i.pximg.net/123456_p0.jpg", "https://i.pximg.net/123456_p1.jpg"],
        file_ext=[".jpg", ".jpg"],
        source_type=source_type,
    )


def test_default_caption_includes_pixiv_pid_and_page_link():
    caption = _caption(_illustration(), 1)

    assert "PID: 123456" in caption
    assert "图片链接: https://www.pixiv.net/artworks/123456" in caption


def test_manual_caption_does_not_include_pixiv_metadata():
    caption = _caption(
        _illustration(source_type="manual"),
        0,
    )

    assert "PID:" not in caption
    assert "图片链接:" not in caption


@pytest.mark.asyncio
async def test_custom_caption_is_augmented_before_photo_is_sent():
    bot = SimpleNamespace(send_photo=AsyncMock(return_value=SimpleNamespace(photo=[])))

    await send_illustration_photo(bot, 99, _illustration(), 1, caption="自定义说明")

    sent_kwargs = bot.send_photo.await_args.kwargs
    assert sent_kwargs["caption"] == (
        "自定义说明\nPID: 123456\n"
        "图片链接: https://www.pixiv.net/artworks/123456"
    )
