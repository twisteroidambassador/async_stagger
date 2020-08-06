"""Tools for working with async iterators."""
import asyncio
import collections.abc
import itertools
from typing import (
    AsyncIterable, AsyncIterator, Awaitable, Iterable, TypeVar)

__all__ = ['aiter', 'anext', 'aiterclose', 'aiter_from_iter', 'product']


T = TypeVar('T')


# Get aiter() and anext() somewhere
try:
    from builtins import aiter
except ImportError:
    # https://bugs.python.org/issue31861 talks about potentially putting
    # aiter() and anext() in the operator module
    try:
        from operator import aiter
    except ImportError:
        def aiter(aiterable: AsyncIterable[T]) -> AsyncIterator[T]:
            """Return an async iterator from an async iterable.

            If an ``aiter`` function is available as a builtin or in the
            :mod:`operator` module, it is imported into
            :mod:`async_stagger.aitertools`, and this function will not be
            defined.
            Only when a stock ``aiter`` is not available will this
            function be defined.

            Unlike the built-in :func:`iter()`, this only support one argument,
            and does not support the two-argument (callable, sentinel) usage.

            Adapted from implementation attached to
            https://bugs.python.org/issue31861 by Davide Rizzo.

            Args:
                aiterable: The async iterable.

            Returns:
                The async iterator produced from the given async iterable.
            """
            if not isinstance(aiterable, collections.abc.AsyncIterable):
                raise TypeError(
                    f'{type(aiterable).__name__!r} object '
                    f'is not asynchronously iterable')
            return aiterable.__aiter__()

try:
    from builtins import anext
except ImportError:
    try:
        from operator import anext
    except ImportError:
        def anext(aiterator: AsyncIterator[T]) -> Awaitable[T]:
            """Return the next item from an async iterator.

            If an ``anext`` function is available as a builtin or in the
            :mod:`operator` module, it is imported into
            :mod:`async_stagger.aitertools`, and this function will not be
            defined.
            Only when a stock ``anext`` is not available will this
            function be defined.

            Unlike the built-in :func:`next`, this does not support providing a
            default value.

            This is a regular function that returns an awaitable, so usually
            you should await its result: ``await anext(it)``

            Adapted from implementation attached to
            https://bugs.python.org/issue31861 by Davide Rizzo.

            Args:
                aiterator: the async iterator.

            Returns:
                An awaitable that will return the next item in the iterator.
            """
            if not isinstance(aiterator, collections.abc.AsyncIterator):
                raise TypeError(f'{type(aiterator).__name__!r} object '
                                f'is not an asynchronous iterator')
            return aiterator.__anext__()


async def aiterclose(aiterator: AsyncIterator):
    """Close the async iterator if possible.

    Async generators have an ``aclose()`` method that closes the generator and
    cleans up associated resources. Plain async iterators do not have anything
    similar, but :pep:`533` suggests adding an ``__aiterclose__()`` method, and having
    it called automatically when exiting from an ``async with`` loop.

    This function tries to close the async iterator using either method, and
    if neither is available, does nothing.

    Args:
        aiterator: the async iterator to close.
    """
    if not isinstance(aiterator, collections.abc.AsyncIterator):
        raise TypeError(f'{type(aiterator).__name__!r} object '
                        f'is not an asynchronous iterator')
    if hasattr(aiterator, "__aiterclose__"):
        # PEP 533 recommends that "__aiterclose__ calls self.aclose()",
        # so we assume it does, and do not call aclose() ourselves
        return await aiterator.__aiterclose__()
    if hasattr(aiterator, "aclose"):
        return await aiterator.aclose()


async def aiter_from_iter(
        iterable: Iterable[T],
) -> AsyncIterator[T]:
    """Wrap an async iterator around a regular iterator.

    Args:
        iterable: a regular iterable.

    Returns:
        An async iterator yielding the same items as the original iterable.
    """
    for item in iterable:
        yield item


async def product(
        *aiterables: AsyncIterable,
        repeat: int = 1,
) -> AsyncIterator:
    """Async version of :func:`itertools.product`.

    Compute the cartesian product of input iterables. The arguments are
    analogous to its :mod:`itertools` counterpart.

    The input async iterables are evaluated lazily. As a result the last
    input iterable is iterated and exhausted first, then the next-to-last is
    iterated, and so on.

    Args:
        aiterables: input async iterables.

        repeat: used to compute the product of input async iterables with
            themselves.
    """
    if not isinstance(repeat, int):
        raise TypeError(
            f'integer argument expected, got {type(repeat).__name__}')
    if repeat < 0:
        raise ValueError('repeat argument cannot be negative')
    if not aiterables:
        # no arguments: yield an empty tuple to match itertools.product.
        yield ()
        return
    if repeat == 0:
        # yield empty tuple to match itertools.product.
        yield ()
        return
    aiterators = [aiter(a) for a in aiterables]
    try:
        try:
            initial_values = await asyncio.gather(*(anext(a) for a in aiterators))
        except StopAsyncIteration:
            # some of the aiterators are empty:
            # yield nothing to match itertools.product
            return
        initial_prefix = initial_values * (repeat - 1)
        yield tuple(itertools.chain(initial_prefix, initial_values))
        rev_values = list([v] for v in reversed(initial_values))

        for rev_idx, aiter_to_exhaust in enumerate(reversed(aiterators)):
            async for item in aiter_to_exhaust:
                rev_values[rev_idx].append(item)
                for exhausted_product in itertools.product(
                        *reversed(rev_values[:rev_idx])):
                    yield tuple(itertools.chain(
                        initial_prefix,
                        initial_values[:-1-rev_idx],
                        (item,),
                        exhausted_product,
                    ))

        values = list(reversed(rev_values))
        prefix_product = itertools.product(*values, repeat=repeat-1)
        next(prefix_product)
        for prefix in prefix_product:
            for p in itertools.product(*values):
                yield tuple(itertools.chain(prefix, p))
    finally:
        for it in aiterators:
            await aiterclose(it)
