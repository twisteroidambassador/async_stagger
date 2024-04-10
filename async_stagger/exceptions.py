__all__ = [
    'HappyEyeballsConnectError',
]


def raise_one_exception_from_many(exc: list[Exception], exc_class: type[Exception]):
    if len(exc) == 1:
        raise exc[0]
    else:
        model_exc = exc[0]
        model_type = type(model_exc)
        model_str = str(model_exc)
        if all(str(e) == model_str and type(e) == model_type for e in exc):
            raise exc[0]
        raise exc_class('Multiple exceptions: {}'.format(
            ', '.join(repr(exc) for exc in exc)))


class HappyEyeballsConnectError(Exception):
    """Encapsulate all exceptions encountered during connection.

    This exception is raised when :func:`~async_stagger.create_connected_sock`
    fails with the *detailed_exceptions* argument set. The *args* of this
    exception consists of a list of exceptions occurred during all connection
    attempts and address resolution.
    """
    pass
