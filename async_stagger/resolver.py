"""Code related to resolving host names to IP addresses.

A resolver is a callable with signature
*resolver(host, port, *, family=0, type=0, proto=0, flags=0)*
(and more optional arguments if necessary)
that returns an async iterable of 5-tuples
*(family, type, proto, canonname, sockaddr)*.
They are intended to be used by :func:`happy_eyeballs.create_connected_sock`,
and to be more or less interchangeable.
"""

import asyncio
import collections
import itertools
import socket
from typing import AsyncIterator, Tuple, Iterable, List, Optional, Iterator

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
        loop: asyncio.AbstractEventLoop = None,
) -> List[AddrInfoType]:
    # DRY at work.
    loop = loop or asyncio.get_event_loop()
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


def _ipaddr_info(
        host: HostType,
        port: PortType,
        family: int,
        type_: int,
        proto: int,
) -> Optional[AddrInfoType]:
    # This function is copied from asyncio/base_events.py with minimal
    # modifications.

    # Try to skip getaddrinfo if "host" is already an IP. Users might have
    # handled name resolution in their own code and pass in resolved IPs.
    if not hasattr(socket, 'inet_pton'):
        return

    if proto not in {0, socket.IPPROTO_TCP, socket.IPPROTO_UDP} or \
            host is None:
        return None

    if type_ == socket.SOCK_STREAM:
        # Linux only:
        #    getaddrinfo() can raise when socket.type is a bit mask.
        #    So if socket.type is a bit mask of SOCK_STREAM, and say
        #    SOCK_NONBLOCK, we simply return None, which will trigger
        #    a call to getaddrinfo() letting it process this request.
        proto = socket.IPPROTO_TCP
    elif type_ == socket.SOCK_DGRAM:
        proto = socket.IPPROTO_UDP
    else:
        return None

    if port is None:
        port = 0
    elif isinstance(port, bytes) and port == b'':
        port = 0
    elif isinstance(port, str) and port == '':
        port = 0
    else:
        # If port's a service name like "http", don't skip getaddrinfo.
        try:
            port = int(port)
        except (TypeError, ValueError):
            return None

    if family == socket.AF_UNSPEC:
        afs = [socket.AF_INET]
        if _HAS_IPv6:
            afs.append(socket.AF_INET6)
    else:
        afs = [family]

    if isinstance(host, bytes):
        host = host.decode('idna')
    if '%' in host:
        # Linux's inet_pton doesn't accept an IPv6 zone index after host,
        # like '::1%lo0'.
        return None

    for af in afs:
        try:
            socket.inet_pton(af, host)
            # The host has already been resolved.
            if _HAS_IPv6 and af == socket.AF_INET6:
                return af, type_, proto, '', (host, port, 0, 0)
            else:
                return af, type_, proto, '', (host, port)
        except OSError:
            pass

    # "host" is not an IP address.
    return None


async def _ensure_resolved(
        address: Tuple,
        *,
        family: int = socket.AF_UNSPEC,
        type_: int = 0,
        proto: int = 0,
        flags: int = 0,
        loop: asyncio.AbstractEventLoop = None,
) -> List[AddrInfoType]:
    # This function is adapted from asyncio/base_events.py.
    loop = loop or asyncio.get_event_loop()
    host, port = address[:2]
    info = _ipaddr_info(host, port, family, type_, proto)
    if info is not None:
        # "host" is already a resolved IP.
        return [info]
    else:
        return await _getaddrinfo_raise_on_empty(
            host, port, family=family, type_=type_,
            proto=proto, flags=flags, loop=loop)


def _roundrobin(*iters: Iterable) -> Iterator:
    # Note: iters should not contain None
    return (a for a in itertools.chain.from_iterable(
                itertools.zip_longest(*iters)
            ) if a is not None)


def _interleave_addrinfos(
        addrinfos: Iterable[AddrInfoType],
        first_address_family_count: int,
) -> List[AddrInfoType]:
    """Interleave list of addrinfo tuples by family."""
    # Group addresses by family
    addrinfos_by_family = collections.OrderedDict()
    for addr in addrinfos:
        family = addr[0]
        if family not in addrinfos_by_family:
            addrinfos_by_family[family] = []
        addrinfos_by_family[family].append(addr)
    addrinfos_lists = list(addrinfos_by_family.values())

    reordered = []
    if first_address_family_count > 1:
        reordered.extend(addrinfos_lists[0][:first_address_family_count - 1])
        del addrinfos_lists[0][:first_address_family_count - 1]
    reordered.extend(_roundrobin(*addrinfos_lists))
    return reordered


async def builtin_resolver(
        host,
        port,
        *,
        family: int = socket.AF_UNSPEC,
        type_: int = 0,
        proto: int = 0,
        flags: int = 0,
        first_addr_family_count: int = FIRST_ADDRESS_FAMILY_COUNT,
        loop: asyncio.AbstractEventLoop = None,
) -> AsyncIterator[AddrInfoType]:
    """Resolver using built-in getaddrinfo().

    Interleaves addresses by family if required, and yield results as an
    async iterable. Nothing spectacular.
    """
    loop = loop or asyncio.get_event_loop()
    addrinfos = await _ensure_resolved(
        (host, port), family=family, type_=type_,
        proto=proto, flags=flags, loop=loop)
    addrinfos = _interleave_addrinfos(addrinfos, first_addr_family_count)
    # it would be nice if "yield from addrinfos" worked, but alas,
    # https://www.python.org/dev/peps/pep-0525/#asynchronous-yield-from
    for ai in addrinfos:
        yield ai


