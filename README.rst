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
These methods have the same behavior when a host name resolves to several IP
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

These methods support additional optional arguments: *delay* and *interleave*
control Happy Eyeballs behavior, and *local_addrs* allows specifying multiple
local addresses to bind to. Check the documentation for details.


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

``async_stagger`` requires Python 3.6 or later.
(v0.2.0 onwards uses more new features in 3.6 such as async generators and
async comprehensions, so it will probably require more than cosmetic changes
to make it run on 3.5.)
It does not have any external dependencies.
Install it from PyPI the usual way::

    pip install async-stagger

The documentation can be found here:
http://async-stagger.readthedocs.io/en/latest/

This project is under active development, and APIs may change in the future.
Check out the Changelog in the documentation.

This project is licensed under the MIT license.


Miscellaneous Remarks
=====================

I have implemented Happy Eyeballs-like algorithms in some of my other projects,
and this module reflects the things I have learned. However I have yet to
eat my own dog food and actually import this module from those other projects.
I would love to hear people's experience using this module in real world
conditions.

`bpo-31861 <https://bugs.python.org/issue31861>`_ talks about adding native
``aiter`` and ``anext`` functions either as builtins or to the ``operator``
module. Well, I want them NAO!!!one!!!eleventy!! So I borrowed the
implementations from that bpo and put them in the ``aitertools`` submodule.
I have only kept the one-argument forms; In particular, the two-argument
``iter`` function is so disparate from the one-argument version, that I don't
think they belong to the same function at all, and there really shouldn't be
a need for ``aiter`` to emulate that behavior.


Acknowledgments
===============

The Happy Eyeballs scheduling algorithm implementation is inspired by
`the implementation in trio`__.

__ https://github.com/python-trio/trio/pull/145/files

