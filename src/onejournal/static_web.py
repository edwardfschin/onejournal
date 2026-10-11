"""Serve a public static shell around the existing protected Mac API.

Only a validated Vite artifact is served. No source tree, Node runtime,
financial calculation, broker call, provisioning or migration is involved.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from onejournal.passkey_access import validate_origin

STATIC_CONTRACT = "onejournal.static-web.v1"
PUBLIC_HEADERS = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "publickey-credentials-get=(self), publickey-credentials-create=(self)",
    "X-Content-Type-Options": "nosniff",
}


def static_routes(directory: Path) -> tuple[list[str], dict[str, str]]:
    """Validate the versioned route artifact emitted from web/lib/routes.ts."""
    try:
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError
        for name in ("index.html", "favicon.svg", "onejournal-static-web.json", "assets", "fonts"):
            path = directory / name
            if path.is_symlink() or not path.exists():
                raise ValueError
        for name in ("index.html", "favicon.svg", "onejournal-static-web.json"):
            if not (directory / name).is_file():
                raise ValueError
        for name in ("assets", "fonts"):
            if not (directory / name).is_dir():
                raise ValueError
        document = json.loads((directory / "onejournal-static-web.json").read_text(encoding="utf-8"))
        names = {"portfolio", "trades", "journal", "reports", "data", "settings"}
        expected = {"/demo", "/local/today"} | {f"/{mode}/{name}" for mode in ("demo", "local") for name in names}
        routes = document["routes"]
        redirects = document["redirects"]
        if (document["contract_version"] != STATIC_CONTRACT or document["passkey_required"] is not True
                or not isinstance(routes, list) or len(routes) != len(expected) or set(routes) != expected
                or not isinstance(redirects, list)):
            raise ValueError
        expected_redirects = {"/": "/demo", **{f"/{name}": f"/demo/{name}" for name in names},
                              **{f"/{name}/local": f"/local/{name}" for name in ("portfolio", "journal", "reports")}}
        actual = {entry["source"]: entry["destination"] for entry in redirects}
        if len(actual) != len(redirects) or actual != expected_redirects:
            raise ValueError
        return routes, actual
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("Static website artifact is missing or incompatible; rebuild it from the locked source.") from None


def serve_static_web(protected_app: FastAPI, directory: Path) -> FastAPI:
    """Public files are separate from, never exempted inside, the API gate."""
    access = getattr(protected_app.state, "passkey_access", None)
    if access is None:
        raise ValueError("Static private serving requires the existing passkey-protected API.")
    origin = validate_origin(access.origin)
    host = urlsplit(origin).netloc
    directory = directory.absolute()
    routes, redirects = static_routes(directory)

    @asynccontextmanager
    async def lifespan(app):
        # Mounted ASGI apps do not receive startup/shutdown automatically.
        async with protected_app.router.lifespan_context(protected_app):
            yield

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def public_boundary(request: Request, call_next):
        if (request.headers.get("host") != host
                or request.headers.get("origin", origin) != origin
                or any(name in request.headers for name in ("forwarded", "x-forwarded-host", "x-forwarded-proto"))):
            response = JSONResponse({"detail": "Local origin required."}, status_code=403)
        else:
            response = await call_next(request)
        for name, value in PUBLIC_HEADERS.items():
            response.headers[name] = value
        return response

    async def shell():
        return FileResponse(directory / "index.html", media_type="text/html")

    for path in routes:
        app.add_api_route(path, shell, methods=["GET", "HEAD"], include_in_schema=False)

    def redirect_to(destination):
        async def redirect(request: Request):
            query = request.url.query
            return RedirectResponse(destination + ("?" + query if query else ""), status_code=307)
        return redirect

    for source, destination in redirects.items():
        app.add_api_route(source, redirect_to(destination), methods=["GET", "HEAD"], include_in_schema=False)

    async def favicon():
        return FileResponse(directory / "favicon.svg", media_type="image/svg+xml")

    app.add_api_route("/favicon.svg", favicon, methods=["GET", "HEAD"], include_in_schema=False)
    for name in ("assets", "fonts"):
        app.mount("/" + name, StaticFiles(directory=directory / name, follow_symlink=False))
    # Unknown URLs and every API/export stay behind the original gate. No SPA
    # catch-all can turn private/API errors into public HTML successes.
    app.mount("/", protected_app)
    return app
