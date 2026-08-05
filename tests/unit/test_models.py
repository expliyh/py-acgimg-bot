"""Unit tests for illustration model parsing."""

import pytest

from models.illustrations import build_illust_from_api_dict


def _single_page_dict(**overrides) -> dict:
    data = {
        "id": "100",
        "title": "Single Page",
        "user": {"id": "200", "name": "Artist"},
        "page_count": 1,
        "sanity_level": 3,
        "x_restrict": 0,
        "tags": [{"name": "tag1"}, {"name": "tag2"}],
        "caption": "A caption",
        "illust_ai_type": 0,
        "image_urls": {"square_medium": "https://i.pximg.net/c/250x250/img-master/100_s.jpg"},
        "meta_single_page": {"original_image_url": "https://i.pximg.net/img-original/100_p0.jpg"},
    }
    data.update(overrides)
    return data


def _multi_page_dict() -> dict:
    return {
        "id": "101",
        "title": "Multi Page",
        "user": {"id": "200", "name": "Artist"},
        "page_count": 2,
        "sanity_level": 3,
        "x_restrict": 1,
        "tags": [{"name": "a"}],
        "caption": None,
        "illust_ai_type": 2,
        "meta_pages": [
            {
                "image_urls": {
                    "square_medium": "https://i.pximg.net/c/250x250/img-master/101_p0_s.jpg",
                    "original": "https://i.pximg.net/img-original/101_p0.jpg",
                }
            },
            {
                "image_urls": {
                    "square_medium": "https://i.pximg.net/c/250x250/img-master/101_p1_s.jpg",
                    "original": "https://i.pximg.net/img-original/101_p1.jpg",
                }
            },
        ],
    }


class TestBuildIllustFromApiDict:
    def test_single_page(self):
        illust = build_illust_from_api_dict(_single_page_dict())
        assert illust.id == "100"
        assert illust.title == "Single Page"
        assert illust.author_id == "200"
        assert illust.author_name == "Artist"
        assert illust.page_count == 1
        assert illust.sanity_level == 3
        assert illust.x_restrict == 0
        assert illust.tags == ["tag1", "tag2"]
        assert illust.caption == "A caption"
        assert illust.is_ai is False
        assert illust.origin_urls == ["https://i.pximg.net/img-original/100_p0.jpg"]
        assert illust.file_ext == [".jpg"]
        assert illust.file_urls == [None]
        assert illust.compressed_file_ids == [None]
        assert illust.original_file_ids == [None]

    def test_multi_page(self):
        illust = build_illust_from_api_dict(_multi_page_dict())
        assert illust.id == "101"
        assert illust.page_count == 2
        assert illust.is_ai is True
        assert illust.origin_urls == [
            "https://i.pximg.net/img-original/101_p0.jpg",
            "https://i.pximg.net/img-original/101_p1.jpg",
        ]
        assert illust.file_ext == [".jpg", ".jpg"]

    def test_ai_flag_mapping(self):
        # illust_ai_type 2 也表示 AI 作品
        illust = build_illust_from_api_dict(_single_page_dict(illust_ai_type=2))
        assert illust.is_ai is True

    def test_missing_original_url_raises(self):
        with pytest.raises(RuntimeError):
            build_illust_from_api_dict(_single_page_dict(meta_single_page={}))

    def test_page_count_mismatch_raises(self):
        data = _single_page_dict(page_count=2)
        with pytest.raises(RuntimeError):
            build_illust_from_api_dict(data)
