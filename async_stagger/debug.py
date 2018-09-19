import logging


AS_DEBUG = False
logger = logging.getLogger(__package__)


def get_debug():
    return AS_DEBUG


def set_debug(enabled):
    global AS_DEBUG
    AS_DEBUG = enabled
