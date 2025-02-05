"""These are some fuzzing-type tests throwing random conditions at
staggered_race to flush out logic bugs.
"""

import asyncio
import random

from functools import partial
from itertools import count

import pytest

from .stagger import staggered_race
from .aitertools import aiter_from_iter


@pytest.mark.asyncio
async def test_simultaneous_done_fail():
    for _ in range(50):
        await simultaneous_done_fail()


async def simultaneous_done_fail():
    async def first():
        await asyncio.sleep(0.3)
        return 1

    async def second():
        await asyncio.sleep(0.1)
        raise RuntimeError('2')

    async def third():
        await asyncio.sleep(0.05)
        return 3

    coro_fns = aiter_from_iter((first, second, third))

    winner_result, winner_idx, exc, aiter_exc = await staggered_race(coro_fns, 0.2)


@pytest.mark.asyncio
async def test_stagger_random_tasks():
    for _ in range(10):
        await random_tasks()


async def random_tasks():
    async def one_coro(index, sleep_for, succeed):
        print('Coroutine %d starting, will sleep for %f' % (index, sleep_for))
        await asyncio.sleep(sleep_for)
        if succeed:
            print('Coroutine %d finishing' % index)
            return index
        else:
            print('Coroutine %d raising RuntimeError' % index)
            raise RuntimeError

    coro_fns = aiter_from_iter(
        partial(one_coro, i, random.random() * 2, random.random() < 0.8)
        for i in range(10))
    delay = 0.3
    winner_result, winner_idx, exc, aiter_exc = \
        await staggered_race(coro_fns, delay)
    if winner_idx is not None:
        assert winner_result == winner_idx
        for i, e in enumerate(exc):
            if i == winner_idx:
                assert e is None
            else:
                assert isinstance(e, (RuntimeError, asyncio.CancelledError))
    else:
        assert all(isinstance(e, RuntimeError) for e in exc)


@pytest.mark.asyncio
async def test_stagger_tasks_nosleep():
    async def one_coro(index):
        if index > 8:
            return index
        raise RuntimeError
    
    coro_fns = aiter_from_iter(partial(one_coro, i) for i in range(12))
    winner_result, winner_idx, exc, aiter_exc = await staggered_race(coro_fns, 0.1)
    assert winner_idx == 9
    assert winner_result == 9
    assert len(exc) == 10
    assert aiter_exc is None


@pytest.mark.asyncio
async def test_stagger_random_tasks_possible_nosleep():
    for _ in range(10):
        await random_tasks_possible_nosleep()


async def random_tasks_possible_nosleep():
    async def one_coro(index, sleep_for, succeed):
        print('Coroutine %d starting, will sleep for %f' % (index, sleep_for))
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)
        if succeed:
            print('Coroutine %d finishing' % index)
            return index
        else:
            print('Coroutine %d raising RuntimeError' % index)
            raise RuntimeError

    coro_fns = aiter_from_iter(
        partial(one_coro, i, 0 if random.random() < 0.8 else random.random() * 2, random.random() < 0.8)
        for i in range(10))
    delay = 0.3
    winner_result, winner_idx, exc, aiter_exc = \
        await staggered_race(coro_fns, delay)
    if winner_idx is not None:
        assert winner_result == winner_idx
        for i, e in enumerate(exc):
            if i == winner_idx:
                assert e is None
            else:
                assert isinstance(e, (RuntimeError, asyncio.CancelledError))
    else:
        assert all(isinstance(e, RuntimeError) for e in exc)


@pytest.mark.asyncio
async def test_stagger_coro_gen():
    for _ in range(10):
        await infinite_coros()


async def infinite_coros():
    async def one_coro(index, sleep_for, succeed):
        print('Coroutine %d starting, will sleep for %f' % (index, sleep_for))
        await asyncio.sleep(sleep_for)
        if succeed:
            print('Coroutine %d finishing' % index)
            return index
        else:
            print('Coroutine %d raising RuntimeError' % index)
            raise RuntimeError

    def coros_gen():
        for i in count():
            yield partial(one_coro, i, random.random(), random.random() > 0.9)

    print(await staggered_race(aiter_from_iter(coros_gen()), 0.1))


@pytest.mark.asyncio
async def test_stagger_simultaneous_done():
    for _ in range(5):
        await simultaneous_done()


async def simultaneous_done():
    coro_fns = aiter_from_iter(
        partial(asyncio.sleep, i*0.2) for i in range(5, 0, -1))
    winner_result, winner_idx, exceptions, aiter_exc = \
        await staggered_race(coro_fns, 0.2)
    assert winner_idx is not None
    assert all(isinstance(e, asyncio.CancelledError)
               for i, e in enumerate(exceptions)
               if i != winner_idx)


@pytest.mark.asyncio
async def test_stagger_no_delay():
    for _ in range(5):
        await no_delay()


async def no_delay():
    async def sleeper(sleep_for, succeed):
        await asyncio.sleep(sleep_for)
        if succeed:
            return
        else:
            raise RuntimeError

    decisions = [random.random()>0.8 for _ in range(10)]
    coro_fns = aiter_from_iter(partial(sleeper, 0.1, d) for d in decisions)
    winner_result, winner_idx, exceptions, aiter_exc = \
        await staggered_race(coro_fns, None)
    if winner_idx is not None:
        assert all(not d for d in decisions[:winner_idx])
        assert decisions[winner_idx]
        assert winner_idx == len(exceptions) - 1
        assert all(isinstance(e, RuntimeError) for e in exceptions[:-1])
    else:
        assert all(not d for d in decisions)
        assert all(isinstance(e, RuntimeError) for e in exceptions)
