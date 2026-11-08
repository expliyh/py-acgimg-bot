"""Illustration cards must survive titles, tags, and names with markup characters."""

from models.illustrations import Illustration, build_illust_from_api_dict
from messase_generator.illustration import ILLUSTRATION_PARSE_MODE, render_illustration_html
from telegram.constants import ParseMode

from tests.unit.telegram_markup import (
    assert_valid_telegram_html,
    hrefs,
    legacy_markdown_unclosed_offset,
    visible_text,
)

_SPECIAL_TITLE = "hello_world*[`<b>&]"
_SPECIAL_AUTHOR = "author_*[`]<&>"
_SPECIAL_TAGS = ["tag_*[`]", "a<b>&", "under_score"]
_SPECIAL_CAPTION = "cap_*[`]<b>no</b> & more<br />line_2"


def _illustration(**overrides) -> Illustration:
    values = dict(
        id="100",
        title=_SPECIAL_TITLE,
        author_id="200",
        author_name=_SPECIAL_AUTHOR,
        page_count=1,
        sanity_level=2,
        r18g=False,
        x_restrict=0,
        tags=list(_SPECIAL_TAGS),
        caption=_SPECIAL_CAPTION,
        is_ai=False,
        file_urls=[None],
        compressed_file_ids=[None],
        original_file_ids=[None],
        origin_urls=["https://i.pximg.net/img-original/img/100_p0.jpg"],
        file_ext=[".jpg"],
        source_type="pixiv",
        source_url="https://example.com/art?b=1&c=2",
    )
    values.update(overrides)
    return Illustration(**values)


def test_legacy_markdown_reports_unclosed_entity_at_byte_35():
    """The production failure: reply_markdown + an unescaped underscore.

    ``**title**`` does not bold the title in legacy Markdown. The two stars
    cancel, and a later ``_`` with no partner is reported at its byte offset.
    A 33-byte title prefix puts that ``_`` at offset 35, matching the logged
    ``Can't parse entities: can't find end of the entity starting at byte offset 35``.
    """

    title = ("A" * 33) + "_"
    legacy = f"**{title}**\n\n作者: 名字\n\n描述: 普通说明"
    assert legacy_markdown_unclosed_offset(legacy) == 35
    assert legacy_markdown_unclosed_offset("**hello_world**") is not None
    assert legacy_markdown_unclosed_offset("描述: hello_world") is not None
    # Underscores inside a finished link, including the URL, are literal.
    assert legacy_markdown_unclosed_offset(
        "[原图](https://i.pximg.net/img-original/img/100_p0.jpg)"
    ) is None
    assert legacy_markdown_unclosed_offset("[author_name](https://www.pixiv.net/users/1)") is None


def test_special_characters_render_as_valid_html():
    illust = _illustration()
    text = illust.get_markdown()

    assert text == render_illustration_html(illust)
    assert ILLUSTRATION_PARSE_MODE == ParseMode.HTML
    assert_valid_telegram_html(text)
    assert text.lower().count("<b>") == 1

    visible = visible_text(text)
    assert _SPECIAL_TITLE in visible
    assert _SPECIAL_AUTHOR in visible
    for tag in _SPECIAL_TAGS:
        assert tag in visible
    assert "cap_*[`]<b>no</b> & more" in visible
    assert "line_2" in visible
    assert "AI: 否" in visible

    links = hrefs(text)
    assert "https://i.pximg.net/img-original/img/100_p0.jpg" in links
    assert "https://www.pixiv.net/users/200" in links
    assert "https://example.com/art?b=1&c=2" in links
    assert all(not link.lower().startswith("javascript:") for link in links)
    assert "None" not in links


def test_multi_page_origins_and_unsafe_source_url():
    illust = _illustration(
        page_count=2,
        file_urls=[None, None],
        origin_urls=[
            "https://i.pximg.net/img-original/img/101_p0.jpg",
            "https://i.pximg.net/img-original/img/101_p1.jpg",
        ],
        file_ext=[".jpg", ".jpg"],
        source_url="javascript:alert(1)",
        author_url="not a url",
        is_ai=True,
        caption=None,
        tags=[],
    )
    text = illust.get_markdown()
    assert_valid_telegram_html(text)
    links = hrefs(text)
    assert links == [
        "https://i.pximg.net/img-original/img/101_p0.jpg",
        "https://i.pximg.net/img-original/img/101_p1.jpg",
    ]
    visible = visible_text(text)
    assert "原图: 1, 2" in visible
    assert "描述: 无" in visible
    assert "标签: 无" in visible
    assert "AI: 是" in visible
    assert "javascript:alert(1)" not in text
    assert _SPECIAL_AUTHOR in visible


def test_missing_source_type_still_links_the_pixiv_author():
    illust = _illustration(source_type=None, author_url=None)
    text = illust.get_markdown()
    assert_valid_telegram_html(text)
    assert "https://www.pixiv.net/users/200" in hrefs(text)


def test_api_payload_with_special_characters_renders_original_url():
    illust = build_illust_from_api_dict(
        {
            "id": "100",
            "title": _SPECIAL_TITLE,
            "user": {"id": "200", "name": _SPECIAL_AUTHOR},
            "page_count": 1,
            "sanity_level": 2,
            "x_restrict": 0,
            "tags": [{"name": name} for name in _SPECIAL_TAGS],
            "caption": _SPECIAL_CAPTION,
            "illust_ai_type": 0,
            "meta_single_page": {
                "original_image_url": "https://i.pximg.net/img-original/img/100_p0.jpg"
            },
        }
    )
    text = illust.get_markdown()
    assert_valid_telegram_html(text)
    assert illust.file_urls == [None]
    assert "https://i.pximg.net/img-original/img/100_p0.jpg" in hrefs(text)
    assert _SPECIAL_TITLE in visible_text(text)
    assert "tag_*[`]" in visible_text(text)


def test_file_url_is_used_when_the_original_url_is_missing():
    illust = _illustration(
        origin_urls=[None],
        file_urls=["https://cdn.example.com/a_b.jpg"],
        source_url=None,
    )
    text = illust.get_markdown()
    assert_valid_telegram_html(text)
    assert "https://cdn.example.com/a_b.jpg" in hrefs(text)


def test_manual_illustration_does_not_invent_a_pixiv_author_link():
    illust = _illustration(source_type="manual", author_url=None, author_id="internal")
    text = illust.get_markdown()
    assert_valid_telegram_html(text)
    assert "pixiv.net/users" not in text
    assert _SPECIAL_AUTHOR in visible_text(text)


def test_oversized_caption_stays_within_the_telegram_limit():
    illust = _illustration(caption="<" * 8000 + "_tail")
    text = illust.get_markdown()
    assert_valid_telegram_html(text)
    assert _SPECIAL_TITLE in visible_text(text)
    assert "作者" in visible_text(text)
