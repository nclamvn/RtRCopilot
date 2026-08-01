"""Observability surface for TIP-012 Task 3 (metrics, request-id, audit export).

Importing this package registers no metrics by itself; the metric objects live
in :mod:`rtr_copilot.observability.metrics` and are imported where they are
instrumented. Kept import-light so pulling in the route classifier or the
worker helpers never drags in the DB engine.
"""
