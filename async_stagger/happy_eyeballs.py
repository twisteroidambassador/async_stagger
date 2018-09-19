import asyncio
import socket
from functools import partial
from typing import Callable, Tuple, Optional, Iterable

from . import aitertools
from . import resolver
from .stagger import staggered_race
from .debug import debug_log
from .typing import AddrInfoType, HostType, PortType
from .constants import (
    CONNECT_DELAY, FIRST_ADDRESS_FAMILY_COUNT, RESOLUTION_DELAY)

__all__ = [
    'create_connected_sock',
    'create_connection',
    'open_connection',
    'HappyEyeballsConnectError',
]


class HappyEyeballsConnectError(Exception):
    """Encapsulate all exceptions encountered during connection.

    This exception is raised when :func:`~async_stagger.create_connected_sock`
    fails with the *detailed_exceptions* argument set. The *args* of this
    exception consists of a list of
    *(remote_addrinfo, local_addrinfo, exception)* tuples, where each tuple
    represents the result of one connection attempt.
    """
    pass


async def _connect_sock(
        addr_info: AddrInfoType,
        local_addr_info: AddrInfoType = None,
        *,
        loop: asyncio.AbstractEventLoop = None
) -> socket.socket:
    """Create, bind and connect one socket."""
    debug_log('Creating socket with remote addrinfo %r, local addrinfo %r',
              addr_info, local_addr_info)
    loop = loop or asyncio.get_event_loop()
    family, type_, proto, _, address = addr_info
    try:
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
                        f'{e.strerror.lower()}',
                        *e.args[2:])
            await loop.sock_connect(sock, address)
            debug_log(
                'Socket %r successfully connected for remote addrinfo %r, '
                'local addrinfo %r',
                sock, addr_info, local_addr_info)
            return sock
        except:
            sock.close()
            raise
    except Exception as e:
        debug_log(
            'Creating socket with remote addrinfo %r, local addrinfo %r '
            'failed with exception %r',
            addr_info, local_addr_info, e)
        raise


