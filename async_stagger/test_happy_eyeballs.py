import asyncio
import itertools
import socket
from unittest import mock

import pytest

from . import happy_eyeballs
from . import resolvers


pytestmark = pytest.mark.skipif(
    not hasattr(socket, 'AF_INET6'), reason='Platform does not support IPv6')

IPV6_ADDRINFOS = [
    (socket.AF_INET6, 0, 0, '', ('2001:db8::1', 1, 0, 0)),
    (socket.AF_INET6, 0, 0, '', ('2001:db8::2', 2, 0, 0)),
    (socket.AF_INET6, 0, 0, '', ('2001:db8::3', 3, 0, 0)),
    (socket.AF_INET6, 0, 0, '', ('2001:db8::4', 4, 0, 0)),
]

IPV4_ADDRINFOS = [
    (socket.AF_INET, 0, 0, '', ('192.0.2.1', 5)),
    (socket.AF_INET, 0, 0, '', ('192.0.2.2', 6)),
    (socket.AF_INET, 0, 0, '', ('192.0.2.3', 7)),
    (socket.AF_INET, 0, 0, '', ('192.0.2.4', 8)),
]

LOCALHOST_ADDRS = [
    ('::1', 9, 0, 0),
    ('127.0.0.1', 10),
]


async def mock_getaddrinfo(host, port, *, family=0, type=0, proto=0, flags=0):
    if host == 'magic-host':
        if family == socket.AF_INET6:
            return IPV6_ADDRINFOS
        elif family == socket.AF_INET:
            return IPV4_ADDRINFOS
        else:
            return IPV6_ADDRINFOS + IPV4_ADDRINFOS
    else:
        raise socket.gaierror('invalid host')


class MockSocket:
    def __init__(
            self,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
            proto=0,
            fileno=None
    ):
        if fileno is not None:
            raise OSError(0, 'fileno not supported')
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise OSError(0, 'family not supported')
        self._family = family
        self._type = type
        self._proto = proto

        self.sockname = None
        self.peername = None
        self.blocking = True
        self.closed = False

    def _verify_address_family(self, address):
        if self._family == socket.AF_INET:
            if len(address) != 2:
                raise OSError(0, 'invalid IPv4 address tuple')
        elif self._family == socket.AF_INET6:
            if len(address) != 4:
                raise OSError(0, 'invalid IPv6 address tuple')
        try:
            socket.inet_pton(self._family, address[0])
        except OSError as e:
            raise OSError(0, 'invalid bind address for family') from e

    def setblocking(self, blocking):
        if self.closed:
            raise OSError(0, 'socket closed')
        self.blocking = blocking

    def bind(self, address):
        if self.closed:
            raise OSError(0, 'socket closed')
        if self.sockname is not None:
            raise OSError(0, 'socket already bound')
        self._verify_address_family(address)
        self._bind_response(address)
        self.sockname = address

    def _bind_response(self, address):
        return

    async def async_connect(self, address):
        if self.closed:
            raise OSError(0, 'socket closed')
        if self.peername is not None:
            raise OSError(0, 'socket already connected')
        self._verify_address_family(address)
        await self._connect_response(address)
        self.peername = address

    async def _connect_response(self, address):
        await asyncio.sleep(0.05)

    def close(self):
        self.closed = True


async def mock_loop_sock_connect(sock, address):
    await sock.async_connect(address)


@pytest.mark.asyncio
async def test_create_connected_sock_normal():
    event_loop = asyncio.get_running_loop()
    with mock.patch('socket.socket', wraps=MockSocket), \
        mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo), \
        mock.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect):

        s = await happy_eyeballs.create_connected_sock('magic-host', 80)


@pytest.mark.asyncio
async def test_create_connected_sock_local_bind_v4():
    event_loop = asyncio.get_running_loop()
    with (
        mock.patch('socket.socket', wraps=MockSocket),
        mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo),
        mock.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect)
    ):
        s = await happy_eyeballs.create_connected_sock(
            'magic-host', 80, local_addrs=[('127.0.0.1', 0)])


@pytest.mark.asyncio
async def test_create_connected_sock_local_bind_v6():
    event_loop = asyncio.get_running_loop()
    with (
        mock.patch('socket.socket', wraps=MockSocket),
        mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo),
        mock.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect),
    ):
        s = await happy_eyeballs.create_connected_sock(
            'magic-host', 80, local_addrs=[('::1', 0, 0, 0)])


@pytest.mark.asyncio
async def test_create_connected_sock_local_bind_v6v4():
    event_loop = asyncio.get_running_loop()
    with (
        mock.patch('socket.socket', wraps=MockSocket),
        mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo),
        mock.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect),
    ):
        s = await happy_eyeballs.create_connected_sock(
            'magic-host', 80, local_addrs=LOCALHOST_ADDRS)


@pytest.mark.asyncio
async def test_create_connected_sock_local_bind_v6v4_aiter():
    async def local_addrs():
        for addr in LOCALHOST_ADDRS:
            yield addr

    event_loop = asyncio.get_running_loop()
    with (
        mock.patch('socket.socket', wraps=MockSocket),
        mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo),
        mock.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect),
    ):
        s = await happy_eyeballs.create_connected_sock(
            'magic-host', 80, local_addrs=local_addrs())


@pytest.mark.asyncio
async def test_create_connected_sock_ipv6_hang():
    class MockSocketIPv6Hang(MockSocket):
        async def _connect_response(self, address):
            if self._family == socket.AF_INET6:
                await asyncio.sleep(10)
                raise OSError('connect to IPv6 address failed')

    event_loop = asyncio.get_running_loop()
    with (
        mock.patch('socket.socket', wraps=MockSocketIPv6Hang),
        mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo),
        mock.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect),
    ):
        time_start = event_loop.time()
        s = await happy_eyeballs.create_connected_sock('magic-host', 80)
        assert event_loop.time() - time_start < 1


