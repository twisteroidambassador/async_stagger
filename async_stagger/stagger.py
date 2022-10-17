"""Contains the core scheduling logic for Happy Eyeballs.

staggered_race is also imported into the base package for convenience.
"""

import asyncio
from contextlib import suppress
from typing import (
    Callable, Any, Tuple, List, Optional, AsyncIterable, Awaitable
)

from . import aitertools
from .debug import debug_log

__all__ = ['staggered_race']


async def staggered_race(
        coro_fns: AsyncIterable[Callable[[], Awaitable]],
        delay: Optional[float],
) -> Tuple[
    Any,
    Optional[int],
    List[Optional[Exception]],
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
    tasks = []
    aiter_exc = None

    async def run_one_coro(
            previous_failed: Optional[asyncio.Event],
            this_index: int = 0,
    ) -> None:
        # Wait for the previous task to finish, or for delay seconds
        if previous_failed is not None:
            with suppress(asyncio.TimeoutError):
                # Use asyncio.wait_for() instead of asyncio.wait() here, so
                # that if we get cancelled at this point, Event.wait() is also
                # cancelled, otherwise there will be a "Task destroyed but it is
                # pending" later.
                await asyncio.wait_for(previous_failed.wait(), delay)
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
        next_task = asyncio.create_task(run_one_coro(this_failed, this_index+1))
        tasks.append(next_task)
        assert len(tasks) == this_index + 2
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
            for i, t in enumerate(tasks):
                if i != this_index:
                    t.cancel()
        finally:
            this_failed.set()  # Kickstart the next coroutine

    first_task = asyncio.create_task(run_one_coro(None))
    tasks.append(first_task)
    try:
        # Wait for a growing list of tasks to all finish: poor man's version of
        # curio's TaskGroup or trio's nursery
        done_count = 0
        while done_count != len(tasks):
            done, _ = await asyncio.wait(tasks)
            done_count = len(done)
            # If run_one_coro raises an unhandled exception, it's probably a
            # programming error, and I want to see it.
            if __debug__:
                for d in done:
                    if d.done() and not d.cancelled() and d.exception():
                        raise RuntimeError(
                            'Logic bug in staggeed_race() or '
                            'catastrophic failure in asyncio'
                        ) from d.exception()
        return winner_result, winner_index, exceptions, aiter_exc
    finally:
        # Make sure no tasks are left running if we leave this function
        for t in tasks:
            t.cancel()
        await asyncio.wait(tasks)
        await aitertools.aiterclose(aiter_coro_fns)
