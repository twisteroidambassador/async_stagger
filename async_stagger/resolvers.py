"""Code related to resolving host names to IP addresses.

A resolver is a callable with signature
``resolver(host, port, *, family=0, type=0, proto=0, flags=0)``
(and more optional arguments if necessary)
that returns an async iterable of 5-tuples
``(family, type, proto, canonname, sockaddr)``.
This is almost the same signature as :func:`socket.getaddrinfo`,
except being an async iterator.

Resolvers can be optionally passed as an argument to
:func:`happy_eyeballs.create_connected_sock` and friends,
in order to customize the address resolution logic.
When used this way, the ``host``, ``port``, ``family``, ``proto`` and ``flags``
arguments are passed directly to the resolver, and ``type`` is always
``socket.SOCK_STREAM``.

A resolver implementation should resolve the provided host and port into a
list of addrinfo tuples, and yield them in an ordering appropriate for the
happy eyeballs algorithm.
"""

import asyncio
import collections
import contextlib
import itertools
import socket
from typing import AsyncIterator, Iterable, Optional, Iterator

from . import exceptions
from .typing import AddrInfoType, HostType, PortType
from .debug import debug_log
from .constants import RESOLUTION_DELAY, FIRST_ADDRESS_FAMILY_COUNT


_HAS_IPv6 = hasattr(socket, 'AF_INET6')


async def _getaddrinfo_raise_on_empty(
        host: HostType,
        port: PortType,
        *,
        family: int = socket.AF_UNSPEC,
        type_: int = 0,
        proto: int = 0,
        flags: int = 0,
) -> list[AddrInfoType]:
    # DRY at work.
    loop = asyncio.get_running_loop()
    debug_log(
        'Resolving (%r, %r), family=%r, type=%r, proto=%r, flags=%r',
        host, port, family, type_, proto, flags)
    addrinfos = await loop.getaddrinfo(
        host, port, family=family, type=type_, proto=proto, flags=flags)
    if not addrinfos:
        raise OSError(
            f'getaddrinfo({host!r}, {port!r}, family={family!r}, '
            f'type={type_!r}, proto={proto!r}, flags={flags!r}) '
            f'returned empty list')
    debug_log(
        'Resolved (%r, %r), family=%r, type=%r, proto=%r, flags=%r: %r',
        host, port, family, type_, proto, flags, addrinfos)
    return addrinfos


def _weave(
        first_iter: Iterable,
        *iters: Iterable,
        first_extras: int = 0,
) -> Iterator:
    # Note: iters should not contain None
    output_iters = []
    if first_extras > 0:
        output_iters.append(itertools.islice(first_iter, first_extras))
        first_iter = itertools.islice(first_iter, first_extras, None)
    output_iters.append(
        a for a in itertools.chain.from_iterable(
                itertools.zip_longest(first_iter, *iters)
        ) if a is not None
    )
    return itertools.chain.from_iterable(output_iters)


def _interleave_addrinfos(
        addrinfos: Iterable[AddrInfoType],
        first_address_family_count: int,
) -> list[AddrInfoType]:
    """Interleave list of addrinfo tuples by family."""
    # Group addresses by family
    addrinfos_by_family = collections.OrderedDict()
    for addr in addrinfos:
        family = addr[0]
        if family not in addrinfos_by_family:
            addrinfos_by_family[family] = []
        addrinfos_by_family[family].append(addr)
    addrinfos_lists = list(addrinfos_by_family.values())

    return list(_weave(
        addrinfos_lists[0], *addrinfos_lists[1:], first_extras=first_address_family_count-1))


async def builtin_resolver(
        host,
        port,
        *,
        family: int = socket.AF_UNSPEC,
        type_: int = 0,
        proto: int = 0,
        flags: int = 0,
        first_addr_family_count: int = FIRST_ADDRESS_FAMILY_COUNT,
) -> AsyncIterator[AddrInfoType]:
    """Resolver using built-in getaddrinfo().

    Interleaves addresses by family if required, and yield results as an
    async iterable. Nothing spectacular.
    """
    addrinfos = await _getaddrinfo_raise_on_empty(
        host, port, family=family, type_=type_,
        proto=proto, flags=flags)
    addrinfos = _interleave_addrinfos(addrinfos, first_addr_family_count)
    # it would be nice if "yield from addrinfos" worked, but alas,
    # https://www.python.org/dev/peps/pep-0525/#asynchronous-yield-from
    for ai in addrinfos:
        yield ai


