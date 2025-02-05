"""Tools for working with async iterators."""
import asyncio
import collections.abc
import itertools
from typing import (
    AsyncIterable, AsyncIterator, Iterable, TypeVar)

__all__ = ['aiterclose', 'aiter_from_iter', 'product']


T = TypeVar('T')


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

    Notes on concurrency:

    Getting the first values from *aiterables* are run in parallel.
    If any async iterator(s) raises an exception, they are wrapped up in an
    :class:`ExceptionGroup`.

    In later steps, each input async iterables is evaluated lazily when needed.
    As a result the last
    input iterable is iterated and exhausted first, then the next-to-last is
    iterated, and so on.

    Args:
        aiterables: input async iterables.

        repeat: used to compute the product of input async iterables with
            themselves.
    
    .. versionchanged:: v0.4.1
       :class:`ExceptionGroup` s can now be raised in certain situations.
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
        some_aiterators_empty = False
        try:
            initial_values = [None] * len(aiterators)

            async def store_initial_value(i, a):
                initial_values[i] = await(anext(a))

            async with asyncio.TaskGroup() as group:
                for i, a in enumerate(aiterators):
                    group.create_task(store_initial_value(i, a))
        except* StopAsyncIteration:
            # some of the aiterators are empty:
            # yield nothing to match itertools.product
            some_aiterators_empty = True
        if some_aiterators_empty:
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
