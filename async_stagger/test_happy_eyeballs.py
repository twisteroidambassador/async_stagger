import asyncio
import itertools
import socket

import pytest

from . import happy_eyeballs


pytestmark = pytest.mark.skipif(
    not hasattr(socket, 'AF_INET6'), reason='Platform does not support IPv6')

IPV6_ADDRINFOS = [
    (socket.AF_INET6, 0, 0, '', ('2001:db8::1', 1)),
    (socket.AF_INET6, 0, 0, '', ('2001:db8::2', 2)),
    (socket.AF_INET6, 0, 0, '', ('2001:db8::3', 3)),
    (socket.AF_INET6, 0, 0, '', ('2001:db8::4', 4)),
]

IPV4_ADDRINFOS = [
    (socket.AF_INET, 0, 0, '', ('192.0.2.1', 5)),
    (socket.AF_INET, 0, 0, '', ('192.0.2.2', 6)),
    (socket.AF_INET, 0, 0, '', ('192.0.2.3', 7)),
    (socket.AF_INET, 0, 0, '', ('192.0.2.4', 8)),
]

LOCALHOST_ADDRINFOS = [
    (socket.AF_INET6, 0, 0, '', ('::1', 9)),
    (socket.AF_INET, 0, 0, '', ('127.0.0.1', 10)),
]


async def mock_getaddrinfo(host, port, *, family=0, type=0, proto=0, flags=0):
    if host == 'magic-host':
        if family == socket.AF_INET6:
            return IPV6_ADDRINFOS
        elif family == socket.AF_INET:
            return IPV4_ADDRINFOS
        else:
            return IPV6_ADDRINFOS + IPV4_ADDRINFOS
    elif host == 'localhost':
        if family == socket.AF_INET6:
            return LOCALHOST_ADDRINFOS[0:1]
        elif family == socket.AF_INET:
            return LOCALHOST_ADDRINFOS[1:2]
        else:
            return LOCALHOST_ADDRINFOS
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
            raise OSError('fileno not supported')
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise OSError('family not supported')
        self._family = family
        self._type = type
        self._proto = proto

        self.sockname = None
        self.peername = None
        self.blocking = True

    def setblocking(self, blocking):
        self.blocking = blocking

    def bind(self, address):
        if self.sockname is not None:
            raise OSError('socket already bound')
        try:
            socket.inet_pton(self._family, address[0])
        except OSError as e:
            raise OSError('invalid bind address family') from e
        self._bind_response(address)
        self.sockname = address

    def _bind_response(self, address):
        return

    async def async_connect(self, address):
        if self.peername is not None:
            raise OSError('socket already connected')
        try:
            socket.inet_pton(self._family, address[0])
        except OSError as e:
            raise OSError('invalid connect address family') from e
        await self._connect_response(address)
        self.peername = address

    async def _connect_response(self, address):
        await asyncio.sleep(0.05)


async def mock_loop_sock_connect(sock, address):
    await sock.async_connect(address)


@pytest.mark.asyncio
async def test_create_connected_sock_normal(event_loop, mocker):
    mocker.patch('socket.socket', wraps=MockSocket)
    mocker.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo)
    mocker.patch.object(
        event_loop, 'sock_connect', side_effect=mock_loop_sock_connect)

    s = await happy_eyeballs.create_connected_sock('magic-host', 80)


@pytest.mark.asyncio
async def test_create_connected_sock_local_bind(event_loop, mocker):
    mocker.patch('socket.socket', wraps=MockSocket)
    mocker.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo)
    mocker.patch.object(
        event_loop, 'sock_connect', side_effect=mock_loop_sock_connect)

    s = await happy_eyeballs.create_connected_sock(
        'magic-host', 80, local_addr=('localhost', 0))


@pytest.mark.asyncio
async def test_create_connected_sock_ip_literal(
        event_loop,
        mocker,
):
    mocker.patch('socket.socket', wraps=MockSocket)
    mocker.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo)
    mocker.patch.object(
        event_loop, 'sock_connect', side_effect=mock_loop_sock_connect)

    s = await happy_eyeballs.create_connected_sock('192.0.2.1', 80)

    event_loop.getaddrinfo.assert_not_called()


@pytest.mark.asyncio
async def test_create_connected_sock_ipv6_hang(
        event_loop,
        mocker,
):
    class MockSocketIPv6Hang(MockSocket):
        async def _connect_response(self, address):
            if self._family == socket.AF_INET6:
                await asyncio.sleep(10)
                raise OSError('connect to IPv6 address failed')

    mocker.patch('socket.socket', wraps=MockSocketIPv6Hang)
    mocker.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo)
    mocker.patch.object(
        event_loop, 'sock_connect', side_effect=mock_loop_sock_connect)

    time_start = event_loop.time()
    s = await happy_eyeballs.create_connected_sock('magic-host', 80)
    assert event_loop.time() - time_start < 1


@pytest.mark.asyncio
async def test_create_connected_sock_ipv6_bind_fail(
        event_loop,
        mocker,
):
    class MockSocketIPv6Hang(MockSocket):
        def _bind_response(self, address):
            if address[0] == '::1':
                raise OSError('bind failed')

    mocker.patch('socket.socket', wraps=MockSocketIPv6Hang)
    mocker.patch.object(event_loop, 'getaddrinfo', side_effect=mock_getaddrinfo)
    mocker.patch.object(
        event_loop, 'sock_connect', side_effect=mock_loop_sock_connect)

    s = await happy_eyeballs.create_connected_sock(
        'magic-host', 80, local_addr=('localhost', 0))


@pytest.mark.asyncio
async def test_create_connected_sock_bind_order(
        event_loop,
        mocker,
):
    local_addrinfo_lists = [
        LOCALHOST_ADDRINFOS,
        list(reversed(LOCALHOST_ADDRINFOS)),
    ]
    remote_addrinfo_lists = [
        [IPV6_ADDRINFOS[0]],
        [IPV4_ADDRINFOS[0]],
    ]

    for local_addrinfo, remote_addrinfo in itertools.product(
            local_addrinfo_lists, remote_addrinfo_lists):

        async def mock_gai(host, port, *, family=0, type=0, proto=0, flags=0):
            if host == 'localhost':
                return local_addrinfo
            elif host == 'magic-host':
                return remote_addrinfo
            else:
                raise socket.gaierror('invalid host')

        mocker.patch('socket.socket', wraps=MockSocket)
        mocker.patch.object(event_loop, 'getaddrinfo', side_effect=mock_gai)
        mocker.patch.object(
            event_loop, 'sock_connect', side_effect=mock_loop_sock_connect)

        s = await happy_eyeballs.create_connected_sock(
            'magic-host', 80, local_addr=('localhost', 0))
