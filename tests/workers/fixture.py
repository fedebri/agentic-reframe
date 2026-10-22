"""Local-only provider stub; exercise the real SDK, core, R2, and job coordinator."""

import asyncio
import hashlib
import json
import time

import workers
from workers import Response

from extensions.cloudflare.runner import AnalysisRunner as _AnalysisRunner
from extensions.cloudflare.runner import Default as _Default

identity_keys = None
identity_fetches = 0
attempts = {}


async def fictional_provider(url, **options):
    """Intercept every outbound fetch; no external network is allowed in this runner."""
    if str(url) == "https://fictional.cloudflareaccess.com/cdn-cgi/access/certs":
        global identity_fetches
        identity_fetches += 1
        if identity_fetches == 1:
            return Response("FICTIONAL temporary key-service outage", status=503)
        return Response.json(identity_keys)
    if not str(url).startswith("https://api.openai.com/v1/responses"):
        raise AssertionError("The fixture runner cannot contact external services.")
    payload = json.loads(options["body"])
    assert "FICTIONAL-HUMAN-ONLY" not in json.dumps(payload)
    if str(url).endswith("/input_tokens"):
        return Response.json({"object": "response.input_tokens", "input_tokens": 100})
    if "FICTIONAL-SIMULATE-429" in json.dumps(payload):
        request_id = hashlib.sha256(options["body"]).hexdigest()
        attempts[request_id] = attempts.get(request_id, 0) + 1
        if attempts[request_id] == 1:
            return Response.json(
                {
                    "error": {
                        "message": "FICTIONAL transient failure",
                        "type": "rate_limit_error",
                    }
                },
                status=429,
            )
    # Leave time for a browser request to save a draft while the runner is working.
    await asyncio.sleep(2)
    schema = payload["text"]["format"]["schema"]
    exercise = schema["properties"]["exercise_id"]["const"]
    if "PassageClaimDraft" in schema.get("$defs", {}):
        definition = schema["$defs"]["PassageClaimDraft"]["properties"]
        source_id = definition["evidence_refs"]["items"]["enum"][0]
        result = {
            "role": "analyst",
            "exercise_id": exercise,
            "claims": [
                {
                    "local_id": f"fictional-{index}",
                    "statement": f"FICTIONAL Cloudflare smoke-test finding {index}.",
                    "claim_type": "hypothesis",
                    "deliverable": deliverable,
                    "evidence_refs": [source_id],
                    "citations": [{"source_id": source_id, "passage_id": "p1"}],
                    "derived_from": [],
                    "confidence": 0.2,
                    "public_reasoning_summary": "FICTIONAL test; no market finding.",
                    "open_questions": ["What real evidence would test this?"],
                }
                for index, deliverable in enumerate(definition["deliverable"]["enum"])
            ],
        }
    else:
        result = {
            "role": "critic",
            "exercise_id": exercise,
            "issues": [],
            "recommendation": "proceed",
            "next_action": "review",
            "next_question": None,
        }
    return Response.json(
        {
            "id": "resp_fictional_cloudflare_smoke",
            "object": "response",
            "created_at": 0,
            "model": payload["model"],
            "status": "completed",
            "output": [
                {
                    "id": "msg_fictional",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(result),
                            "annotations": [],
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 100,
                "total_tokens": 200,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        },
        headers={"x-request-id": "fictional-cloudflare-smoke"},
    )


class AnalysisRunner(_AnalysisRunner):
    """Use the production Durable Object with only its provider boundary replaced."""

    async def fetch(self, request):
        workers.fetch = fictional_provider
        return await super().fetch(request)


class Default(_Default):
    """Forward analysis exactly as production; retain the local identity probe."""

    async def fetch(self, request):
        if request.url.endswith("/identity-probe"):
            import jwt
            from cryptography.hazmat.primitives.asymmetric import rsa

            from extensions.cloudflare.runtime import WorkersIdentity

            global identity_keys, identity_fetches
            identity_fetches = 0
            private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
            identity_keys = {"keys": [{**jwk, "kid": "fictional", "alg": "RS256"}]}
            workers.fetch = fictional_provider
            payload = {
                "iss": "https://fictional.cloudflareaccess.com",
                "aud": ["fictional-audience"],
                "sub": "fictional-subject",
                "email": "fictional@example.test",
                "iat": int(time.time()),
                "exp": int(time.time()) + 60,
            }
            verifier = WorkersIdentity(payload["iss"], "fictional-audience")
            token = jwt.encode(
                payload, private, algorithm="RS256", headers={"kid": "fictional"}
            )
            assert verifier.authenticate(token).subject == "fictional-subject"
            assert verifier.authenticate(token).subject == "fictional-subject"
            assert identity_fetches == 2
            invalid = jwt.encode(
                {**payload, "aud": ["wrong-audience"]},
                private,
                algorithm="RS256",
                headers={"kid": "fictional"},
            )
            try:
                verifier.authenticate(invalid)
            except jwt.InvalidTokenError:
                return Response.json(
                    {
                        "signature_verified": True,
                        "wrong_audience_rejected": True,
                        "temporary_failure_retried": True,
                        "cached_keys_reused": True,
                    }
                )
            raise AssertionError("An invalid Access audience was accepted.")
        return await super().fetch(request)
