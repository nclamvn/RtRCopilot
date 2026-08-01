"""TIP-012 Task 2 — app-layer quotas, limits and resilience.

Redis-backed rate limiting, request body-size limits, provider cost budgets,
per-provider circuit breaker and job backpressure. Enforced in the API app
layer (D-012-03) so the guarantees survive an ingress bypass and are testable.
"""
