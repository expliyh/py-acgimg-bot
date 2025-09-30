from __future__ import annotations

from aiohttp import BasicAuth, ClientSession, ClientTimeout

from registries import config_registry
from .Storage import Storage


class WebDavStorage(Storage):
    def __init__(self) -> None:
        super().__init__("webdav")
        self.endpoint: str | None = None
        self.username: str | None = None
        self.password: str | None = None
        self.base_path: str | None = None
        self.public_base_url: str | None = None

    async def _load_config(self) -> None:
        config = await config_registry.get_webdav_config()
        self.endpoint = (config.endpoint or "").rstrip("/") or None
        self.username = config.username
        self.password = config.password
        self.base_path = config.base_path or ""
        self.public_base_url = (config.public_base_url or None)

        if self.endpoint is None:
            raise RuntimeError("WebDAV endpoint is not configured")

    async def _ensure_remote_path(self, session: ClientSession, directory: str) -> None:
        if not directory:
            return
        segments = [segment for segment in directory.split("/") if segment]
        current_path: list[str] = []
        for segment in segments:
            current_path.append(segment)
            url = f"{self.endpoint}/{'/'.join(current_path)}"
            async with session.request("MKCOL", url) as response:
                if response.status in {201, 301, 405}:
                    # 201 created, 301/405 already exists
                    continue
                if response.status in {200, 204}:
                    continue
                if response.status >= 400:
                    body = await response.text()
                    raise RuntimeError(f"WebDAV MKCOL failed ({response.status}): {body}")

    async def upload(self, file: bytes, filename: str, sub_folder: str | None = None) -> str:
        await self.ensure_ready()
        if self.endpoint is None:
            raise RuntimeError("WebDAV endpoint is not configured")

        object_name = self.build_object_path(self.base_path, filename, sub_folder)
        directory = object_name.rsplit("/", 1)[0] if "/" in object_name else ""

        auth = None
        if self.username:
            auth = BasicAuth(self.username, self.password or "")

        timeout = ClientTimeout(total=60)
        async with ClientSession(auth=auth, timeout=timeout) as session:
            await self._ensure_remote_path(session, directory)
            upload_url = f"{self.endpoint}/{object_name}"
            async with session.put(upload_url, data=file) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise RuntimeError(f"WebDAV upload failed ({response.status}): {body}")

        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{object_name}"
        return upload_url


webdav_storage = WebDavStorage()
