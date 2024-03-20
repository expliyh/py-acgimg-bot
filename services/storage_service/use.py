from registries import config_registry
from . import Storage

from .backblaze import backblaze


async def use() -> Storage | None:
    config = await config_registry.get_config("storage_service_use")
    if config is None:
        return None
    match config.value_str:
        case "backblaze":
            return backblaze
        case _:
            raise Exception("Unknown storage service")
