import asyncio
import itertools
from typing import AsyncIterable

import pytest

from . import aitertools


async def arange(x, *, delay=0):
    """One-argument, async version of range() for test purposes."""
    for i in range(x):
        await asyncio.sleep(delay)
        yield i


@pytest.mark.asyncio
async def test_aiter_from_iter():
    lst = list(range(10))
    new_lst = []
    async for item in aitertools.aiter_from_iter(lst):
        new_lst.append(item)
    assert lst == new_lst


async def list_from_aiter(aiterable: AsyncIterable) -> list:
    new_list = []
    async for item in aiterable:
        new_list.append(item)
    return new_list


@pytest.mark.asyncio
async def test_product_noargs():
    assert (await list_from_aiter(aitertools.product())
            == list(itertools.product()))


@pytest.mark.asyncio
async def test_product_empty_arg():
    result_product = list(itertools.product(range(1), range(0)))
    result_aproduct = await list_from_aiter(
        aitertools.product(arange(1), arange(0)))
    assert result_aproduct == result_product


@pytest.mark.asyncio
async def test_product_zero_repeat():
    assert (await list_from_aiter(aitertools.product(arange(2), repeat=0))
            == list(itertools.product(range(2), repeat=0)))


@pytest.mark.asyncio
async def test_product():
    result_product = list(itertools.product(range(1)))
    result_aproduct = await list_from_aiter(aitertools.product(arange(1)))
    assert result_aproduct == result_product

    result_product = list(itertools.product(range(1), range(2), range(1)))
    result_aproduct = await list_from_aiter(aitertools.product(
        arange(1), arange(2), arange(1)))
    assert result_aproduct == result_product

    result_product = list(itertools.product(range(3), range(2), range(4)))
    result_aproduct = await list_from_aiter(aitertools.product(
        arange(3), arange(2), arange(4)))
    assert result_aproduct == result_product


@pytest.mark.asyncio
async def test_product_with_repeat():
    result_product = list(itertools.product(
        range(3), range(2), repeat=3))
    result_aproduct = await list_from_aiter(aitertools.product(
        arange(3), arange(2), repeat=3))
    assert result_aproduct == result_product

