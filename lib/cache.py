# from functools import lru_cache, wraps
# from frozendict import frozendict
from diskcache import Cache

from .logger import Logger

cache = Cache(".diskcache")
log = Logger("cache")


def delete_cache(func, *args, **kwargs):
    key = func.__cache_key__(*args, **kwargs)
    # key = key[:-1]
    log.info(f"Deleting cache for {key}")
    cache.delete(key)
