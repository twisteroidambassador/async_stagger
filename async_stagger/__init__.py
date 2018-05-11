from .happy_eyeballs import create_connected_sock, create_connection, \
    open_connection
from .stagger import staggered_race

__all__ = stagger.__all__ + happy_eyeballs.__all__
