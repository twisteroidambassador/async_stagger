"""Types used in type hints around the package."""


AddrInfoType = tuple[
    int,  # family
    int,  # type
    int,  # proto
    str,  # canonname
    tuple,  # sockaddr
]

HostType = str | bytes | None
PortType = str | bytes | int | None
