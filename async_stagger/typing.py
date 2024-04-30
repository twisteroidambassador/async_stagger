"""Types used in type hints around the package."""

from collections.abc import Awaitable, Sequence, AsyncIterable
from typing import Protocol


AddrInfoType = tuple[
    int,  # family
    int,  # type
    int,  # proto
    str,  # canonname
    tuple,  # sockaddr
]

HostType = str | bytes | None
PortType = str | bytes | int | None


class AsyncGetAddrInfoType(Protocol):
    def __call__(
            self,
            host: HostType,
            port: PortType,
            *,
            family: int = 0,
            type: int = 0,
            proto: int = 0,
            flags: int = 0,
            **kwargs,
    ) -> Awaitable[Sequence[AddrInfoType]]:
        ...


class ResolverType(Protocol):
    def __call__(
            self,
            host: HostType,
            port: PortType,
            *,
            family: int = 0,
            type: int = 0,
            proto: int = 0,
            flags: int = 0,
            **kwargs,
    ) -> AsyncIterable[AddrInfoType]:
        ...