async def create_connected_sock(
        host: HostType,
        port: PortType,
        *,
        family: int = socket.AF_UNSPEC,
        proto: int = 0,
        flags: int = 0,
        local_addr: Tuple = None,
        local_addrs: Iterable[Tuple] = None,
        delay: Optional[float] = CONNECT_DELAY,
        interleave: int = FIRST_ADDRESS_FAMILY_COUNT,
        async_dns: bool = False,
        resolution_delay: float = RESOLUTION_DELAY,
        detailed_exceptions: bool = False,
        loop: asyncio.AbstractEventLoop = None,
) -> socket.socket:
    """Connect to *(host, port)* and return a connected socket.

    This function implements :rfc:`6555` Happy Eyeballs and some features of
    :rfc:`8305` Happy Eyeballs v2. When a host name resolves to multiple IP
    addresses, connection attempts are made in parallel with staggered start
    times, and the one completing fastest is used. The resolved addresses can
    be interleaved by address family, so even if network connectivity for one
    address family is broken (when IPv6 fails, for example), connections
    still complete quickly. IPv6 and IPv4 addresses of a hostname can also
    be resolved in parallel.

    (Some fancier features specified in :rfc:`8305`, like
    statefulness and features related to NAT64 and DNS64 are not
    implemented. Destination address sorting is left for the operating
    system; it is assumed that the addresses returned by
    :func:`~asyncio.AbstractEventLoop.getaddrinfo` is already sorted
    according to OS's preferences.)

    Most of the arguments should be familiar from the various :mod:`socket` and
    :mod:`asyncio` methods.
    *delay*, *interleave*, *async_dns* and *resolution_delay*
    control Happy Eyeballs-specific behavior.
    *local_addrs* is a new argument providing new features not specific to
    Happy Eyeballs.

    Args:
        host: Host name to connect to. Unlike
            :func:`asyncio.create_connection`
            there is no default, but it's still possible to manually specify
            *None* here.

        port: Port number to connect to. Similar to **host**, *None* can be
            specified here as well.

        family: Address family.
            Specify :data:`socket.AF_INET` or :data:`socket.AF_INET6` here
            to limit the type of addresses used. See documentation on the
            :mod:`socket` module for details.

        proto: Socket protocol. Since the socket type is always
            :data:`socket.SOCK_STREAM`, proto can usually be left unspecified.

        flags: Flags passed to :func:`~asyncio.AbstractEventLoop.getaddrinfo`.
            See documentation on :func:`socket.getaddrinfo` for details.

        local_addr: *(local_host, local_port)* tuple used to bind the socket to
            locally. The *local_host* and *local_port* are looked up using
            :func:`~asyncio.AbstractEventLoop.getaddrinfo` if necessary,
            similar to *host* and *port*.

        local_addrs: An iterable of (local_host, local_port) tuples, all of
            which are candidates for locally binding the socket to. This allows
            e.g. providing one IPv4 and one IPv6 address. Addresses are looked
            up using :func:`~asyncio.AbstractEventLoop.getaddrinfo`
            if necessary.

        delay: Amount of time to wait before making connections to different
            addresses. This is the "Connect Attempt Delay" as defined in
            :rfc:`8305`.

        interleave: Whether to interleave resolved addresses by address family.
            0 means not to interleave and simply use the returned order.
            An integer >= 1 is interpreted as
            "First Address Family Count" defined in :rfc:`8305`,
            i.e. the reordered list will have this many addresses for the
            first address family,
            and the rest will be interleaved one to one.

        async_dns: Do asynchronous DNS resolution, where IPv6 and IPv4
            addresses are resolved in parallel, and connection attempts can
            be made as soon as either address family is resolved. This behavior
            is described in :rfc:`8305#section-3`.

        resolution_delay: Amount of time to wait for IPv6 addresses to resolve
            if IPv4 addresses are resolved first. This is the "Resolution
            Delay" as defined in :rfc:`8305`.

        detailed_exceptions: Determines what exception to raise when all
            connection attempts fail. If set to True, an instance of
            :class:`~async_stagger.HappyEyeballsConnectError` is raised, which
            contains the individual exceptions raised by each connection
            attempt.
            When set to false (default), an exception is raised the same
            way as :func:`asyncio.create_connection`: if all the connection
            attempt exceptions have the same ``str``, one of them is raised,
            otherwise an instance of *OSError* is raised whose message contains
            ``str`` representations of all connection attempt exceptions.

        loop: Event loop to use.

    Returns:
        The connected :class:`socket.socket` object.


    .. versionadded:: v0.1.3
       the *local_addrs* parameter.

    .. versionadded:: v0.2.1
       the *async_dns* and *resolution_delay* parameters.
    """
    loop = loop or asyncio.get_event_loop()

    if local_addr is not None:
        if local_addrs is not None:
            raise ValueError('local_addr and local_addrs cannot be specified '
                             'at the same time')
        local_addrs = [local_addr]

    debug_log('Starting Happy Eyeballs connection to (%r, %r), '
              'local addresses %r',
              host, port, local_addrs)

    if not async_dns:
        remote_addrinfo_aiter = resolver.builtin_resolver(
            host, port, family=family, type_=socket.SOCK_STREAM, proto=proto,
            flags=flags, first_addr_family_count=interleave, loop=loop)
    else:
        remote_addrinfo_aiter = resolver.async_builtin_resolver(
            host, port, family=family, type_=socket.SOCK_STREAM, proto=proto,
            flags=flags, resolution_delay=resolution_delay,
            first_addr_family_count=interleave, loop=loop)

    if local_addrs is not None:
        local_addrinfo_aiter = resolver.ensure_multiple_addrs_resolved(
            local_addrs, family=family, type_=socket.SOCK_STREAM,
            proto=proto, flags=flags, loop=loop)
    else:
        local_addrinfo_aiter = aitertools.aiter_from_iter((None,))

    connections = []

    async def connect_tasks():
        async for ai, lai in aitertools.product(
            remote_addrinfo_aiter, local_addrinfo_aiter
        ):
            connections.append((ai, lai))
            yield partial(_connect_sock, ai, lai, loop=loop)

    # Use a separate task for each (remote_addr, local_addr) pair. When
    # multiple local addresses are specified, this depends on the OS quickly
    # failing address combinations that don't work (e.g. an IPv6 remote
    # address with an IPv4 local address). Come to think of it, since the
    # family of the socket is determined by the remote address, if the remote
    # and local addresses have different family, binding local address should
    # raise an exception. If your OS can't figure that out,
    # it's probably time to get a better OS.
    winner_socket, _, exceptions = await staggered_race(
        connect_tasks(), delay, loop=loop)
    assert len(connections) == len(exceptions)

    if winner_socket:
        debug_log('Starting Happy Eyeballs connection to (%r, %r) '
                  'from %r succeeded, connected socket %r',
                  host, port, local_addrs, winner_socket)
        return winner_socket

    debug_log('Happy eyeballs connection to (%r, %r) from %r failed',
              host, port)
    if not detailed_exceptions:
        # Raise one exception like loop.create_connection
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
    else:
        raise HappyEyeballsConnectError(
            list((*c, e) for c, e in zip(connections, exceptions)))


