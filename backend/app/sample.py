"""Generates a realistic demo log so the app has something to show on load."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

NORMAL = [
    ('INFO', 'checkout-api', 'Request completed GET /api/v1/cart/{id} in {ms}ms'),
    ('INFO', 'checkout-api', 'Request completed POST /api/v1/orders in {ms}ms'),
    ('INFO', 'auth-service', 'User {uid} authenticated from {ip}'),
    ('DEBUG', 'checkout-api', 'Cache hit for key cart:{uid}'),
    ('INFO', 'payment-worker', 'Charged order {oid} for ${amt}'),
    ('WARN', 'checkout-api', 'Slow query took {ms}ms: SELECT * FROM carts WHERE user_id = {uid}'),
    ('INFO', 'inventory', 'Stock level for SKU-{sku} updated to {qty}'),
]

INCIDENT = [
    ('ERROR', 'payment-worker', 'Connection refused to payments-db:5432 for order {oid}'),
    ('ERROR', 'payment-worker', 'Failed to charge order {oid}: upstream timeout after {ms}ms'),
    ('ERROR', 'checkout-api', 'Unhandled exception in POST /api/v1/orders: ConnectionPoolTimeout'),
    ('FATAL', 'payment-worker', 'Circuit breaker opened for payments-db after {qty} failures'),
    ('WARN', 'checkout-api', 'Retrying order {oid}, attempt {qty}'),
]


def generate(lines: int = 1200, seed: int = 7) -> str:
    """A quiet service, a 4-minute database incident, then recovery."""
    rng = random.Random(seed)
    start = datetime.now(tz=timezone.utc) - timedelta(minutes=45)

    # The incident sits ~60% of the way through the window.
    incident_start = int(lines * 0.60)
    incident_end = int(lines * 0.72)

    out: list[str] = []
    for i in range(lines):
        ts = start + timedelta(seconds=i * 2.2 + rng.uniform(0, 1.4))
        in_incident = incident_start <= i < incident_end

        if in_incident and rng.random() < 0.72:
            level, service, template = rng.choice(INCIDENT)
        else:
            level, service, template = rng.choice(NORMAL)

        message = template.format(
            id=rng.randint(10_000, 99_999),
            ms=rng.randint(900, 4200) if in_incident else rng.randint(8, 180),
            uid=rng.randint(1000, 9999),
            ip=f"10.{rng.randint(0, 3)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
            oid=rng.randint(500_000, 599_999),
            amt=f"{rng.uniform(9, 420):.2f}",
            sku=rng.randint(100, 999),
            qty=rng.randint(1, 50),
        )
        out.append(
            f'{ts.strftime("%Y-%m-%dT%H:%M:%S.")}{ts.microsecond // 1000:03d}Z '
            f'{level:<5} [{service}] {message}'
        )

    return "\n".join(out)
