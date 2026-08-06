from handlers.command_handlers.add_manual_handler import _parse_options


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