create_connected_sock_kwds = tuple(
    create_connected_sock.__kwdefaults__.keys())


async def create_connection(
        protocol_factory: Callable[[], asyncio.Protocol],
        host: HostType,
        port: PortType,
        *,
        loop: asyncio.AbstractEventLoop = None,
        **kwargs,
) -> Tuple[asyncio.Transport, asyncio.Protocol]:
    """Connect to *(host, port)* and return *(transport, protocol)*.

    This function does the same thing as
    :meth:`asyncio.AbstractEventLoop.create_connection`,
    only more awesome with Happy Eyeballs.
    Refer to that function's documentation for
    explanations of these arguments: *protocol_factory*, *ssl*, and
    *server_hostname*. Refer to :func:`~async_stagger.create_connected_sock`
    for all other arguments.

    Returns:
        *(transport, protocol)*, the same as
        :meth:`asyncio.AbstractEventLoop.create_connection`.
    """
    loop = loop or asyncio.get_event_loop()
    # To avoid the trouble of synchronizing this function's argument list
    # to create_connected_sock, the keyword arguments meant for
    # create_connected_sock are extracted dynamically.
    create_connected_sock_kwargs = dict(
        (arg, kwargs.pop(arg)) for arg in create_connected_sock_kwds
        if arg in kwargs
    )
    # The remaining keyword arguments are sent to loop.create_connection.
    # This way, this function stays compatible with different versions of
    # Python even if new keyword arguments are added to loop.create_connection.
    # In unfortunate cases where invalid keyword arguments are passed, the
    # socket object will be created first, then the call to
    # loop.create_connection will fail.

    sock = await create_connected_sock(
        host, port, loop=loop, **create_connected_sock_kwargs)

    try:
        # Defer to the event loop to create transport and protocol
        return await loop.create_connection(
            protocol_factory, sock=sock, **kwargs)
    except:
        sock.close()
        raise


async def open_connection(
        host: HostType,
        port: PortType,
        *,
        loop: asyncio.AbstractEventLoop = None,
        **kwargs,
) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect to (host, port) and return (reader, writer).

    This function does the same thing as :func:`asyncio.open_connection`, with
    added awesomeness of Happy Eyeballs. Refer to the documentation of that
    function for what *limit* does, and refer to
    :func:`~async_stagger.create_connection` and
    :func:`~async_stagger.create_connected_sock` for everything else.

    Returns:
        *(reader, writer)*, the same as :func:`asyncio.open_connection`.
    """
    loop = loop or asyncio.get_event_loop()
    # Some gymnastics so I do not have to maintain a copy of the default value
    # for the keyword argument 'limit' for asyncio.open_connection and
    # asyncio.StreamReader
    stream_reader_kwargs = {'loop': loop}
    if 'limit' in kwargs:
        stream_reader_kwargs['limit'] = kwargs.pop('limit')
    reader = asyncio.StreamReader(**stream_reader_kwargs)
    protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
    transport, _ = await create_connection(
        lambda: protocol, host, port, loop=loop, **kwargs)
    writer = asyncio.StreamWriter(transport, protocol, reader, loop)
    return reader, writer
