import asyncio
import logging
import sys


PY38 = sys.version_info >= (3, 8)


AS_DEBUG = False
logger = logging.getLogger(__package__)


def get_debug():
    return AS_DEBUG


def set_debug(enabled):
    global AS_DEBUG
    AS_DEBUG = enabled


def debug_log(msg, *args, **kwargs):
    if not AS_DEBUG:
        return

    if PY38:
        # In Python 3.8, Tasks have unique names. Printing these names may help
        # debugging, but it also makes the logs much more verbose.
        logger.debug('%r ' + msg, asyncio.current_task(), *args, **kwargs)
    else:
        logger.debug(msg, *args, **kwargs)