"""CI guard: every data endpoint must require authentication.

Iterates all FastAPI routes and verifies that each data endpoint has an
authentication dependency (oauth2_scheme or get_current_user).

Exemptions: health checks, auth endpoints, OpenAPI docs.
"""

from backend.app.main import app
from backend.app.core.security import oauth2_scheme, get_current_user

# Paths that are intentionally unauthenticated.
AUTH_EXEMPT_PREFIXES = (
    "/health",
    "/api/v1/auth",
    "/docs",
    "/redoc",
    "/openapi.json",
)


def _has_auth_dependency(route) -> bool:
    """Check if a route or its parent router has an auth dependency."""
    # Check direct endpoint dependencies
    if hasattr(route, "dependant") and route.dependant:
        for dep in route.dependant.dependencies:
            dep_callable = dep.call
            if dep_callable is oauth2_scheme or dep_callable is get_current_user:
                return True
            # Check if it's a Security wrapper around get_current_user
            if hasattr(dep_callable, "__wrapped__"):
                if dep_callable.__wrapped__ is get_current_user:
                    return True
    # Check route dependencies list
    if hasattr(route, "dependencies"):
        for dep in route.dependencies:
            if hasattr(dep, "dependency"):
                if dep.dependency is oauth2_scheme or dep.dependency is get_current_user:
                    return True
    return False


def test_all_data_endpoints_require_auth() -> None:
    """Assert that every non-exempt endpoint has an auth dependency."""
    unprotected: list[str] = []

    for route in app.routes:
        # Skip non-API routes (static mounts, etc.)
        if not hasattr(route, "methods"):
            continue

        path = getattr(route, "path", "")

        # Skip exempt paths
        if any(path.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES):
            continue

        if not _has_auth_dependency(route):
            methods = ",".join(sorted(route.methods - {"HEAD", "OPTIONS"}))
            if methods:
                unprotected.append(f"{methods} {path}")

    assert not unprotected, (
        "Endpoints without authentication:\n"
        + "\n".join(f"  - {e}" for e in sorted(unprotected))
        + "\n\nAdd `dependencies=[Depends(oauth2_scheme)]` to the router "
        "or `Security(get_current_user, scopes=[...])` to each endpoint."
    )