def async_builtin_resolver(
        host,
        port,
        *,
        family: int = socket.AF_UNSPEC,
        type_: int = 0,
        proto: int = 0,
        flags: int = 0,
        resolution_delay: float = RESOLUTION_DELAY,
        first_addr_family_count: int = FIRST_ADDRESS_FAMILY_COUNT,
        raise_exc_group: bool = False,
) -> AsyncIterator[AddrInfoType]:
    """Dispatcher function for async resolver.

    Returns builtin_resolver(...) if family != socket.AF_UNSPEC.
    """
    if _HAS_IPv6 and family == socket.AF_UNSPEC:
        return _async_concurrent_resolver(
            host, port, type_=type_, proto=proto, flags=flags,
            resolution_delay=resolution_delay,
            first_addr_family_count=first_addr_family_count,
            raise_exc_group=raise_exc_group,
        )
    else:
        return builtin_resolver(
            host, port, family=family, type_=type_, proto=proto, flags=flags,
            first_addr_family_count=first_addr_family_count)


async def _async_concurrent_resolver(
        host,
        port,
        *,
        type_: int = 0,
        proto: int = 0,
        flags: int = 0,
        resolution_delay: float = RESOLUTION_DELAY,
        first_addr_family_count: int = FIRST_ADDRESS_FAMILY_COUNT,
        raise_exc_group: bool = False,
) -> AsyncIterator[AddrInfoType]:
    debug_log('Async resolving (%r, %r), type=%r, proto=%r, flags=%r',
              host, port, type_, proto, flags)
    bell = asyncio.Event()
    addrinfos = []
    next_yield_idx = 0
    v4_exception = v6_exception = None

    async with asyncio.TaskGroup() as group:
        async def v6_resolve():
            try:
                v6_addrinfos = await _getaddrinfo_raise_on_empty(
                    host,
                    port,
                    family=socket.AF_INET6,
                    type_=type_,
                    proto=proto,
                    flags=flags,
                )
                if len(addrinfos) > next_yield_idx:
                    # addrinfos must contain already resolved IPv4 addresses
                    v4_addrinfos = addrinfos[next_yield_idx:]
                    del addrinfos[next_yield_idx:]
                    addrinfos.extend(_weave(v6_addrinfos, v4_addrinfos, first_extras=first_addr_family_count-1))
                else:
                    addrinfos.extend(v6_addrinfos)
            except OSError as e:
                nonlocal v6_exception
                v6_exception = e
            finally:
                bell.set()

        v6_task = group.create_task(v6_resolve())

        async def v4_resolve():
            try:
                v4_addrinfos = await _getaddrinfo_raise_on_empty(
                    host,
                    port,
                    family=socket.AF_INET,
                    type_=type_,
                    proto=proto,
                    flags=flags,
                )
                if not v6_task.done():
                    with contextlib.suppress(TimeoutError):
                        async with asyncio.timeout(resolution_delay):
                            await bell.wait()
                if len(addrinfos) > next_yield_idx:
                    # addrinfos must contain already resolved IPv6 addresses
                    v6_addrinfos = addrinfos[next_yield_idx:]
                    extra_v6_addrs = first_addr_family_count - next_yield_idx
                    del addrinfos[next_yield_idx:]
                    if extra_v6_addrs <= 0:
                        addrinfos.extend(_weave(v4_addrinfos, v6_addrinfos))
                    else:
                        addrinfos.extend(_weave(v6_addrinfos, v4_addrinfos, first_extras=extra_v6_addrs-1))
                else:
                    addrinfos.extend(v4_addrinfos)
            except OSError as e:
                nonlocal v4_exception
                v4_exception = e
            finally:
                bell.set()

        v4_task = group.create_task(v4_resolve())

        while True:
            if len(addrinfos) > next_yield_idx:
                next_yield_value = addrinfos[next_yield_idx]
                next_yield_idx += 1
                yield next_yield_value
                continue
            if v6_task.done() and v4_task.done():
                break
            bell.clear()
            await bell.wait()

    if next_yield_idx > 0:
        return
    exc = [v6_exception, v4_exception]
    if raise_exc_group:
        raise ExceptionGroup('No resolution result', exc)
    else:
        exceptions.raise_one_exception_from_many(exc, socket.gaierror)
