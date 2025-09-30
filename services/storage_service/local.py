from __future__ import annotations

from pathlib import Path

import aiofiles

from registries import config_registry
from .Storage import Storage


class LocalStorage(Storage):
    def __init__(self) -> None:
        super().__init__("local")
        self.root_path: Path | None = None
        self.base_url: str | None = None

    async def _load_config(self) -> None:
        config = await config_registry.get_local_storage_config()
        root_path = config.root_path or "storage"
        self.root_path = Path(root_path).expanduser().resolve()
        self.base_url = config.base_url
        self.root_path.mkdir(parents=True, exist_ok=True)

    async def upload(self, file: bytes, filename: str, sub_folder: str | None = None) -> str:
        await self.ensure_ready()
        if self.root_path is None:
            raise RuntimeError("Local storage root path is not configured")

        folder = self.normalize_sub_folder(sub_folder)
        destination_dir = self.root_path
        if folder:
            destination_dir = self.root_path.joinpath(*folder.rstrip("/").split("/"))
            destination_dir.mkdir(parents=True, exist_ok=True)

        destination_path = destination_dir / filename
        async with aiofiles.open(destination_path, "wb") as fp:
            await fp.write(file)

        if self.base_url:
            relative_path = destination_path.relative_to(self.root_path).as_posix()
            return f"{self.base_url.rstrip('/')}/{relative_path}"
        return str(destination_path)


local_storage = LocalStorage()
