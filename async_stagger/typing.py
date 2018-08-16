"""Types used in type hints around the package."""

from typing import Tuple, Union

AddrInfoType = Tuple[
    int,  # family
    int,  # type
    int,  # proto
    str,  # canonname
    Tuple,  # sockaddr
]

HostType = Union[str, bytes, None]
PortType = Union[str, bytes, int, None]