async def ensure_multiple_addrs_resolved(
        addresses: List[Tuple],
        family: int = socket.AF_UNSPEC,
        type_: int = 0,
        proto: int = 0,
        flags: int = 0,
        loop: asyncio.AbstractEventLoop = None,
) -> AsyncIterator[AddrInfoType]:
    """Ensure all addresses in *addresses* are resolved.

    This is for resolving multiple local bind addresses. All addresses are
    resolved before yielding any of them, in case some of them raise
    exceptions when resolving.
    """
    loop = loop or asyncio.get_event_loop()
    results = await asyncio.gather(*(
        _ensure_resolved(
            addr, family=family, type_=type_, proto=proto,
            flags=flags, loop=loop
        )
        for addr in addresses
    ))
    for addrinfo in itertools.chain.from_iterable(results):
        yield addrinfo


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
        loop: asyncio.AbstractEventLoop = None,
) -> AsyncIterator[AddrInfoType]:
    """Dispatcher function for async resolver.

    Returns builtin_resolver(...) if family != socket.AF_UNSPEC.
    """
    if _HAS_IPv6 and family == socket.AF_UNSPEC:
        return _async_builtin_resolver(
            host, port, type_=type_, proto=proto, flags=flags,
            resolution_delay=resolution_delay,
            first_addr_family_count=first_addr_family_count, loop=loop)
    else:
        return builtin_resolver(
            host, port, family=family, type_=type_, proto=proto, flags=flags,
            first_addr_family_count=first_addr_family_count, loop=loop)


async def _async_builtin_resolver(
        host,
        port,
        *,
        type_: int = 0,
        proto: int = 0,
        flags: int = 0,
        resolution_delay: float = RESOLUTION_DELAY,
        first_addr_family_count: int = FIRST_ADDRESS_FAMILY_COUNT,
        loop: asyncio.AbstractEventLoop = None,
) -> AsyncIterator[AddrInfoType]:
    """Asynchronous resolver using built-in getaddrinfo().

    "Asynchronous" means that IPv6 and IPv4 resolutions are done separately
    in parallel, and addresses can be yielded as soon as either address family
    finished resolving. The behavior is detailed in :rfc:`8305#section-3`.
    """
    loop = loop or asyncio.get_event_loop()
    debug_log('Async resolving (%r, %r), type=%r, proto=%r, flags=%r',
              host, port, type_, proto, flags)

    # Determine whether host is an IP address literal
    addrinfo = _ipaddr_info(host, port, socket.AF_UNSPEC, type_, proto)
    if addrinfo is not None:
        yield addrinfo
        return

    # These two deques will be changed by the resolve tasks, assume they will
    # change during any "await"
    v6_infos = collections.deque()
    v4_infos = collections.deque()

    async def resolve_ipv6():
        v6_infos.extend(await _getaddrinfo_raise_on_empty(
            host, port, family=socket.AF_INET6,
            type_=type_, proto=proto, flags=flags, loop=loop))

    v6_resolve_task = loop.create_task(resolve_ipv6())

    async def resolve_ipv4():
        infos = await _getaddrinfo_raise_on_empty(
            host, port, family=socket.AF_INET,
            type_=type_, proto=proto, flags=flags, loop=loop)
        if not v6_resolve_task.done():
            await asyncio.wait((v6_resolve_task,), timeout=resolution_delay)
        v4_infos.extend(infos)

    v4_resolve_task = loop.create_task(resolve_ipv4())
    pending = {v6_resolve_task, v4_resolve_task}

    extra_v6_addrs_to_yield = first_addr_family_count - 1
    next_should_yield_v6 = True
    has_yielded = False

    try:
        while True:
            # If there's nothing to yield:
            if not v6_infos and not v4_infos:
                if not pending:
                    break
                # Resolve tasks are not done, wait for one and try again
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED)
                # "Consume" any exception
                for d in done:
                    exc = d.exception()
                    if exc:
                        debug_log('Resolution task %r raised exception: %r',
                                  d, exc)
                continue
            # There's something to yield
            if extra_v6_addrs_to_yield > 0:
                # Always try to yield IPv6 address if available
                assert next_should_yield_v6
                if v6_infos:
                    yield v6_infos.popleft()
                    extra_v6_addrs_to_yield -= 1
                else:
                    yield v4_infos.popleft()
            else:
                # Alternate between IPv6 and IPv4
                if ((next_should_yield_v6 and v6_infos)
                        or (not next_should_yield_v6 and not v4_infos)):
                    yield v6_infos.popleft()
                    next_should_yield_v6 = False
                else:
                    yield v4_infos.popleft()
                    next_should_yield_v6 = True
            has_yielded = True

        assert v6_resolve_task.done()
        assert v4_resolve_task.done()
        if has_yielded:
            return

        raise OSError(
            f'Address resolution failed, '
            f'IPv6: <{v6_resolve_task.exception()!r}>, '
            f'IPv4: <{v4_resolve_task.exception()!r}>')
    finally:
        # Clean up any remaining tasks and consume their exceptions
        if pending:
            for p in pending:
                p.cancel()
            done, pending = await asyncio.wait(pending)
            assert not pending
            for d in done:
                exc = d.exception()
                if exc:
                    debug_log('Resolution task %r raised exception: %r',
                              d, exc)
        debug_log('Async resolution (%r, %r), type=%r, proto=%r, flags=%r '
                  'finalized', host, port, type_, proto, flags)
