import asyncio
import socket
from functools import partial
from typing import Callable, Optional, Iterable, AsyncIterable

from . import exceptions
from . import aitertools
from . import resolvers
from .stagger import staggered_race
from .debug import debug_log
from .typing import AddrInfoType, HostType, PortType, ResolverType
from .constants import CONNECT_DELAY

__all__ = [
    'create_connected_sock',
    'create_connection',
    'open_connection',
]


async def _connect_sock(
        addr_info: AddrInfoType,
        local_addr: tuple = None,
) -> socket.socket:
    """Create, bind and connect one socket."""
    debug_log('Creating socket with remote addrinfo %r, local addr %r',
              addr_info, local_addr)
    loop = asyncio.get_running_loop()
    family, type_, proto, _, address = addr_info
    try:
        sock = socket.socket(family=family, type=type_, proto=proto)
        try:
            sock.setblocking(False)
            if local_addr is not None:
                try:
                    sock.bind(local_addr)
                except OSError as e:
                    raise OSError(
                        e.errno,
                        f'error while attempting to bind on address {local_addr!r}: '
                        f'{e.strerror.lower()}',
                        *e.args[2:])
            await loop.sock_connect(sock, address)
            debug_log(
                'Socket %r successfully connected for remote addrinfo %r, '
                'local addr %r',
                sock, addr_info, local_addr)
            return sock
        except:
            sock.close()
            raise
    except Exception:
        # This will NOT catch asyncio.CancelledError.
        debug_log(
            'Creating socket with remote addrinfo %r, local addr %r '
            'failed with exception',
            addr_info, local_addr, exc_info=True)
        raise


