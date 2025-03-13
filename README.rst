async_stagger: Happy Eyeballs in ``asyncio``
############################################

Quick, what's the situation?
============================

To get all the benefits of Happy Eyeballs connection establishment algorithm,
simply use ``async_stagger.open_connection`` like you would use
``asyncio.open_connection``::

    reader, writer = await async_stagger.open_connection('www.example.com', 80)

Now your connections are more dual-stack friendly and will complete faster!
A replacement for ``loop.create_connection`` is also provided.


The current state of Happy Eyeballs in the Python ecosystem
===========================================================

The native **asyncio** module had supported happy eyeballs since Python 3.8.1.
It's still not default behavior, though, and must be turned on deliberately.
See `the docs`__ for details.

__ https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.create_connection

[**aiohttp**](https://github.com/aio-libs/aiohttp)'s HTTP client uses happy
eyeballs by default,
and the devs maintain a vendored implementation as
[aiohappyeyeballs](https://github.com/aio-libs/aiohappyeyeballs).

Along with this repository,
the 3 implementations started very similar,
but has diverged a lot in time in order to keep up with changes in **asyncio**,
particularly with the introduction of ``eager_task_factory`` in Python 3.12.


The long version
================

What is Happy Eyeballs, and why should I use it?
------------------------------------------------

Happy Eyeballs is an algorithm for establishing TCP connections to destinations
specified by host names. It is described in :rfc:`6555` and :rfc:`8305`. The
primary benefit is that when host name resolution returns multiple addresses,
and some of the address are unreachable, Happy Eyeballs will establish the
connection much faster than conventional algorithms. For more information,
check the `Wikipedia article on Happy Eyeballs`_.

.. _Wikipedia article on Happy Eyeballs: https://en.wikipedia.org/wiki/Happy_Eyeballs

Python's standard library provides several high-level methods of establishing
TCP connections towards a host name: The **socket** module has
``socket.create_connection``,
and **asyncio** has ``loop.create_connection`` and ``asyncio.open_connection``.
By default,
these methods have the same behavior when a host name resolves to several IP
addresses: they try to connect to the first address in the list,
and only after the attempt fails (which may take tens of seconds) will
the second one be tried, and so on. In contrast, the Happy Eyeballs algorithm
will start an attempt with the second IP address in parallel to the first one
hasn't completed after some time, typically around 300 milliseconds.
As a result several attempts may be in flight at the same time, and whenever
one of the attempts succeed, all other connections are cancelled, and the
winning connection is used.
This means a much shorter wait before one of the IP addresses connect
successfully.

Happy Eyeballs is particularly important for dual-stack clients, when some hosts
may have resolvable IPv6 addresses that are somehow unreachable.


What does ``async_stagger`` has to offer?
-----------------------------------------

``async_stagger`` provides ``open_connection`` and
``create_connection`` with Happy Eyeballs support. They are mostly drop-in
replacements for their ``asyncio`` counterparts, and support most existing
arguments.
(There are small differences: ``create_connection`` takes
a *loop* argument instead of being a method on an event loop.
Also, these two methods do not support the *sock* argument.)
Another public coroutine ``create_connected_sock`` returns a connected
``socket.socket`` object.
Check the documentation for details.

These methods implements many features specified in :rfc:`8305` Happy Eyeballs
v2, which extends and obsoletes :rfc:`6555`. In particular, asynchronous
address resolution, destination address interleaving by family and staggered
connection attempts are implemented.


Happy Eyeballs sounds great! I want to use similar logic somewhere else!
------------------------------------------------------------------------

You're in luck! ``async_stagger`` actually exposes the underlying scheduling
logic as a reusable block: ``staggered_race``. It can be use when:

* There are several ways to achieve one goal. Some of the ways may fail, but
  you have to try it to find out.

* Making attempts strictly in sequence is too slow.

* You want to parallelize, but also don't want to start the attempts all
  at the same time. Maybe you want to give preference to some of the attempts,
  so they should be started earlier and given more time to complete. Maybe you
  want to avoid straining the system with simultaneous attempts.

* An attempt done half-way can be rolled back safely.


Where can I get it?
-------------------

``async_stagger`` requires Python 3.11 or later from v0.4.0 onwards.
Please use v0.3.1 for Python 3.6 - 3.10.
It does not have any external dependencies.
Install it from PyPI the usual way::

    pip install async-stagger

The documentation can be found here:
http://async-stagger.readthedocs.io/en/latest/

This project is under active development, and APIs may change in the future.
Check out the Changelog in the documentation.

This project is licensed under the MIT license.


Acknowledgments
===============

The Happy Eyeballs scheduling algorithm implementation is inspired by
`the implementation in trio`__.

__ https://github.com/python-trio/trio/pull/145/files

