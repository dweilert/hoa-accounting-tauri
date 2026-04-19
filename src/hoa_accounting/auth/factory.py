"""Build the auth manager from config."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from hoa_accounting.auth.base import AuthUser
from hoa_accounting.auth.local import LocalBackend

_COGNITO_RECHECK_INTERVAL = 60  # seconds between reachability probes


def _cognito_reachable(region: str, user_pool_id: str) -> bool:
    """Quick TCP/HTTP probe of the Cognito JWKS endpoint (2 s timeout)."""
    import urllib.request
    url = (
        f"https://cognito-idp.{region}.amazonaws.com"
        f"/{user_pool_id}/.well-known/jwks.json"
    )
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
                return resp.status == 200
    except Exception:
        return False


@dataclass
class AuthConfig:
    backend: str = "local"
    session_secret: str = "dev-secret-change-me"
    cognito: dict = field(default_factory=dict)
    group_role_map: dict = field(default_factory=dict)
    local_fallback: bool = True


class AuthManager:
    def __init__(
        self,
        cfg: AuthConfig,
        local: LocalBackend,
        cognito_backend: Any = None,
    ) -> None:
        self._cfg = cfg
        self._local = local
        self._cognito = cognito_backend
        # reachability cache so we don't probe on every page load
        self._cognito_reachable: bool | None = None
        self._cognito_checked_at: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────

    def authenticate_local(self, email: str, password: str) -> AuthUser | None:
        if not self.local_enabled:
            return None
        return self._local.authenticate(email, password)

    def get_cognito_login_url(self, redirect_uri: str) -> str | None:
        if self._cognito is None:
            return None
        return self._cognito.get_login_url(redirect_uri)

    def handle_cognito_callback(self, code: str, redirect_uri: str) -> AuthUser | None:
        if self._cognito is None:
            return None
        return self._cognito.handle_callback(code, redirect_uri)

    @property
    def cognito_enabled(self) -> bool:
        """True only when Cognito is configured AND currently reachable."""
        if self._cognito is None:
            return False
        if self._cfg.backend == "cognito_with_local_fallback":
            return self._check_cognito_reachable()
        return True  # "cognito" mode: always show button (fail at redirect)

    def _check_cognito_reachable(self) -> bool:
        now = time.monotonic()
        if self._cognito_reachable is None or (now - self._cognito_checked_at) > _COGNITO_RECHECK_INTERVAL:
            cognito_cfg = self._cfg.cognito
            self._cognito_reachable = _cognito_reachable(
                cognito_cfg.get("region", "us-east-1"),
                cognito_cfg.get("user_pool_id", ""),
            )
            self._cognito_checked_at = now
        return self._cognito_reachable

    @property
    def local_enabled(self) -> bool:
        mode = self._cfg.backend
        return mode in ("local", "cognito_with_local_fallback")

    @property
    def local(self) -> LocalBackend:
        return self._local


def build_auth_manager(raw_config: dict, db_path: str) -> AuthManager:
    auth_cfg_raw = raw_config.get("auth", {})
    cfg = AuthConfig(
        backend=auth_cfg_raw.get("backend", "local"),
        session_secret=auth_cfg_raw.get("session_secret", "dev-secret-change-me"),
        cognito=auth_cfg_raw.get("cognito", {}),
        group_role_map=auth_cfg_raw.get("group_role_map", {}),
        local_fallback=auth_cfg_raw.get("local_fallback", True),
    )

    local = LocalBackend(db_path)

    cognito_backend = None
    cognito_cfg = cfg.cognito
    if cfg.backend in ("cognito", "cognito_with_local_fallback") and cognito_cfg.get("user_pool_id"):
        from hoa_accounting.auth.cognito import CognitoBackend
        cognito_backend = CognitoBackend(
            user_pool_id=cognito_cfg.get("user_pool_id", ""),
            client_id=cognito_cfg.get("client_id", ""),
            client_secret=cognito_cfg.get("client_secret", ""),
            region=cognito_cfg.get("region", "us-east-1"),
            domain=cognito_cfg.get("domain", ""),
            group_role_map=cfg.group_role_map,
            override_db_path=db_path,
        )

    return AuthManager(cfg, local, cognito_backend)
