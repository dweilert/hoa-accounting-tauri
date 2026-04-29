"""AWS Cognito OIDC authentication backend."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from typing import Any
from urllib.parse import urlencode

_log = logging.getLogger(__name__)

from hoa_accounting.auth.base import ROLE_ADMIN, ROLE_REPORTS, AuthUser

DEFAULT_GROUP_ROLE_MAP: dict[str, str] = {
    "board": ROLE_ADMIN,
    "review-admin": ROLE_ADMIN,
    "homeowner": ROLE_REPORTS,
    "reviewers": ROLE_REPORTS,
}


class CognitoBackend:
    supports_password = False
    supports_oauth = True

    def __init__(
        self,
        user_pool_id: str,
        client_id: str,
        client_secret: str,
        region: str,
        domain: str,
        group_role_map: dict[str, str],
        override_db_path: str | None = None,
        override_conn: sqlite3.Connection | None = None,
    ) -> None:
        self._pool_id = user_pool_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._region = region
        self._domain = domain.rstrip("/")
        self._group_role_map = {**DEFAULT_GROUP_ROLE_MAP, **group_role_map}
        self._override_db_path = override_db_path or (None if override_conn is None else None)
        self._override_conn = override_conn  # kept for backwards compat
        self._override_tl = threading.local()
        self._jwks_cache: dict[str, Any] = {}
        self._jwks_expires: float = 0.0

    def _get_override_conn(self) -> sqlite3.Connection | None:
        if self._override_db_path:
            conn = getattr(self._override_tl, "conn", None)
            if conn is None:
                conn = sqlite3.connect(self._override_db_path)
                conn.row_factory = sqlite3.Row
                self._override_tl.conn = conn
            return conn
        return self._override_conn

    # ── AuthBackend protocol ──────────────────────────────────────────────

    def authenticate(self, email: str, password: str) -> AuthUser | None:
        return None  # Cognito doesn't support password auth here

    def get_login_url(self, redirect_uri: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid email profile",
        }
        return f"{self._domain}/oauth2/authorize?{urlencode(params)}"

    def handle_callback(self, code: str, redirect_uri: str) -> AuthUser | None:
        tokens = self._exchange_code(code, redirect_uri)
        if not tokens:
            return None
        id_token = tokens.get("id_token")
        if not id_token:
            return None
        return self._user_from_id_token(id_token)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any] | None:
        import urllib.request
        import json as _json
        import base64

        token_url = f"{self._domain}/oauth2/token"
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        body = urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }).encode()
        req = urllib.request.Request(
            token_url,
            data=body,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return _json.loads(resp.read())  # type: ignore[no-any-return]
        except Exception as exc:
            _log.warning("Cognito token exchange failed: %s", exc)
            return None

    def _get_jwks(self) -> dict[str, Any]:
        import urllib.request
        import json as _json

        now = time.monotonic()
        if now < self._jwks_expires and self._jwks_cache:
            return self._jwks_cache

        jwks_url = (
            f"https://cognito-idp.{self._region}.amazonaws.com"
            f"/{self._pool_id}/.well-known/jwks.json"
        )
        try:
            with urllib.request.urlopen(jwks_url, timeout=10) as resp:
                data = _json.loads(resp.read())
            self._jwks_cache = {k["kid"]: k for k in data.get("keys", [])}
            self._jwks_expires = now + 3600
        except Exception as exc:
            _log.warning("Cognito JWKS fetch failed: %s", exc)
        return self._jwks_cache

    def _user_from_id_token(self, id_token: str) -> AuthUser | None:
        import jwt
        from jwt.algorithms import RSAAlgorithm

        try:
            header = jwt.get_unverified_header(id_token)
        except Exception as exc:
            _log.warning("Cognito id_token header decode failed: %s", exc)
            return None

        jwks = self._get_jwks()
        key_data = jwks.get(header.get("kid", ""))
        if not key_data:
            return None

        try:
            public_key = RSAAlgorithm.from_jwk(key_data)
            issuer = (
                f"https://cognito-idp.{self._region}.amazonaws.com/{self._pool_id}"
            )
            claims = jwt.decode(
                id_token,
                public_key,  # type: ignore[arg-type]  # cryptography stub typed as private+public union; from_jwk returns public
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=issuer,
            )
        except Exception as exc:
            _log.warning("Cognito JWT verification failed: %s", exc)
            return None

        email = claims.get("email", "").lower()
        if not email:
            return None

        groups: list[str] = claims.get("cognito:groups", []) or []
        name = (
            claims.get("name")
            or f"{claims.get('given_name', '')} {claims.get('family_name', '')}".strip()
            or email
        )
        role = self._resolve_role(email, groups)
        return AuthUser(
            email=email,
            display_name=name,
            role=role,
            backend="cognito",
            groups=groups,
        )

    def _resolve_role(self, email: str, groups: list[str]) -> str:
        # Local override takes highest priority
        _oc = self._get_override_conn()
        if _oc:
            row = _oc.execute(
                "SELECT role FROM local_role_overrides WHERE email = ? COLLATE NOCASE",
                (email,),
            ).fetchone()
            if row:
                return row["role"]  # type: ignore[no-any-return]

        # Map Cognito group → role (first match wins, admin beats reports)
        mapped_roles = {self._group_role_map.get(g) for g in groups} - {None}
        if ROLE_ADMIN in mapped_roles:
            return ROLE_ADMIN
        if ROLE_REPORTS in mapped_roles:
            return ROLE_REPORTS

        return ROLE_REPORTS  # default: least privilege
