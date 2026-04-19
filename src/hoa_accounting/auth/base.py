"""Shared auth types — no backend-specific imports here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

ROLE_ADMIN   = "admin"
ROLE_REPORTS = "reports"


@dataclass(frozen=True)
class AuthUser:
    email: str
    display_name: str
    role: str
    backend: str
    groups: list[str] = field(default_factory=list)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_reports_only(self) -> bool:
        return self.role == ROLE_REPORTS

    def to_session(self) -> dict:
        return {
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "backend": self.backend,
            "groups": self.groups,
        }

    @staticmethod
    def from_session(data: dict) -> "AuthUser":
        return AuthUser(
            email=data["email"],
            display_name=data.get("display_name", ""),
            role=data.get("role", ROLE_REPORTS),
            backend=data.get("backend", "unknown"),
            groups=data.get("groups", []),
        )


@runtime_checkable
class AuthBackend(Protocol):
    supports_password: bool
    supports_oauth: bool

    def authenticate(self, email: str, password: str) -> AuthUser | None: ...
    def get_login_url(self, redirect_uri: str) -> str | None: ...
    def handle_callback(self, code: str, redirect_uri: str) -> AuthUser | None: ...
