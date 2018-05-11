.. async_stagger documentation master file, created by
   sphinx-quickstart on Tue May  8 18:30:35 2018.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to async_stagger's documentation!
=========================================

Project home page: https://github.com/twisteroidambassador/async_stagger

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   self
   reference


Making TCP connections using Happy Eyeballs
===========================================

In practice, you will probably use the two drop-in replacements for ``asyncio``
functions, :func:`async_stagger.create_connection` and
:func:`async_stagger.open_connection`. They take pretty much the same arguments
as their ``asyncio`` counterparts.

Most of the arguments are explained in detail in the reference of
:func:`async_stagger.create_connected_sock`, though, so you may want to look
at that entry as well.


Using the underlying scheduling logic
=====================================

The Happy Eyeballs scheduling logic, i.e. "run coroutines with staggered start
times, wait for one to complete, cancel all others", is exposed in a reusable
form in :func:`async_stagger.staggered_race`.


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
