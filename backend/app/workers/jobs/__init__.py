"""Periodic job modules package.

Each module in this package may define a module-level ``JOB`` attribute
(a :class:`backend.app.workers.periodic_jobs.PeriodicJob`) which is
auto-discovered and scheduled by the periodic job runner. Adding a new
job is therefore purely file-additive: drop a module here that exposes
``JOB`` and it will be picked up on startup.
"""
