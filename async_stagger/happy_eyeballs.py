import asyncio
import socket
from collections import OrderedDict
from functools import partial
from itertools import cycle, islice, product
from typing import Callable, Union, Tuple, Optional, Iterable

from .stagger import staggered_race

__all__ = ['create_connected_sock', 'create_connection', 'open_connection']

_DEFAULT_DELAY = 0.3
_DEFAULT_LIMIT = 2 ** 16

_HAS_IPv6 = hasattr(socket, 'AF_INET6')


def _ipaddr_info(host, port, family, type_, proto):
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
                return af, type, proto, '', (host, port, 0, 0)
            else:
                return af, type, proto, '', (host, port)
        except OSError:
            pass

    # "host" is not an IP address.
    return None


async def _ensure_resolved(address, *, family=0, type_=socket.SOCK_STREAM,
                           proto=0, flags=0, loop=None):
    # This function is copied from asyncio/base_events.py and made into a
    # native coroutine.
    loop = loop or asyncio.get_event_loop()
    host, port = address[:2]
    info = _ipaddr_info(host, port, family, type_, proto)
    if info is not None:
        # "host" is already a resolved IP.
        return [info]
    else:
        return await loop.getaddrinfo(host, port, family=family, type=type_,
                                      proto=proto, flags=flags)


async def _connect_sock(addr_info, local_addr_info=None, *, loop=None):
    """Create, bind and connect one socket."""
    loop = loop or asyncio.get_event_loop()
    family, type_, proto, _, address = addr_info
    sock = socket.socket(family=family, type=type_, proto=proto)
    try:
        sock.setblocking(False)
        if local_addr_info is not None:
            laddr = local_addr_info[4]
            try:
                sock.bind(laddr)
            except OSError as e:
                raise OSError(
                    e.errno,
                    f'error while attempting to bind on address {laddr!r}: '
                    f'{e.strerror.lower()}')
        await loop.sock_connect(sock, address)
        return sock
    except:
        sock.close()
        raise


def roundrobin(*iterables):
    """roundrobin('ABC', 'D', 'EF') --> A D E B F C"""
    # Copied from Python docs, Recipe credited to George Sakkis
    pending = len(iterables)
    nexts = cycle(iter(it).__next__ for it in iterables)
    while pending:
        try:
            for next in nexts:
                yield next()
        except StopIteration:
            pending -= 1
            nexts = cycle(islice(nexts, pending))


def _interleave_addrinfos(addrinfos, first_address_family_count=1):
    """Interleave list of addrinfo tuples by family."""
    # Group addresses by family
    addrinfos_by_family = OrderedDict()
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
    reordered.extend(roundrobin(*addrinfos_lists))
    return reordered


async def create_connected_sock(
        host: Union[str, bytes, None],
        port: Union[str, bytes, int, None],
        *,
        family: int = 0,
        proto: int = 0,
        flags: int = 0,
        local_addr: Optional[Tuple] = None,
        local_addrs: Optional[Iterable[Tuple]] = None,
        delay: Optional[float] = _DEFAULT_DELAY,
        interleave: int = 1,
        loop: Optional[asyncio.AbstractEventLoop] = None,
) -> socket.socket:
    """Connect to (host, port) and return a connected socket.

    This function implements RFC6555 Happy Eyeballs and some features of
    RFC8305 Happy Eyeballs v2. When a host name resolves to multiple IP
    addresses, connection attempts are made in parallel with staggered start
    times, and the one completing fastest is used. The resolved addresses can
    be interleaved by address family, so even if network connectivity for one
    address family is broken (when IPv6 fails, for example), connections
    still complete quickly.

    (Some fancier features specified in RFC8305, like asynchronous DNS
    queries, statefulness, and features related to NAT64 and DNS64 are not
    implemented. Destination address sorting is left for the operating
    system; it is assumed that the addresses returned by ``getaddrinfo()`` is
    already sorted according to OS's preferences.)

    Most of the arguments should be familiar from the various ``socket`` and
    ``asyncio`` methods.
    *delay* and *interleave* control Happy Eyeballs-specific behavior.
    *local_addrs* is a new argument providing new features not specific to
    Happy Eyeballs.

    Args:
        host: Host name to connect to. Unlike ``asyncio.create_connection()``
            there is no default, but it's still possible to manually specify
            *None* here.

        port: Port number to connect to. Similar to **host**, *None* can be
            specified here as well.

        family: Address family. Specify ``socket.AF_INET`` or ``AF_INET6`` here
            to limit the type of addresses used. See documentation on the
            ``socket`` module for details.

        proto: Socket protocol. Since the socket type is always ``SOCK_STREAM``,
            proto can usually be left unspecified.

        flags: Flags passed to ``getaddrinfo``. See documentation on
            ``socket.getaddrinfo()`` for details.

        local_addr: (local_host, local_port) tuple used to bind the socket to
            locally. The *local_host* and *local_port* are looked up using
            getaddrinfo() if necessary, similarly to *host* and *port*.

        local_addrs: An iterable of (local_host, local_port) tuples, all of
            which are candidates for locally binding the socket to. This allows
            e.g. providing one IPv4 and one IPv6 address. Addresses are looked
            up using getaddrinfo() if necessary.

        delay: Amount of time to wait before making connections to different
            addresses. This is the "Connect Attempt Delay" as defined in
            RFC8305.

        interleave: Whether to interleave addresses returned by
            ``getaddrinfo()`` by address family. 0 means not to interleave and
            simply use the returned order. An integer >= 1 is interpreted as
            "First Address Family Count" defined in RFC8305, i.e. the reordered
            list will have this many addresses for the first address family,
            and the rest will be interleaved one to one.

        loop: Event loop to use.

    Returns:
        The connected ``socket.socket`` object.
    """
    loop = loop or asyncio.get_event_loop()

    if local_addr is not None and local_addrs is not None:
        raise ValueError(
            'local_addr and local_addrs cannot be specified at the same time')

    remote_addrinfos_task = loop.create_task(_ensure_resolved(
        (host, port), family=family, type_=socket.SOCK_STREAM, proto=proto,
        flags=flags, loop=loop))
    if local_addrs is None and local_addr is not None:
        local_addrs = [local_addr]
    if local_addrs is not None:
        local_resolve_tasks = [loop.create_task(_ensure_resolved(
            la, family=family, type_=socket.SOCK_STREAM, proto=proto,
            flags=flags, loop=loop)) for la in local_addrs]
    else:
        local_resolve_tasks = []

    # Use gather() instead of wait() to make sure cancellation propagates in
    await asyncio.gather(remote_addrinfos_task, *local_resolve_tasks, loop=loop)

    addrinfos = remote_addrinfos_task.result()
    if not addrinfos:
        raise OSError('getaddrinfo() returned empty list')
    if local_resolve_tasks:
        local_addrinfos = [lai
                           for t in local_resolve_tasks
                           for lai in t.result()]
        if not local_addrinfos:
            raise OSError('getaddrinfo() returned empty list')
    else:
        local_addrinfos = [None]

    if interleave:
        addrinfos = _interleave_addrinfos(addrinfos, interleave)

    # Use a separate task for each (remote_addr, local_addr) pair. When
    # multiple local addresses are specified, this depends on the OS quickly
    # failing address combinations that don't work (e.g. an IPv6 remote
    # address with an IPv4 local address). If your OS can't figure that out,
    # it's probably time to get a better OS.
    winner_socket, _, exceptions = await staggered_race(
        (partial(_connect_sock, ai, lai, loop=loop)
         for ai, lai in product(addrinfos, local_addrinfos)),
        delay,
        loop=loop)
    if winner_socket:
        return winner_socket
    if len(exceptions) == 1:
        raise exceptions[0]
    else:
        # If they all have the same str(), raise one.
        model = str(exceptions[0])
        if all(str(exc) == model for exc in exceptions):
            raise exceptions[0]
        # Raise a combined exception so the user can see all
        # the various error messages.
        raise OSError('Multiple exceptions: {}'.format(
            ', '.join(str(exc) for exc in exceptions)))


