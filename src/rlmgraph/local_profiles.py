from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path


class LocalProfileStore:
    """Machine-local profiles with scrypt password hashes and ephemeral login tokens."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._tokens: dict[str, str] = {}
        if not self.path.exists():
            self.path.write_text('{"profiles":[]}', encoding="utf-8")

    def public_profiles(self) -> list[dict]:
        return [self._public(item) for item in self._load()["profiles"]]

    def create(self, name: str, password: str, response_style: str = "BALANCED") -> dict:
        name = " ".join(name.split())
        if not 1 <= len(name) <= 80:
            raise ValueError("Profile name must contain between 1 and 80 characters.")
        if len(password) < 8:
            raise ValueError("Password must contain at least 8 characters.")
        with self._lock:
            payload = self._load()
            if any(item["name"].casefold() == name.casefold() for item in payload["profiles"]):
                raise ValueError("A local profile with that name already exists.")
            salt = secrets.token_bytes(16)
            profile = {
                "id": f"LOCAL-PROFILE-{uuid.uuid4().hex[:12]}",
                "name": name,
                "password_salt": salt.hex(),
                "password_hash": self._hash(password, salt).hex(),
                "response_style": self._style(response_style),
                "owns_legacy_memory": not payload["profiles"],
                "created_at": datetime.now(UTC).isoformat(),
            }
            payload["profiles"].append(profile)
            self._save(payload)
        return self._login_result(profile)

    def login(self, profile_id: str, password: str) -> dict:
        profile = next(
            (item for item in self._load()["profiles"] if item["id"] == profile_id), None
        )
        if profile is None:
            raise ValueError("Local profile was not found.")
        salt = bytes.fromhex(profile["password_salt"])
        candidate = self._hash(password, salt).hex()
        if not hmac.compare_digest(candidate, profile["password_hash"]):
            raise ValueError("Password is incorrect.")
        return self._login_result(profile)

    def authenticate(self, token: str) -> dict:
        profile_id = self._tokens.get(token)
        profile = next(
            (item for item in self._load()["profiles"] if item["id"] == profile_id), None
        )
        if profile is None:
            raise PermissionError("Log in to a local profile first.")
        return self._public(profile)

    def logout(self, token: str) -> None:
        self._tokens.pop(token, None)

    def _login_result(self, profile: dict) -> dict:
        token = secrets.token_urlsafe(32)
        self._tokens[token] = profile["id"]
        return {"profile": self._public(profile), "token": token}

    @staticmethod
    def _hash(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, dklen=32,
            maxmem=64 * 1024 * 1024,
        )

    @staticmethod
    def _style(value: str) -> str:
        normalized = value.strip().upper()
        return normalized if normalized in {"CONCISE", "BALANCED", "DETAILED"} else "BALANCED"

    @staticmethod
    def _public(profile: dict) -> dict:
        return {
            key: profile[key]
            for key in ("id", "name", "response_style", "owns_legacy_memory", "created_at")
        }

    def _load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, payload: dict) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)
