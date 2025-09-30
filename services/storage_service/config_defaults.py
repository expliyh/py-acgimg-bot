from __future__ import annotations

STORAGE_CONFIG_DEFAULTS: dict[str, str] = {
    'storage_service_use': 'local',
    'backblaze_app_id': '',
    'backblaze_app_key': '',
    'backblaze_bucket_name': '',
    'backblaze_base_path': '',
    'backblaze_base_url': '',
    'webdav_endpoint': '',
    'webdav_username': '',
    'webdav_password': '',
    'webdav_base_path': '',
    'webdav_public_url': '',
    'local_storage_root': 'storage',
    'local_storage_base_url': '',
}


async def ensure_storage_config_defaults() -> None:
    from registries.config_registry import init_database_config

    await init_database_config(STORAGE_CONFIG_DEFAULTS)
