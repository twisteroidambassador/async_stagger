Changelog
#########

v0.4.1
======

Eager task factories, introduced in Python 3.12, is now supported.

:func:`~async_stagger.aitertools.product` may now raise :class:`ExceptionGroup` s
if some async iterables raises exceptions producing a first output.

v0.4.0
======

Started using features in Python 3.11.
As a result, dropped support for Python 3.10 and lower.

Factored out resolvers from the main connection logic.
Resolvers can now be customized and plugged into `open_connection` and friends.

Removed :func:`~async_stagger.aitertools.aiter`
and :func:`~async_stagger.aitertools.anext`
from :mod:`~async_stagger.aitertools`
because they are now built-in.

v0.4.0.post1 includes no code changes.
Only changes to the documentation and metadata are made.

v0.3.1
======

Added support for Python 3.8.

Added :func:`~async_stagger.aitertools.aiterclose` that tries to close an
async iterator.


v0.3.0
======

Backwards incompatible change:
Added new return value *aiter_exc* to :func:`~async_stagger.staggered_race`.
It contains the exception raised by the async iterator, if any.

Added new argument *detailed_exceptions* to
:func:`~async_stagger.create_connected_sock`.
When set to True, when the connection fails, a
:class:`~async_stagger.exceptions.HappyEyeballsConnectError` is raised,
containing all the exceptions raised by the connect / resolution tasks.

Added debug logging features.


v0.2.1
======

Added support for asynchronous address resolution: IPv6 and IPv4 addresses for
a hostname can be resolved in parallel, and connection attempts may start
as soon as either address family is resolved. This reduces time needed for
connection establishment in cases where resolution for a certain address family
is slow.


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
