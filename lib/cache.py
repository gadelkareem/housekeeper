# from functools import lru_cache, wraps
# from frozendict import frozendict
from diskcache import Cache

from .utils import Utils
from .logger import Logger

cache = Cache(".diskcache")
log = Logger("cache")


# def freezeargs(func):
#     """Transform mutable dictionnary
#     Into immutable
#     Useful to be compatible with cache
#     """
#
#     @wraps(func)
#     def wrapped(*args, **kwargs):
#         args = tuple(
#             [frozendict(arg) if isinstance(arg, dict) else arg for arg in args]
#         )
#         kwargs = {
#             k: frozendict(v) if isinstance(v, dict) else v for k, v in kwargs.items()
#         }
#         return func(*args, **kwargs)
#
#     return wrapped


def delete_cache(func, *args, **kwargs):
    key = func.__cache_key__(*args, **kwargs)
    # key = key[:-1]
    log.info(f"Deleting cache for {key}")
    cache.delete(key)

