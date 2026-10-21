"""Exercise Workers key retrieval and request authentication without network IO."""

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

jwt = pytest.importorskip("jwt")
pytest.importorskip("flask")
pytest.importorskip("cryptography")

from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from extensions.cloudflare import runtime  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def key_endpoint(monkeypatch):
    """Replace the native Fetch bridge; PyJWT, signatures and Flask remain real."""
    replies, calls = [], []

    async def fetch(url, *, signal):
        assert signal == 5000
        calls.append(url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, data = reply

        async def read_json():
            if isinstance(data, Exception):
                raise data
            return data

        return SimpleNamespace(status=status, json=read_json)

    monkeypatch.setitem(sys.modules, "workers", SimpleNamespace(fetch=fetch))
    monkeypatch.setitem(
        sys.modules, "js", SimpleNamespace(AbortSignal=SimpleNamespace(timeout=int))
    )
    monkeypatch.setitem(
        sys.modules, "pyodide.ffi", SimpleNamespace(run_sync=asyncio.run)
    )
    monkeypatch.setattr(runtime, "_access_identity", None)
    monkeypatch.setattr(
        runtime, "stage_resources", lambda: ROOT / "config/project.yaml"
    )
    return replies, calls


@pytest.fixture
def signing_material():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    return private, {"keys": [{**key, "kid": "fictional-key", "alg": "RS256"}]}


@pytest.mark.parametrize(
    "failure",
    [
        OSError("FICTIONAL timeout"),
        (503, {}),
        (429, {}),
        (200, OSError("FICTIONAL body timeout")),
    ],
)
def test_transient_key_fetch_retries_once(
    key_endpoint, signing_material, failure, caplog
):
    replies, calls = key_endpoint
    _, keys = signing_material
    replies.extend([failure, (200, keys)])
    client = runtime.WorkersKeys("https://fictional.cloudflareaccess.com/certs")
    assert client.get_signing_key("fictional-key").key is not None
    assert len(calls) == 2
    assert "retrying once" in caplog.text
    assert client.get_signing_key("fictional-key").key is not None
    assert len(calls) == 2


@pytest.mark.parametrize(("status", "attempts"), [(403, 1), (503, 2)])
def test_key_fetch_failure_is_bounded_and_not_cached(key_endpoint, status, attempts):
    replies, calls = key_endpoint
    replies.extend([(status, {})] * attempts)
    client = runtime.WorkersKeys("https://fictional.cloudflareaccess.com/certs")
    with pytest.raises(jwt.PyJWKClientConnectionError):
        client.fetch_data()
    assert len(calls) == attempts
    assert client.jwk_set_cache.get() is None


def test_home_reuses_keys_but_verifies_every_token_and_configuration(
    key_endpoint, signing_material, tmp_path
):
    replies, calls = key_endpoint
    private, keys = signing_material
    replies.extend([(200, keys)] * 3)
    env = SimpleNamespace(
        WEB_SECRET_KEY="fictional-session-secret",
        WEB_ACCESS_TEAM_DOMAIN="https://fictional.cloudflareaccess.com",
        WEB_ACCESS_AUD="fictional-audience",
    )
    claims = {
        "iss": env.WEB_ACCESS_TEAM_DOMAIN,
        "aud": env.WEB_ACCESS_AUD,
        "sub": "fictional-subject",
        "email": "tester@example.test",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    token = jwt.encode(
        claims, private, algorithm="RS256", headers={"kid": "fictional-key"}
    )
    for _ in range(2):
        client = runtime.hosted_app(env, tmp_path).test_client()
        response = client.get("/", headers={"Cf-Access-Jwt-Assertion": token})
        assert response.status_code == 200
        assert b"Investigate a design challenge" in response.data
    assert len(calls) == 1
    for change in (
        {"aud": "wrong"},
        {"iss": "https://wrong.cloudflareaccess.com"},
        {"exp": 1},
    ):
        invalid = jwt.encode(
            {**claims, **change},
            private,
            algorithm="RS256",
            headers={"kid": "fictional-key"},
        )
        assert (
            client.get("/", headers={"Cf-Access-Jwt-Assertion": invalid}).status_code
            == 401
        )
    assert len(calls) == 1
    for issuer, audience in (
        (env.WEB_ACCESS_TEAM_DOMAIN, "another-audience"),
        ("https://another.cloudflareaccess.com", "another-audience"),
    ):
        env.WEB_ACCESS_TEAM_DOMAIN, env.WEB_ACCESS_AUD = issuer, audience
        token = jwt.encode(
            {**claims, "iss": issuer, "aud": audience},
            private,
            algorithm="RS256",
            headers={"kid": "fictional-key"},
        )
        client = runtime.hosted_app(env, tmp_path).test_client()
        assert (
            client.get("/", headers={"Cf-Access-Jwt-Assertion": token}).status_code
            == 200
        )
    assert len(calls) == 3


def test_unavailable_signing_keys_never_open_home(
    key_endpoint, signing_material, tmp_path
):
    replies, _calls = key_endpoint
    private, _keys = signing_material
    replies.extend([(503, {})] * 2)
    env = SimpleNamespace(
        WEB_SECRET_KEY="fictional-session-secret",
        WEB_ACCESS_TEAM_DOMAIN="https://fictional.cloudflareaccess.com",
        WEB_ACCESS_AUD="fictional-audience",
    )
    token = jwt.encode(
        {
            "iss": env.WEB_ACCESS_TEAM_DOMAIN,
            "aud": env.WEB_ACCESS_AUD,
            "sub": "fictional-subject",
            "email": "tester@example.test",
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
        },
        private,
        algorithm="RS256",
        headers={"kid": "fictional-key"},
    )
    client = runtime.hosted_app(env, tmp_path).test_client()
    response = client.get("/", headers={"Cf-Access-Jwt-Assertion": token})
    assert response.status_code == 503
    assert b"Cloudflare signing keys are temporarily unavailable" in response.data
    assert b"Investigate a design challenge" not in response.data
