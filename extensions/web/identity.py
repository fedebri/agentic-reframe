"""Verify Cloudflare Access identities using signatures, not email headers."""

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Identity:
    """Verified issuer/subject own projects; email identifies administrators."""

    issuer: str
    subject: str
    email: str


class AccessIdentity:
    """Use PyJWT's bounded JWKS retrieval and RS256 signature/claim validation."""

    def __init__(self, issuer: str, audience: str):
        import jwt

        self.issuer = issuer.rstrip("/")
        parsed = urlsplit(self.issuer)
        if (
            parsed.scheme != "https"
            or not (parsed.hostname or "").endswith(".cloudflareaccess.com")
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or parsed.port
            or not audience
        ):
            raise ValueError(
                "Set WEB_ACCESS_TEAM_DOMAIN to https://TEAM.cloudflareaccess.com "
                "and WEB_ACCESS_AUD to the application AUD."
            )
        self.audience = audience
        self.keys = jwt.PyJWKClient(
            f"{self.issuer}/cdn-cgi/access/certs", timeout=5, lifespan=300
        )

    def authenticate(self, token: str) -> Identity:
        """Validate signatures and claims, requiring an unexpired human identity."""
        import jwt

        key = self.keys.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=self.issuer,
            audience=self.audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "email"]},
        )
        if (
            not claims["sub"]
            or not isinstance(claims["email"], str)
            or not claims["email"]
        ):
            raise jwt.InvalidTokenError("A human identity is required")
        return Identity(self.issuer, claims["sub"], claims["email"].casefold())
