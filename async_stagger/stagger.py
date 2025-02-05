"""Contains the core scheduling logic for Happy Eyeballs.

staggered_race is also imported into the base package for convenience.
"""

import asyncio
from contextlib import suppress
from typing import (
    Callable, Any, Optional, AsyncIterable, Awaitable
)

from . import aitertools
from .debug import debug_log

__all__ = ['staggered_race']


async def staggered_race(
        coro_fns: AsyncIterable[Callable[[], Awaitable]],
        delay: Optional[float],
) -> tuple[
    Any,
    Optional[int],
    list[Optional[Exception]],
    Optional[Exception],
]:
    """Run coroutines with staggered start times and take the first to finish.

    This function takes an async iterable of coroutine functions. The first one
    is retrieved and started immediately. From then on, whenever the
    immediately preceding one fails (raises an exception), or when *delay*
    seconds has passed, the next coroutine is retrieved and started. This
    continues until one of the coroutines complete successfully, in which
    case all others are cancelled, or until all coroutines fail.

    The coroutines provided should be well-behaved in the following way:

    * They should only ``return`` if completed successfully.

    * They should always raise an exception if they did not complete
      successfully. In particular, if they handle cancellation, they should
      probably reraise, like this::

        try:
            # do work
        except asyncio.CancelledError:
            # undo partially completed work
            raise

    Args:
        coro_fns: an async iterable of coroutine functions, i.e. callables that
            return a coroutine object when called.
            Use :func:`functools.partial` or lambdas to pass arguments.
            If you want to use a regular iterable here, wrap it with
            :func:`~aitertools.aiter_from_iter`.

        delay: amount of time, in seconds, between starting coroutines. If
            ``None``, the coroutines will run sequentially.

    Returns:
        tuple *(winner_result, winner_index, coro_exc, aiter_exc)* where

        - *winner_result*: the result of the winning coroutine, or ``None``
          if no coroutines won.

        - *winner_index*: the index of the winning coroutine in
          ``coro_fns``, or ``None`` if no coroutines won. If the winning
          coroutine may return None on success, *winner_index* can be used
          to definitively determine whether any coroutine won.

        - *coro_exc*: list of exceptions raised by the coroutines.
          ``len(exceptions)`` is equal to the number of coroutines actually
          started, and the order is the same as in ``coro_fns``. The winning
          coroutine's entry is ``None``.

        - *aiter_exc*: exception raised by the *coro_fns* async iterable,
          or ``None`` if *coro_fns* was iterated to completion without raising
          any exception.

    .. versionchanged:: v0.2.0
       *coro_fns* argument now takes an async iterable instead of a regular
       iterable.

    .. versionchanged:: v0.3.0
       The return value is now a 4-tuple. *aiter_exc* is added.

    .. versionchanged:: v0.4.0
       Removed *loop* parameter.

    """
    aiter_coro_fns = aiter(coro_fns)
    winner_result = None
    winner_index = None
    exceptions = []
    tasks = set()
    taskgroup = asyncio.TaskGroup()
    aiter_exc = None

    async def run_one_coro(
            previous_failed: Optional[asyncio.Event],
            this_index: int = 0,
    ) -> None:
        this_task = asyncio.current_task()
        # If we're running under eager task factory, add this_task to tasks.
        # If we're running under lazy task factory, then this_task has already
        # been added to tasks, and this is a no-op.
        tasks.add(this_task)
        # Wait for the previous task to finish, or for delay seconds
        if previous_failed is not None:
            with suppress(asyncio.TimeoutError):
                async with asyncio.timeout(delay):
                    await previous_failed.wait()
        # Get the next coroutine to run
        try:
            coro_fn = await anext(aiter_coro_fns)
        except StopAsyncIteration:
            debug_log('Async iterator exhausted on iteration %d', this_index)
            return
        except Exception as e:
            nonlocal aiter_exc
            aiter_exc = e
            debug_log('Async iterator raised exception on iteration %d',
                      this_index, exc_info=True)
            return
        # Start task that will run the next coroutine
        this_failed = asyncio.Event()
        next_task = taskgroup.create_task(run_one_coro(this_failed, this_index+1))
        # If we're running under lazy task factory, add next_task to tasks.
        # If we're running under eager task factory, then next_task has already been
        # added to tasks by itself, and this is a no-op.
        tasks.add(next_task)
        # Prepare place to put this coroutine's exceptions if not won
        exceptions.append(None)
        assert len(exceptions) == this_index + 1

        coro = coro_fn()
        debug_log('Got coroutine function %r, will run coroutine %r',
                  coro_fn, coro)
        try:
            result = await coro
        except asyncio.CancelledError as e:
            debug_log('Coroutine %r cancelled', coro)
            exceptions[this_index] = e
        except Exception as e:
            debug_log('Coroutine %r failed with exception',
                      coro, exc_info=True)
            exceptions[this_index] = e
        else:
            debug_log(
                'Coroutine %r completed successfully, result: %r',
                coro, result)
            # Store winner's results
            nonlocal winner_index, winner_result
            assert winner_index is None
            winner_index = this_index
            winner_result = result
            # Cancel all other tasks. We take care to not cancel the current
            # task as well. If we do so, then since there is no `await` after
            # here and CancelledError are usually thrown at one, we will
            # encounter a curious corner case where the current task will end
            # up as done() == True, cancelled() == False, exception() ==
            # asyncio.CancelledError, which is normally not possible.
            # https://bugs.python.org/issue33413
            for t in tasks:
                if t is not this_task:
                    t.cancel()
            # Note: we could also have abused the cancellation handling of
            # TaskGroups to cancel all other tasks, by raising an exception
            # from this task. However, doing that means the other tasks are
            # cancelled slower, probably after one or more iterations of the
            # event loop. This gives those tasks some chance to run or even
            # finish successfully, which breaks the assumption that only one
            # task wins. So we do not do that.
        finally:
            this_failed.set()  # Kickstart the next coroutine

    try:
        async with taskgroup:
            first_task = taskgroup.create_task(run_one_coro(None))
            tasks.add(first_task)
            # exiting *async with* waits for all tasks in taskgroup
            # If any task in taskgroup raises an unhandled exception,
            # a BaseExceptionGroup will be raised here
        return winner_result, winner_index, exceptions, aiter_exc
    finally:
        await aitertools.aiterclose(aiter_coro_fns)
