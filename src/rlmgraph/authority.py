from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class AuthenticatedIdentity:
    subject: str
    organization_id: str
    session_id: str
    authentication_method: str
    authenticated_at: datetime
    expires_at: datetime


class ManagedKeyring:
    """Local managed symmetric keys for session and audit authentication.

    The key file is a trust anchor, not part of an audit package. Possession permits signing;
    verification therefore authenticates the package to this managed installation, not to a
    public identity or external transparency service.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> dict:
        if self.path.exists():
            return self._read()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC).isoformat()
        data = {"version": 1, "active": self._new_key(now), "retired": [], "revoked": []}
        self._write_new(data)
        return data

    def rotate(self) -> str:
        data = self.initialize()
        data["retired"].append(data["active"])
        data["active"] = self._new_key(datetime.now(UTC).isoformat())
        self._replace(data)
        return data["active"]["id"]

    def revoke(self, key_id: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("Key revocation requires a reason.")
        data = self.initialize()
        candidates = [data["active"], *data["retired"]]
        key = next((item for item in candidates if item["id"] == key_id), None)
        if key is None:
            raise ValueError("Unknown signing key.")
        if key_id == data["active"]["id"]:
            data["active"] = self._new_key(datetime.now(UTC).isoformat())
        data["retired"] = [item for item in data["retired"] if item["id"] != key_id]
        data["revoked"].append({"id": key_id, "reason": reason, "at": datetime.now(UTC).isoformat()})
        self._replace(data)

    def sign(self, purpose: str, payload: bytes) -> dict[str, str]:
        key = self.initialize()["active"]
        signature = hmac.new(_unb64(key["secret"]), purpose.encode() + b"\0" + payload, hashlib.sha256)
        return {"algorithm": "HMAC-SHA256", "key_id": key["id"], "value": _b64(signature.digest())}

    def verify(self, purpose: str, payload: bytes, signature: dict) -> tuple[bool, str]:
        data = self.initialize()
        if any(item["id"] == signature.get("key_id") for item in data["revoked"]):
            return False, "signing key is revoked"
        keys = [data["active"], *data["retired"]]
        key = next((item for item in keys if item["id"] == signature.get("key_id")), None)
        if key is None:
            return False, "signing key is unavailable"
        if signature.get("algorithm") != "HMAC-SHA256":
            return False, "unsupported signature algorithm"
        expected = self.sign_with(key, purpose, payload)
        return hmac.compare_digest(expected, str(signature.get("value", ""))), "verified"

    @staticmethod
    def sign_with(key: dict, purpose: str, payload: bytes) -> str:
        digest = hmac.new(_unb64(key["secret"]), purpose.encode() + b"\0" + payload, hashlib.sha256)
        return _b64(digest.digest())

    def backup(self, destination: str | Path) -> Path:
        target = Path(destination)
        if target.exists():
            raise ValueError("Key backup destination already exists.")
        target.write_bytes(self.path.read_bytes())
        os.chmod(target, 0o600)
        return target

    def restore(self, source: str | Path) -> None:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
        self._validate(data)
        if self.path.exists():
            raise ValueError("Refusing to overwrite an existing keyring during restore.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_new(data)

    @staticmethod
    def _new_key(created_at: str) -> dict[str, str]:
        return {"id": secrets.token_hex(12), "created_at": created_at, "secret": _b64(secrets.token_bytes(32))}

    def _read(self) -> dict:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._validate(data)
        return data

    @staticmethod
    def _validate(data: dict) -> None:
        if data.get("version") != 1 or not data.get("active", {}).get("secret"):
            raise ValueError("Invalid managed keyring.")

    def _write_new(self, data: dict) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(self.path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, sort_keys=True)
        os.chmod(self.path, 0o600)

    def _replace(self, data: dict) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".new")
        if temporary.exists():
            raise RuntimeError("Keyring rotation staging file already exists.")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, sort_keys=True)
        os.replace(temporary, self.path)


class SessionAuthority:
    """Issue and verify short-lived authenticated sessions from a managed trust anchor."""

    def __init__(self, keyring: ManagedKeyring) -> None:
        self.keyring = keyring

    def issue(self, subject: str, organization_id: str, *, ttl_seconds: int = 900) -> str:
        if not subject.strip() or not organization_id.strip() or ttl_seconds <= 0:
            raise ValueError("Session subject, organization, and positive lifetime are required.")
        now = datetime.now(UTC)
        claims = {"sub": subject, "org": organization_id, "sid": secrets.token_hex(16),
                  "amr": "managed-local-key", "iat": now.isoformat(),
                  "exp": (now + timedelta(seconds=ttl_seconds)).isoformat()}
        body = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
        signature = self.keyring.sign("RLMGRAPH_SESSION_V1", body)
        return _b64(body) + "." + _b64(json.dumps(signature, sort_keys=True).encode())

    def authenticate(self, token: str, *, now: datetime | None = None) -> AuthenticatedIdentity:
        try:
            body_value, signature_value = token.split(".", 1)
            body = _unb64(body_value)
            signature = json.loads(_unb64(signature_value))
            claims = json.loads(body)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Malformed authenticated session.") from exc
        valid, reason = self.keyring.verify("RLMGRAPH_SESSION_V1", body, signature)
        if not valid:
            raise ValueError(f"Authenticated session rejected: {reason}.")
        expires = datetime.fromisoformat(claims["exp"])
        if (now or datetime.now(UTC)) >= expires:
            raise ValueError("Authenticated session expired.")
        return AuthenticatedIdentity(claims["sub"], claims["org"], claims["sid"], claims["amr"],
                                     datetime.fromisoformat(claims["iat"]), expires)
