"""Unit tests for image resource resolution helpers."""

import pytest

from models import Illustration
from services.image_service.get_image import (
    _resolve_page_id,
    _resolve_link,
    _resolve_extension,
    _resolve_file_id,
)
from exps import BadRequestError


def make_illust(**overrides) -> Illustration:
    illust = Illustration(
        id="100",
        author_id="200",
        author_name="Artist",
        page_count=2,
        sanity_level=3,
        r18g=False,
        x_restrict=0,
        tags=[],
        caption=None,
        is_ai=False,
        file_urls=["https://cdn/0.jpg", "https://cdn/1.jpg"],
        compressed_file_ids=["photo0", None],
        original_file_ids=["doc0", "doc1"],
        origin_urls=["https://orig/0.jpg", "https://orig/1.jpg"],
        file_ext=[".jpg", ".png"],
    )
    for key, value in overrides.items():
        setattr(illust, key, value)
    return illust


class TestResolvePageId:
    def test_default_first_page(self):
        assert _resolve_page_id(make_illust(), None, allow_random=False) == 0

    def test_random_within_range(self):
        assert _resolve_page_id(make_illust(), None, allow_random=True) in (0, 1)

    def test_explicit_page(self):
        assert _resolve_page_id(make_illust(), 1, allow_random=False) == 1

    def test_out_of_range_raises_bad_request(self):
        with pytest.raises(BadRequestError):
            _resolve_page_id(make_illust(), 5, allow_random=False)

    def test_zero_page_count_raises(self):
        with pytest.raises(FileNotFoundError):
            _resolve_page_id(make_illust(page_count=0), None, allow_random=False)


class TestResolveLink:
    def test_picks_file_url(self):
        illust = make_illust()
        assert _resolve_link(illust, 1) == "https://cdn/1.jpg"

    def test_falls_back_to_origin_url(self):
        illust = make_illust(file_urls=[None, None])
        assert _resolve_link(illust, 0) == "https://orig/0.jpg"

    def test_missing_link_raises(self):
        illust = make_illust(file_urls=[], origin_urls=[])
        with pytest.raises(FileNotFoundError):
            _resolve_link(illust, 0)


class TestResolveExtension:
    def test_list_ext(self):
        assert _resolve_extension(make_illust(), 1, "https://x/1.png") == ".png"

    def test_infers_from_link(self):
        illust = make_illust(file_ext=None)
        assert _resolve_extension(illust, 0, "https://x/image.jpg") == ".jpg"

    def test_defaults_to_jpg(self):
        illust = make_illust(file_ext=None)
        assert _resolve_extension(illust, 0, "https://x/noext") == ".jpg"

    def test_normalizes_dot(self):
        illust = make_illust(file_ext="png")
        assert _resolve_extension(illust, 0, "https://x/1") == ".png"


class TestResolveFileId:
    def test_compressed_list(self):
        assert _resolve_file_id(make_illust(), 0, origin=False) == "photo0"

    def test_missing_entry_returns_none(self):
        assert _resolve_file_id(make_illust(), 1, origin=False) is None

    def test_original_list(self):
        assert _resolve_file_id(make_illust(), 0, origin=True) == "doc0"

    def test_string_container(self):
        illust = make_illust(compressed_file_ids="single-id")
        assert _resolve_file_id(illust, 0, origin=False) == "single-id"
