from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod


class Storage(ABC):
    """Asynchronous storage provider abstraction supporting dynamic configuration."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._config_lock = asyncio.Lock()
        self._configured = False

    async def get_config(self) -> None:
        """Load or refresh provider configuration."""

        async with self._config_lock:
            await self._load_config()
            self._configured = True

    async def ensure_ready(self) -> None:
        """Ensure configuration is loaded before the provider is used."""

        if self._configured:
            return
        await self.get_config()

    @abstractmethod
    async def _load_config(self) -> None:
        """Fetch provider-specific configuration data."""

    @abstractmethod
    async def upload(self, file: bytes, filename: str, sub_folder: str | None = None) -> str:
        """Persist a file and return a public URL for the uploaded object."""

    @staticmethod
    def normalize_sub_folder(sub_folder: str | None) -> str:
        if not sub_folder:
            return ""
        normalized = sub_folder.replace("\\", "/").strip("/")
        return f"{normalized}/" if normalized else ""

    @staticmethod
    def join_path(*segments: str) -> str:
        parts: list[str] = []
        for segment in segments:
            if not segment:
                continue
            cleaned = segment.replace("\\", "/").strip("/")
            if cleaned:
                parts.append(cleaned)
        return "/".join(parts)

    def build_object_path(self, base_path: str | None, filename: str, sub_folder: str | None = None) -> str:
        return self.join_path(base_path or "", self.normalize_sub_folder(sub_folder), filename)
