from .root import root
from .set_backblaze_appid import set_backblaze_appid
from .set_user_nickname import set_user_nickname
from .set_pixiv_token import set_pixiv_token
from .set_cache_ttl import set_cache_ttl
from .set_cache_redis import set_cache_redis

index = {
    "root": root,
    "set_backblaze_appid": set_backblaze_appid,
    "set_user_nickname": set_user_nickname,
    "set_pixiv_token": set_pixiv_token,
    "set_cache_ttl": set_cache_ttl,
    "set_cache_redis": set_cache_redis,
}
