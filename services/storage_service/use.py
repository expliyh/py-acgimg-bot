from collections.abc import Mapping

from registries import config_registry
from .Storage import Storage
from .backblaze import backblaze
from .local import local_storage
from .webdav import webdav_storage


_STORAGE_PROVIDERS: Mapping[str, Storage] = {
    "backblaze": backblaze,
    "webdav": webdav_storage,
    "local": local_storage,
}


async def use() -> Storage | None:
    config = await config_registry.get_config("storage_service_use")
    if config is None:
        return None

    provider_key = str(config).strip().lower()
    if not provider_key or provider_key in {"none", "disabled"}:
        return None

    try:
        return _STORAGE_PROVIDERS[provider_key]
    except KeyError as exc:
        raise Exception(f"Unknown storage service: {provider_key}") from exc
