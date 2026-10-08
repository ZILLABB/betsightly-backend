"""Release gate for combined public API routes.

In October 2026 the integration branch cherry-picked a full API file from a
booking hotfix and accidentally dropped the Next Available endpoint. All unit
suites still passed; the live staging smoke test correctly failed with 404.
"""
from leagues import api as leagues_api


def test_recovery_integration_mounts_next_available_and_secure_booking_routes():
    expected = {"/next-available", "/bookings", "/daily-accumulators"}
    mounted = {
        route.path: route for route in leagues_api.router.routes
        if route.path in expected
    }
    assert set(mounted) == expected
    assert all("GET" in mounted[path].methods for path in expected)


def test_next_available_public_handler_must_not_be_write_or_mutation_route():
    routes = [
        route for route in leagues_api.router.routes
        if route.path == "/next-available"
    ]
    assert len(routes) == 1
    assert routes[0].methods == {"GET"}
