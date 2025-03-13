"""Code related to resolving host names to IP addresses.

A resolver is a callable with signature
``resolver(host, port, *, family=0, type=0, proto=0, flags=0)``
(and more optional arguments if necessary)
that returns an async iterable of 5-tuples
``(family, type, proto, canonname, sockaddr)``.
This is almost the same signature as :func:`socket.getaddrinfo`,
except returning an async iterator instead of a list.

This module provides two resolvers.
:func:`basic_resolver` resolves IPv4 and IPv6 addresses together, and
:func:`concurrent_resolver` (the default used by :func:`~async_stagger.create_connected_sock`)
resolves IPv4 and IPv6 addresses separately in parallel.


Extending resolvers
-------------------

Both resolvers provided here can use alternate implementations of ``getaddrinfo``.
For example, say you have implemented an async function
``getaddrinfo_dns_over_https(server, host, port, *, family=0, type=0, proto=0, flags=0)``
that resolves host names over DoH.
You can then do:

.. code-block:: python

    from functools import partial
    getaddrinfo = partial(getaddrinfo_dns_over_https, server='https://cloudflare-dns.com/dns-query')
    doh_resolver = partial(async_stagger.resolvers.concurrent_resolver, getaddrinfo_async=getaddrinfo)
    reader, writer = await async_stagger.open_connection(host, port, resolver=doh_resolver)

to use Cloudflare's DoH server when making connections.

And of course, you can implement entirely new resolvers.
"""

import asyncio
import collections
import contextlib
import itertools
import socket
from collections.abc import AsyncIterator, Iterable, Iterator, Sequence

from . import exceptions
from .typing import AddrInfoType, HostType, PortType, AsyncGetAddrInfoType
from .debug import debug_log
from .constants import RESOLUTION_DELAY, FIRST_ADDRESS_FAMILY_COUNT


__all__ = [
    'basic_resolver',
    'concurrent_resolver',
]


_HAS_IPv6 = hasattr(socket, 'AF_INET6')


async def _getaddrinfo(
        host: HostType,
        port: PortType,
        *,
        family: int = socket.AF_UNSPEC,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
) -> list[AddrInfoType]:
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(host, port, family=family, type=type, proto=proto, flags=flags)


async def _getaddrinfo_raise_on_empty(
        host: HostType,
        port: PortType,
        *,
        family: int = socket.AF_UNSPEC,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
        getaddrinfo_async: AsyncGetAddrInfoType = _getaddrinfo,
) -> Sequence[AddrInfoType]:
    debug_log(
        'Resolving (%r, %r), family=%r, type=%r, proto=%r, flags=%r',
        host, port, family, type, proto, flags)
    addrinfos = await getaddrinfo_async(
        host, port, family=family, type=type, proto=proto, flags=flags)
    if not addrinfos:
        raise OSError(
            f'getaddrinfo({host!r}, {port!r}, family={family!r}, '
            f'type={type!r}, proto={proto!r}, flags={flags!r}) '
            f'returned empty list')
    debug_log(
        'Resolved (%r, %r), family=%r, type=%r, proto=%r, flags=%r: %r',
        host, port, family, type, proto, flags, addrinfos)
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


async def basic_resolver(
        host,
        port,
        *,
        family: int = socket.AF_UNSPEC,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
        first_addr_family_count: int = FIRST_ADDRESS_FAMILY_COUNT,
        getaddrinfo_async: AsyncGetAddrInfoType = _getaddrinfo,
) -> AsyncIterator[AddrInfoType]:
    """The basic resolver.

    Resolves all IP addresses in one call to *getaddrinfo_async*.
    The returned addresses are then interleaved by family.

    For arguments *host*, *port*, *family*, *type*, *proto*, *flags*,
    refer to :func:`socket.getaddrinfo`.

    Args:
        first_addr_family_count: "First Address Family Count" defined in :rfc:`8305`.
            i.e. the reordered list will have this many addresses for the
            first address family,
            and the rest will be interleaved one to one.
        getaddrinfo_async: the async ``getaddrinfo`` implementation that's used
            to actually resolve the host.
    """
    addrinfos = await _getaddrinfo_raise_on_empty(
        host, port, family=family, type=type, proto=proto, flags=flags,
        getaddrinfo_async=getaddrinfo_async,
    )
    addrinfos = _interleave_addrinfos(addrinfos, first_addr_family_count)
    # it would be nice if "yield from addrinfos" worked, but alas,
    # https://www.python.org/dev/peps/pep-0525/#asynchronous-yield-from
    for ai in addrinfos:
        yield ai


