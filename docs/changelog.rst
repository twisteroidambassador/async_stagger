Changelog
#########


v0.2.0
======

Backwards incompatible change: :func:`~async_stagger.staggered_race` now takes
an async iterable instead of a regular iterable for its *coro_fns* argument.

A new module :mod:`~async_stagger.aitertools` is added, containing tools for
working with async iterators.
Among other things,
implementations for :func:`~async_stagger.aitertools.aiter`
and :func:`~async_stagger.aitertools.anext`
are provided, analogous to the built-in functions :func:`iter` and :func:`next`.

Implementation detail:
Code for resolving host names to IP addresses are moved to their own module
and made to yield results as async iterables.


v0.1.3
======

Added support for multiple local addresses.


v0.1.2
======

Fixed several bugs.


v0.1.1
======

The first real release. Implements stateless Happy Eyeballs.
