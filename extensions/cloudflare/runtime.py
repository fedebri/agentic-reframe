"""Workers-specific storage, authentication, and HTTP transport boundaries."""

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import jwt

from extensions.web.identity import AccessIdentity

from .snapshots import SnapshotStore

if TYPE_CHECKING:
    from openai import OpenAI

DATA_ROOT = Path("/tmp/agentic-reframe/data")
RESOURCE_ROOT = Path("/tmp/agentic-reframe/resources")


def stage_resources() -> Path:
    """Keep canonical resource paths stable across Worker versions and isolates."""
    source = Path(__file__).resolve().parents[2]
    files = [
        source / "config/project.yaml",
        source / "docs/brief.md",
        source / "agents/analyst.md",
        source / "agents/critic.md",
        *source.joinpath("exercises").glob("*.md"),
    ]
    for path in files:
        target = RESOURCE_ROOT / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return RESOURCE_ROOT / "config/project.yaml"


class WorkersKeys(jwt.PyJWKClient):
    """Retain PyJWT validation while fetching JWKS through Workers' Fetch API."""

    def fetch_data(self):
        from js import AbortSignal
        from pyodide.ffi import run_sync
        from workers import fetch

        try:
            response = run_sync(fetch(self.uri, signal=AbortSignal.timeout(5000)))
            if response.status != 200:
                raise jwt.PyJWKClientConnectionError("Access signing keys unavailable.")
            data = run_sync(response.json())
        except jwt.PyJWKClientConnectionError:
            raise
        except Exception as error:
            raise jwt.PyJWKClientConnectionError(
                "Access signing keys unavailable."
            ) from error
        if self.jwk_set_cache is not None:
            self.jwk_set_cache.put(data)
        return data


class WorkersIdentity(AccessIdentity):
    """Verify the same Access identity contract without urllib socket access."""

    def __init__(self, issuer: str, audience: str):
        super().__init__(issuer, audience)
        self.keys = WorkersKeys(f"{self.issuer}/cdn-cgi/access/certs", lifespan=300)


class WorkersTransport(httpx.BaseTransport):
    """Give the existing synchronous OpenAI client a bounded Workers Fetch transport."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        from js import AbortSignal
        from pyodide.ffi import run_sync
        from workers import fetch

        # This adapter is solely for the SDK's configured OpenAI endpoint.
        if request.url.scheme != "https" or request.url.host != "api.openai.com":
            raise httpx.UnsupportedProtocol(
                "Only the OpenAI HTTPS endpoint is allowed."
            )
        timeout = request.extensions.get("timeout", {}).get("read") or 60
        try:
            response = run_sync(
                fetch(
                    str(request.url),
                    method=request.method,
                    headers=dict(request.headers),
                    body=request.content,
                    redirect="error",
                    signal=AbortSignal.timeout(int(timeout * 1000)),
                )
            )
            content = run_sync(response.bytes())
        except Exception as error:
            raise httpx.ConnectError(
                "Workers API request failed.", request=request
            ) from error
        return httpx.Response(
            response.status,
            headers=list(response.headers.items()),
            content=content,
            request=request,
        )


def api_client(key: str, timeout_seconds: float) -> "OpenAI":
    """Keep retries and budgeting in the existing core, rather than the SDK."""
    from openai import OpenAI

    return OpenAI(
        api_key=key,
        max_retries=0,
        timeout=timeout_seconds,
        http_client=httpx.Client(transport=WorkersTransport()),
    )


def hosted_app(env, root: Path = DATA_ROOT):
    """Create the existing Flask interface on a serialized, restored snapshot."""
    # The OpenAI SDK initializes random values on import. Workers disallows that
    # during startup snapshots, so load the existing web/core code inside a request.
    from extensions.web.app import create_app

    local = getattr(env, "DEV_MODE", "0") == "1"
    secret = getattr(env, "WEB_SECRET_KEY", "")
    if not secret:
        raise ValueError("Set the WEB_SECRET_KEY Worker secret before opening the app.")
    issuer = getattr(env, "WEB_ACCESS_TEAM_DOMAIN", "")
    audience = getattr(env, "WEB_ACCESS_AUD", "")
    return create_app(
        {
            "DATA_ROOT": root,
            "PROJECT_CONFIG": stage_resources(),
            "SECRET_KEY": secret,
            "AUTH_MODE": "local" if local else "cloudflare",
            "ACCESS_TEAM_DOMAIN": issuer,
            "ACCESS_AUD": audience,
            "ADMIN_EMAILS": getattr(env, "WEB_ADMIN_EMAILS", ""),
            "RUN_BUDGET_USD": getattr(env, "WEB_RUN_BUDGET_USD", "0"),
            "USER_BUDGET_USD": getattr(env, "WEB_USER_BUDGET_USD", "0.50"),
            "TOTAL_BUDGET_USD": getattr(env, "WEB_TOTAL_BUDGET_USD", "5.00"),
            "LIVE_ENABLED": getattr(env, "WEB_LIVE_ENABLED", "0") == "1",
            "SESSION_COOKIE_SECURE": not local,
            "SESSION_COOKIE_NAME": "agentic_reframe_cloudflare",
        },
        store=SnapshotStore(root),
        access=None if local else WorkersIdentity(issuer, audience),
    )