@pytest.mark.asyncio
async def test_create_connected_sock_ipv6_bind_fail():
    class MockSocketIPv6Hang(MockSocket):
        def _bind_response(self, address):
            if address[0] == '::1':
                raise OSError('bind failed')
    event_loop = asyncio.get_running_loop()
    with (
        mock.patch('socket.socket', wraps=MockSocketIPv6Hang),
        mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo),
        mock.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect),
    ):
        s = await happy_eyeballs.create_connected_sock(
            'magic-host', 80, local_addrs=[('::1', 0, 0, 0), ('127.0.0.1', 0)])


@pytest.mark.asyncio
async def test_create_connected_sock_bind_order():
    local_addr_lists = [
        LOCALHOST_ADDRS,
        list(reversed(LOCALHOST_ADDRS)),
    ]
    remote_addrinfo_lists = [
        [IPV6_ADDRINFOS[0]],
        [IPV4_ADDRINFOS[0]],
    ]

    event_loop = asyncio.get_running_loop()

    for local_addr, remote_addrinfo in itertools.product(
            local_addr_lists, remote_addrinfo_lists):

        async def mock_gai(host, port, *, family=0, type=0, proto=0, flags=0):
            if host == 'magic-host':
                return remote_addrinfo
            else:
                raise socket.gaierror('invalid host')
        with (
            mock.patch('socket.socket', wraps=MockSocket),
            mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_gai),
            mock.patch.object(
                event_loop, 'sock_connect', side_effect=mock_loop_sock_connect),
        ):
            s = await happy_eyeballs.create_connected_sock(
                'magic-host', 80, local_addrs=local_addr)


@pytest.mark.asyncio
async def test_create_connected_sock_resolver_concurrent():
    event_loop = asyncio.get_running_loop()
    with (
        mock.patch('socket.socket', wraps=MockSocket),
        mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo),
        mock.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect),
    ):
        s = await happy_eyeballs.create_connected_sock(
            'magic-host', 80, resolver=resolvers.concurrent_resolver)


@pytest.mark.asyncio
async def test_create_connected_sock_resolver_basic():
    event_loop = asyncio.get_running_loop()
    with (
        mock.patch('socket.socket', wraps=MockSocket),
        mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo),
        mock.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect),
    ):
        s = await happy_eyeballs.create_connected_sock(
            'magic-host', 80, resolver=resolvers.basic_resolver)



@pytest.mark.asyncio
async def test_create_connected_sock_async_ipv6_resolve_slow():
    async def mock_gai(host, port, *, family=0, type=0, proto=0, flags=0):
        if family != socket.AF_INET:
            await asyncio.sleep(1)
        return await mock_getaddrinfo(
            host, port, family=family, type=type, proto=proto, flags=flags)

    event_loop = asyncio.get_running_loop()
    with (
        mock.patch('socket.socket', wraps=MockSocket),
        mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_gai),
        mock.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect),
    ):
        start_time = event_loop.time()
        s = await happy_eyeballs.create_connected_sock(
            'magic-host', 80, resolver=resolvers.concurrent_resolver)
        assert event_loop.time() - start_time < 1
        assert s._family == socket.AF_INET


@pytest.mark.asyncio
async def test_create_connected_sock_connect_fail_same_exception():
    class MockSocketConnectFail(MockSocket):
        async def _connect_response(self, address):
            raise OSError('connect call failed')

    event_loop = asyncio.get_running_loop()
    with (
        mock.patch('socket.socket', wraps=MockSocketConnectFail),
        mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo),
        mock.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect),
    ):
        with pytest.raises(OSError) as exc_info:
            s = await happy_eyeballs.create_connected_sock('magic-host', 80)

        assert exc_info.value.args[0] == 'connect call failed'


@pytest.mark.asyncio
async def test_create_connected_sock_connect_fail_different_exception():
    class MockSocketConnectFail(MockSocket):
        def _bind_response(self, address):
            if address[0] == '::1':
                raise OSError('bind failed')

        async def _connect_response(self, address):
            raise OSError('connect call failed')
    
    event_loop = asyncio.get_running_loop()
    with (
        mock.patch('socket.socket', wraps=MockSocketConnectFail),
        mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo),
        mock.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect),
    ):
        with pytest.raises(OSError) as exc_info:
            s = await happy_eyeballs.create_connected_sock(
                'magic-host', 80, local_addrs=LOCALHOST_ADDRS)

        assert exc_info.value.args[0].startswith('Multiple exceptions: ')


@pytest.mark.asyncio
async def test_create_connected_sock_connect_fail_raise_exc_group():
    class MockSocketConnectFail(MockSocket):
        def _bind_response(self, address):
            if address[0] == '::1':
                raise OSError(0, 'bind failed')

        async def _connect_response(self, address):
            raise OSError(0, 'connect call failed')

    event_loop = asyncio.get_running_loop()
    with (
        mock.patch('socket.socket', wraps=MockSocketConnectFail),
        mock.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo),
        mock.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect),
    ):
        with pytest.raises(ExceptionGroup) as exc_info:
            s = await happy_eyeballs.create_connected_sock(
                'magic-host', 80, local_addrs=LOCALHOST_ADDRS,
                raise_exc_group=True)

        exc = exc_info.value
        assert len(exc.exceptions) == 16
        assert all(isinstance(e, OSError) for e in exc.exceptions)
