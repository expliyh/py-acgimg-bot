"""Missing Pixiv works are reported as not found instead of a token failure."""

import pytest

from services.pixiv_service import PixivService, PixivWorkNotFound, _TokenState, _is_missing_work


def test_missing_work_markers_ignore_token_and_rate_limit_errors():
    assert _is_missing_work(
        {
            "user_message": "該当作品は削除されたか、存在しないため表示できません。",
            "message": "",
            "reason": "",
        }
    )
    assert _is_missing_work("not found")
    assert not _is_missing_work({"message": "Rate Limit", "user_message": ""})
    assert not _is_missing_work(
        {"message": "Error occurred at the OAuth process. Please check your refresh token."}
    )


def _service(client) -> PixivService:
    service = PixivService()
    service._tokens = [_TokenState(id=1, refresh_token="refresh-token", enabled=True, client=client)]
    service.enabled = True
    return service


class _Client:
    def __init__(self, responses):
        self._responses = list(responses)
        self.auth_calls = 0
        self.detail_calls = 0

    def auth(self, refresh_token):
        self.auth_calls += 1
        return {"expires_in": 3600}

    def illust_detail(self, pixiv_id):
        self.detail_calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


async def test_deleted_work_raises_without_refreshing_the_token_again():
    client = _Client(
        [
            {
                "error": {
                    "user_message": "該当作品は削除されたか、存在しないため表示できません。",
                    "message": "",
                    "reason": "",
                }
            }
        ]
    )
    with pytest.raises(PixivWorkNotFound) as caught:
        await _service(client).get_illust_info_by_pixiv_id(123)
    assert caught.value.pixiv_id == "123"
    assert client.detail_calls == 1
    assert client.auth_calls == 1


async def test_null_illust_is_not_found():
    client = _Client([{"illust": None}])
    with pytest.raises(PixivWorkNotFound):
        await _service(client).get_illust_info_by_pixiv_id(123)


async def test_rate_limit_is_not_reported_as_a_missing_work():
    client = _Client(
        [
            {"error": {"user_message": "", "message": "Rate Limit", "reason": ""}},
            {"error": {"user_message": "", "message": "Rate Limit", "reason": ""}},
        ]
    )
    with pytest.raises(RuntimeError, match="All Pixiv tokens failed"):
        await _service(client).get_illust_info_by_pixiv_id(123)
    assert client.detail_calls == 2
