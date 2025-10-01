import asyncio
import logging
import time
from dataclasses import dataclass, field

from pixivpy3 import AppPixivAPI

try:
    from pixivpy3 import PixivError  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    class PixivError(Exception):
        """Fallback exception type when pixivpy3 does not expose PixivError."""
        pass

from registries import config_registry
from models import Illustration, build_illust_from_api_dict

logger = logging.getLogger(__name__)


@dataclass
class _TokenState:
    id: int
    refresh_token: str
    enabled: bool
    client: AppPixivAPI = field(default_factory=AppPixivAPI)
    valid_until: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_error: str | None = None


class PixivService:
    def __init__(self) -> None:
        self._tokens: list[_TokenState] = []
        self._next_index: int = 0
        self._state_lock = asyncio.Lock()
        self.enabled: bool = False

    async def read_token_from_config(self) -> None:
        records = await config_registry.get_pixiv_tokens()
        tokens: list[_TokenState] = []

        for record in records:
            if record.id is None:
                continue
            refresh_token = (record.token or "").strip()
            if not refresh_token:
                continue
            tokens.append(
                _TokenState(
                    id=record.id,
                    refresh_token=refresh_token,
                    enabled=record.enable,
                )
            )

        async with self._state_lock:
            self._tokens = tokens
            self._next_index = 0
            self.enabled = any(token.enabled for token in tokens)

        if self.enabled:
            total = len(tokens)
            active = sum(1 for token in tokens if token.enabled)
            logger.info("Loaded %s Pixiv refresh tokens (%s enabled)", total, active)
        else:
            logger.warning("Pixiv features disabled due to missing enabled tokens")

    async def token_refresh(self, force: bool = False) -> None:
        async with self._state_lock:
            tokens = [token for token in self._tokens if token.enabled]

        if not tokens:
            logger.debug("Pixiv token refresh skipped because no enabled tokens")
            return

        for token in tokens:
            try:
                await self._refresh_token(token, force=force)
            except Exception as exc:
                logger.warning("Failed to refresh Pixiv token %s: %s", token.id, exc)

    async def _refresh_token(self, token: _TokenState, *, force: bool = False) -> None:
        async with token.lock:
            now = int(time.time())
            if not force and token.valid_until > now:
                return

            try:
                response = token.client.auth(refresh_token=token.refresh_token)
            except PixivError as exc:
                token.valid_until = 0
                token.last_error = str(exc)
                logger.warning("Pixiv authentication failed for token %s: %s", token.id, exc)
                raise
            except Exception as exc:
                token.valid_until = 0
                token.last_error = str(exc)
                logger.warning("Unexpected Pixiv auth error for token %s: %s", token.id, exc)
                raise

            expires_in = int(response.get("expires_in", 0) or 0)
            token.valid_until = now + max(expires_in - 60, 60)
            token.last_error = None
            logger.debug("Refreshed Pixiv token %s, valid for %s seconds", token.id, expires_in)

    async def _ordered_tokens(self) -> list[_TokenState]:
        async with self._state_lock:
            active = [token for token in self._tokens if token.enabled]
            self.enabled = bool(active)
            if not active:
                raise RuntimeError("Pixiv features are disabled")

            start = self._next_index % len(active)
            order = active[start:] + active[:start]
            self._next_index = (self._next_index + 1) % len(active)

        return order

    async def _fetch_illust_detail(self, pixiv_id: int) -> dict:
        candidates = await self._ordered_tokens()
        last_error: Exception | None = None

        for token in candidates:
            try:
                await self._refresh_token(token)
            except Exception as exc:
                last_error = exc
                continue

            try:
                response = token.client.illust_detail(pixiv_id)
            except PixivError as exc:
                token.valid_until = 0
                token.last_error = str(exc)
                logger.warning("Pixiv API error for token %s: %s", token.id, exc)
                last_error = exc
                continue
            except Exception as exc:
                token.last_error = str(exc)
                logger.warning("Unexpected Pixiv client error for token %s: %s", token.id, exc)
                last_error = exc
                continue

            if response.get("error"):
                logger.warning("Pixiv API responded with error for token %s: %s", token.id, response["error"])
                try:
                    await self._refresh_token(token, force=True)
                    response = token.client.illust_detail(pixiv_id)
                except Exception as exc:
                    token.last_error = str(exc)
                    last_error = exc
                    continue
                if response.get("error"):
                    token.last_error = str(response["error"])
                    last_error = RuntimeError(str(response["error"]))
                    continue

            token.last_error = None
            return response

        raise RuntimeError("All Pixiv tokens failed to fetch illust detail") from last_error

    async def get_raw(self, pixiv_id: int) -> dict:
        return await self._fetch_illust_detail(pixiv_id)

    async def get_illust_info_by_pixiv_id(self, pixiv_id: int) -> Illustration:
        response = await self._fetch_illust_detail(pixiv_id)
        illust_data = response.get("illust")
        if not isinstance(illust_data, dict):
            raise RuntimeError("Pixiv response missing illust data")
        return build_illust_from_api_dict(illust_data)


pixiv = PixivService()
