from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar


class ModelSettingsManager:
    """Durable role/provider/model configuration applied to live adapters."""

    available_models: ClassVar[list[str]] = [
        "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4",
    ]
    providers: ClassVar[dict[str, str]] = {
        "codex_cli": "Codex CLI",
        "openai_api": "OpenAI API",
        "local_openai": "Local OpenAI-compatible server",
    }
    role_metadata: ClassVar[dict[str, dict[str, object]]] = {
        "conversation": {
            "label": "Conversational language",
            "description": "Meaning interpretation, rendering, repair, and memory relationships.",
            "providers": ["codex_cli", "openai_api", "local_openai"],
        },
        "evidence": {
            "label": "Evidence investigation",
            "description": "Tool-capable repository branches and evidence synthesis.",
            "providers": ["codex_cli"],
        },
        "ideas": {
            "label": "Project ideas",
            "description": "Tool-capable read-only project suggestion generation.",
            "providers": ["codex_cli"],
        },
        "implementation": {
            "label": "Implementation",
            "description": "Governed changes inside disposable implementation sandboxes.",
            "providers": ["codex_cli"],
        },
    }

    def __init__(self, path: str | Path, defaults: dict[str, dict], appliers: dict) -> None:
        self.path = Path(path)
        self.appliers = appliers
        self.selections = {role: dict(config) for role, config in defaults.items()}
        self._load()
        self._apply_all()

    def snapshot(self) -> dict[str, object]:
        return {
            "available_models": self.available_models,
            "providers": self.providers,
            "roles": [
                {"role": role, **metadata, **self.selections[role]}
                for role, metadata in self.role_metadata.items()
            ],
            "storage_path": str(self.path),
            "api_keys_are_persisted": False,
        }

    def update(
        self, role: str, model: str, provider: str,
        base_url: str = "", api_key_environment: str = "OPENAI_API_KEY",
    ) -> dict[str, object]:
        metadata = self.role_metadata.get(role)
        if metadata is None:
            raise ValueError(f"Unknown model role: {role}")
        if provider not in metadata["providers"]:
            raise ValueError(f"Provider {provider} cannot perform the {role} role.")
        if provider == "codex_cli" and model.strip() == "gpt-5.4":
            raise ValueError(
                "gpt-5.4 is unavailable for this Codex ChatGPT configuration. "
                "Choose gpt-5.6-sol or another supported Codex model."
            )
        if provider != "local_openai" and model not in self.available_models:
            raise ValueError(f"Unsupported hosted model selection: {model}")
        if not model.strip():
            raise ValueError("Model ID cannot be empty.")
        if provider == "openai_api":
            base_url = base_url.strip() or "https://api.openai.com/v1"
        elif provider == "local_openai":
            if not base_url.strip().startswith(("http://", "https://")):
                raise ValueError("Local model URL must begin with http:// or https://.")
            base_url = base_url.strip().rstrip("/")
        else:
            base_url = ""
            api_key_environment = ""
        self.selections[role] = {
            "provider": provider,
            "model": model.strip(),
            "base_url": base_url,
            "api_key_environment": api_key_environment.strip(),
        }
        self._apply(role)
        self._save()
        return self.snapshot()

    def _apply_all(self) -> None:
        for role in self.role_metadata:
            self._apply(role)

    def _apply(self, role: str) -> None:
        applier = self.appliers.get(role)
        if callable(applier):
            applier(dict(self.selections[role]))

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        for role, config in stored.items():
            if role not in self.role_metadata or not isinstance(config, dict):
                continue
            provider = config.get("provider")
            model = config.get("model")
            if provider in self.role_metadata[role]["providers"] and isinstance(model, str):
                self.selections[role] = {**self.selections[role], **config}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(self.selections, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
