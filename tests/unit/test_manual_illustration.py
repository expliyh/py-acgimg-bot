from io import BytesIO

import pytest
from PIL import Image

from handlers.command_handlers.add_manual_handler import _parse_options
from services.manual_illustration_importer import import_manual_illustration


def test_parse_manual_image_command_options():
    title, options = _parse_options([
        "测试图片", "author=画师", "source=https://example.com/work", "ai=yes", "r18=是"
    ])
    assert title == "测试图片"
    assert options["author_name"] == "画师"
    assert options["source_url"] == "https://example.com/work"
    assert options["is_ai"] is True
    assert options["is_r18"] is True
    assert options["author_url"] is None


@pytest.mark.parametrize("data", [b"not an image", b"\x89PNG\r\n\x1a\ntruncated"])
async def test_manual_import_rejects_malformed_image_contents(data):
    with pytest.raises(ValueError, match="损坏或格式无效"):
        await import_manual_illustration(data, filename="image.png", title="test")


async def test_manual_import_rejects_unsupported_image_contents():
    data = BytesIO()
    Image.new("RGB", (1, 1)).save(data, format="BMP")

    with pytest.raises(ValueError, match="仅支持"):
        await import_manual_illustration(
            data.getvalue(), filename="image.jpg", title="test"
        )