def concurrent_resolver(
        host: HostType,
        port: PortType,
        *,
        family: int = socket.AF_UNSPEC,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
        resolution_delay: float = RESOLUTION_DELAY,
        first_addr_family_count: int = FIRST_ADDRESS_FAMILY_COUNT,
        raise_exc_group: bool = False,
        getaddrinfo_async: AsyncGetAddrInfoType = _getaddrinfo,
) -> AsyncIterator[AddrInfoType]:
    """The concurrent resolver.

    When ``family == socket.AF_UNSPEC``, two calls to *getaddrinfo_async* are
    run in parallel, one for IPv6 and one for IPv4.
    Addresses are yielded once either run returns with addresses.

    When ``family != socket.AF_UNSPEC``, the call is dispatched to :func:`basic_resolver`.

    For arguments *host*, *port*, *family*, *type*, *proto*, *flags*,
    refer to :func:`socket.getaddrinfo`.

    Args:
        resolution_delay: Amount of time to wait for IPv6 addresses to resolve
            if IPv4 addresses are resolved first. This is the "Resolution
            Delay" as defined in :rfc:`8305`.
        first_addr_family_count: "First Address Family Count" defined in :rfc:`8305`.
            i.e. the reordered list will have this many addresses for the
            first address family,
            and the rest will be interleaved one to one.
        raise_exc_group: If set to ``True``, when both IPv6 and IPv4 resolutions
            fail, raise a :class:`ExceptionGroup` containing both exceptions.
            If set to ``False``, raise a :class:`socket.gaierror` whose message
            contains ``str`` representations of both exceptions.
        getaddrinfo_async: the async ``getaddrinfo`` implementation that's used
            to actually resolve the host.
    """
    if _HAS_IPv6 and family == socket.AF_UNSPEC:
        return _async_concurrent_resolver(
            host, port, type=type, proto=proto, flags=flags,
            resolution_delay=resolution_delay,
            first_addr_family_count=first_addr_family_count,
            raise_exc_group=raise_exc_group,
            getaddrinfo_async=getaddrinfo_async,
        )
    else:
        return basic_resolver(
            host, port, family=family, type=type, proto=proto, flags=flags,
            first_addr_family_count=first_addr_family_count,
            getaddrinfo_async=getaddrinfo_async,
        )


async def _async_concurrent_resolver(
        host,
        port,
        *,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
        resolution_delay: float,
        first_addr_family_count: int,
        raise_exc_group: bool,
        getaddrinfo_async: AsyncGetAddrInfoType,
) -> AsyncIterator[AddrInfoType]:
    debug_log('Async resolving (%r, %r), type=%r, proto=%r, flags=%r',
              host, port, type, proto, flags)
    bell = asyncio.Event()
    addrinfos = []
    next_yield_idx = 0
    v4_exception = v6_exception = None

    async def v6_resolve():
        try:
            v6_addrinfos = await _getaddrinfo_raise_on_empty(
                host,
                port,
                family=socket.AF_INET6,
                type=type,
                proto=proto,
                flags=flags,
                getaddrinfo_async=getaddrinfo_async,
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

    async def v4_resolve():
        try:
            v4_addrinfos = await _getaddrinfo_raise_on_empty(
                host,
                port,
                family=socket.AF_INET,
                type=type,
                proto=proto,
                flags=flags,
                getaddrinfo_async=getaddrinfo_async,
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

    async with asyncio.TaskGroup() as group:
        v6_task = group.create_task(v6_resolve())
        v4_task = group.create_task(v4_resolve())

        while True:
            if len(addrinfos) > next_yield_idx:
                next_yield_value = addrinfos[next_yield_idx]
                next_yield_idx += 1
                try:
                    yield next_yield_value
                except GeneratorExit:
                    # If unhandled, this GeneratorExit ends up wrapped in an BaseExceptionGroup,
                    # and triggers a "Task exception was never retrieved" message.
                    # We could get cancellation for free if we don't handle it here and
                    # do `except* GeneratorExit` outside the TaskGroup, but then it becomes
                    # more awkward to return since we can't `return` within `except*`.
                    v6_task.cancel()
                    v4_task.cancel()
                    return
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
