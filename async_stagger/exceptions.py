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