async def create_connected_sock(
        host: HostType,
        port: PortType,
        *,
        family: int = socket.AF_UNSPEC,
        proto: int = 0,
        flags: int = 0,
        local_addrs: Iterable[tuple] | AsyncIterable[tuple] = None,
        delay: Optional[float] = CONNECT_DELAY,
        resolver: ResolverType = resolvers.concurrent_resolver,
        raise_exc_group: bool = False,
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
    implemented.)

    Most of the arguments should be familiar from the various :mod:`socket` and
    :mod:`asyncio` methods.
    *delay* and *resolver* control Happy Eyeballs-specific behavior.
    *local_addr* is removed in favor of *local_addrs*, which provides new
    features not specific to Happy Eyeballs.

    The *host*, *port*, *family*, *proto* and *flags* parameters are passed
    directly to the *resolver* being used. If you're using a custom resolver,
    you should verify its support for these parameters.

    Args:
        host: Host name to connect to. Unlike
            :func:`asyncio.open_connection`
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

        flags: Flags passed to ``getaddrinfo``.
            See documentation on :func:`socket.getaddrinfo` for details.
            similar to *host* and *port*.

        local_addrs: A sync or async iterable of address tuples, all of
            which are candidates for locally binding the socket to. This allows
            e.g. providing one IPv4 and one IPv6 address.
            Addresses must be already resolved. In particular, IPv4 addresses
            must be 2-tuples of ``(host, port)``, and IPv6 addresses
            must be 4-tuples of ``(host, port, flowinfo, scope_id)``,
            where ``host`` is the literal representation of the address.

        delay: Amount of time to wait before making connections to different
            addresses. This is the "Connect Attempt Delay" as defined in
            :rfc:`8305`.

        resolver: The resolver to use.
            To customize behavior of the resolver, use :func:`functools.partial`
            to bind arguments to the resolver before passing it in.
            for example, to set "First Address Family Count" to 2:

            .. code-block:: python

                resolver = functools.partial(async_stagger.resolvers.concurrent_resolver, first_addr_family_count=2)
                socket = await async_stagger.create_connected_sock(..., resolver=resolver)

        raise_exc_group: Determines what exception to raise when all
            connection attempts fail. If set to True, raise an instance of
            :class:`ExceptionGroup`
            containing all the individual exceptions raised by each connection
            and address resolution attempt.
            When set to false (default), an exception is raised the same
            way as :func:`asyncio.open_connection`: if all the connection
            attempt exceptions have the same ``str``, one of them is raised,
            otherwise an instance of :class:`OSError` is raised whose message contains
            ``str`` representations of all connection attempt exceptions.

    Returns:
        The connected :class:`socket.socket` object.


    .. versionadded:: v0.1.3
       the *local_addrs* parameter.

    .. versionadded:: v0.2.1
       the *async_dns* and *resolution_delay* parameters.

    .. versionadded:: v0.4.0
       the *resolver* parameter.

    .. versionchanged:: v0.4.0
       *local_addrs* parameter now takes sync or async iterables of already-resolved
       addresses. Support for host names is removed.

    .. versionchanged:: v0.4.0
       the *detailed_exceptions* parameter is replaced by *raise_exc_group*.
       When specified, an :class:`ExceptionGroup` is raised.

    .. versionremoved:: v0.4.0
       the *loop* parameter.

    .. versionremoved:: v0.4.0
       the *local_addr* parameter. Use *local_addrs* instead.

    .. versionremoved:: v0.4.0
       the *interleave*, *async_dns* and *resolution_delay* parameters.
       Specify them on *resolver* instead.
    """
    debug_log('Starting Happy Eyeballs connection to (%r, %r), '
              'local addresses %r',
              host, port, local_addrs)

    remote_addrinfo_aiter = resolver(
        host, port,
        family=family, type=socket.SOCK_STREAM, proto=proto, flags=flags,
    )

    if local_addrs is not None:
        try:
            local_addrs_aiter = aiter(local_addrs)
        except TypeError:
            local_addrs_aiter = aitertools.aiter_from_iter(local_addrs)
    else:
        local_addrs_aiter = aitertools.aiter_from_iter((None,))

    async def connect_tasks():
        async for ai, la in aitertools.product(
            remote_addrinfo_aiter, local_addrs_aiter
        ):
            yield partial(_connect_sock, ai, la)

    # Use a separate task for each (remote_addr, local_addr) pair. When
    # multiple local addresses are specified, this depends on the OS quickly
    # failing address combinations that don't work (e.g. an IPv6 remote
    # address with an IPv4 local address). Come to think of it, since the
    # family of the socket is determined by the remote address, if the remote
    # and local addresses have different family, binding local address should
    # raise an exception. If your OS can't figure that out,
    # it's probably time to get a better OS.
    winner_socket, _, exc, aiter_exc = await staggered_race(
        connect_tasks(), delay)

    if winner_socket:
        debug_log('Happy Eyeballs connection to (%r, %r) '
                  'from %r succeeded, connected socket %r',
                  host, port, local_addrs, winner_socket)
        return winner_socket

    debug_log('Happy eyeballs connection to (%r, %r) from %r failed',
              host, port, local_addrs)
    if aiter_exc is not None:
        if isinstance(aiter_exc, ExceptionGroup):
            exc.extend(aiter_exc.exceptions)
        else:
            exc.append(aiter_exc)
    if not raise_exc_group:
        exceptions.raise_one_exception_from_many(exc, OSError)
    else:
        raise ExceptionGroup('happy eyeballs connection failed', exc)


create_connected_sock_kwds = tuple(
    create_connected_sock.__kwdefaults__.keys())


async def create_connection(
        protocol_factory: Callable[[], asyncio.Protocol],
        host: HostType,
        port: PortType,
        **kwargs,
) -> tuple[asyncio.Transport, asyncio.Protocol]:
    """Connect to *(host, port)* and return *(transport, protocol)*.

    This is a replacement for :meth:`asyncio.loop.create_connection` with added
    Happy Eyeballs.
    Refer to that function's documentation for
    explanations of these arguments: *protocol_factory*, *ssl*, and
    *server_hostname*. Refer to :func:`~async_stagger.create_connected_sock`
    for all other arguments.

    Returns:
        *(transport, protocol)*, the same as
        :meth:`asyncio.loop.create_connection`.
    """
    loop = asyncio.get_running_loop()
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
        host, port, **create_connected_sock_kwargs)

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
        **kwargs,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect to (host, port) and return (reader, writer).

    This is a replacement for :func:`asyncio.open_connection` with added
    Happy Eyeballs.
    Refer to the documentation of that
    function for what *limit* does, and refer to
    :func:`~async_stagger.create_connection` and
    :func:`~async_stagger.create_connected_sock` for everything else.

    Returns:
        *(reader, writer)*, the same as :func:`asyncio.open_connection`.
    """
    loop = asyncio.get_running_loop()
    # Some gymnastics so I do not have to maintain a copy of the default value
    # for the keyword argument 'limit' for asyncio.open_connection and
    # asyncio.StreamReader
    stream_reader_kwargs = {}
    if 'limit' in kwargs:
        stream_reader_kwargs['limit'] = kwargs.pop('limit')
    reader = asyncio.StreamReader(**stream_reader_kwargs)
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await create_connection(
        lambda: protocol, host, port, **kwargs)
    writer = asyncio.StreamWriter(transport, protocol, reader, loop)
    return reader, writer