async def create_connection(
        protocol_factory: Callable[[], asyncio.Protocol],
        host: Union[str, bytes, None],
        port: Union[str, bytes, int, None],
        *,
        ssl=None,
        family: int = 0,
        proto: int = 0,
        flags: int = 0,
        local_addr: Optional[Tuple] = None,
        local_addrs: Optional[Iterable[Tuple]] = None,
        server_hostname=None,
        ssl_handshake_timeout=None,
        delay: Optional[float] = _DEFAULT_DELAY,
        interleave: int = 1,
        loop: Optional[asyncio.AbstractEventLoop] = None,
) -> Tuple[asyncio.Transport, asyncio.Protocol]:
    """Connect to (host, port) and return (transport, protocol).

    This function does the same thing as ``loop.create_connection``, only
    more awesome with Happy Eyeballs. Refer to that function's documentation for
    explanations of these arguments: *protocol_factory*, *ssl*, and
    *server_hostname*. Refer to :func:`async_stagger.create_connected_sock`
    for all other arguments.

    Returns:
        *(transport, protocol)*, the same as ``loop.create_connection``.
    """
    loop = loop or asyncio.get_event_loop()
    # These checks are copied from BaseEventLoop.create_connection()
    if server_hostname is not None and not ssl:
        raise ValueError('server_hostname is only meaningful with ssl')
    if server_hostname is None and ssl:
        server_hostname = host
    if ssl_handshake_timeout is not None and not ssl:
        raise ValueError('ssl_handshake_timeout is only meaningful with ssl')

    sock = await create_connected_sock(
        host, port, family=family, proto=proto, flags=flags,
        local_addr=local_addr, local_addrs=local_addrs,
        delay=delay, interleave=interleave, loop=loop)

    try:
        # Defer to the event loop to create transport and protocol
        return await loop.create_connection(
            protocol_factory, ssl=ssl, sock=sock,
            server_hostname=server_hostname)
    except:
        sock.close()
        raise


async def open_connection(
        host: Union[str, bytes, None],
        port: Union[str, bytes, int, None],
        *,
        limit: int = _DEFAULT_LIMIT,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect to (host, port) and return (reader, writer).

    This function does the same thing as ``asyncio.open_connection``, with
    added awesomeness of Happy Eyeballs. Refer to the documentation of that
    function for what *limit* does, and refer to
    :func:`async_stagger.create_connection` for everything else.

    Returns:
        *(reader, writer)*, the same as ``asyncio.open_connection``.
    """
    loop = loop or asyncio.get_event_loop()
    reader = asyncio.StreamReader(limit=limit, loop=loop)
    protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
    transport, _ = await create_connection(
        lambda: protocol, host, port, loop=loop, **kwargs)
    writer = asyncio.StreamWriter(transport, protocol, reader, loop)
    return reader, writer
