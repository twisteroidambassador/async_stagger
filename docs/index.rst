.. async_stagger documentation master file, created by
   sphinx-quickstart on Tue May  8 18:30:35 2018.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to async_stagger's documentation!
#########################################

Project home page: https://github.com/twisteroidambassador/async_stagger

Check out the :doc:`project's README file<readme_link>` for the elevator pitch.

.. toctree::
   :maxdepth: 1
   :caption: Contents of the documentation:

   self
   Project README file<readme_link>
   reference
   changelog


.. contents:: Contents of this page


Quick Start
===========


Installation
------------

Install through PyPI as usual:

.. code-block:: console

   pip install async-stagger

Python 3.11 or above is required.
For older versions of Python, use a previous release.


Making TCP connections using Happy Eyeballs
-------------------------------------------

To quickly get the benefit of Happy Eyeballs, simply use
:func:`async_stagger.create_connection` and
:func:`async_stagger.open_connection` where you would use their ``asyncio``
counterparts. Modifications required are minimal, since they support all the
usual arguments except *sock*, and all new arguments are optional and have
sane defaults.

Alternatively, use :func:`async_stagger.create_connected_sock` to create a
connected ``socket.socket`` object, and use it as you wish.


Using the underlying scheduling logic
-------------------------------------

The Happy Eyeballs scheduling logic, i.e. "run coroutines with staggered start
times, wait for one to complete, cancel all others", is exposed in a reusable
form in :func:`async_stagger.staggered_race`.


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
