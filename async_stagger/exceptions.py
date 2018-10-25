__all__ = [
    'HappyEyeballsConnectError',
]


class HappyEyeballsConnectError(Exception):
    """Encapsulate all exceptions encountered during connection.

    This exception is raised when :func:`~async_stagger.create_connected_sock`
    fails with the *detailed_exceptions* argument set. The *args* of this
    exception consists of a list of exceptions occurred during all connection
    attempts and address resolution.
    """
    pass
