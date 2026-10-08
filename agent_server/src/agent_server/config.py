"""Strict release-local configuration with no global skill or database lookup."""

import os
import re
import tomllib
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    port: Annotated[int, Field(ge=1, le=65535)] = 8910
    startup_timeout_seconds: Annotated[int, Field(ge=1, le=120)] = 60


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    base_url: str
    name: str
    api_key_env: str
    context_window_tokens: Annotated[int, Field(ge=4096)]
    store: bool = False
    supports_forced_tool_choice: bool = True

    @model_validator(mode="after")
    def valid_provider(self) -> "ModelSettings":
        if not self.base_url.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
            raise ValueError("model.base_url must be HTTPS or local loopback HTTP")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", self.api_key_env):
            raise ValueError("model.api_key_env must be an environment variable name")
        if not self.name or self.name == "set-model-name":
            raise ValueError("model.name must be configured before live use")
        return self


class LimitSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    decision_seconds: Annotated[int, Field(ge=1, le=120)] = 60
    invalid_intent_attempts: Annotated[int, Field(ge=1, le=10)] = 3
    model_requests: Annotated[int, Field(ge=1, le=100)] = 8
    host_tool_attempts: Annotated[int, Field(ge=1, le=1000)] = 64
    client_queries: Annotated[int, Field(ge=0, le=100)] = 4


class CompactionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    trigger_fraction: Annotated[float, Field(gt=0, lt=1)] = 0.75
    target_fraction: Annotated[float, Field(gt=0, lt=1)] = 0.60
    summary_timeout_seconds: Annotated[int, Field(ge=1, le=60)] = 10

    @model_validator(mode="after")
    def valid_thresholds(self) -> "CompactionSettings":
        if self.target_fraction >= self.trigger_fraction:
            raise ValueError("compaction target must be below trigger")
        return self


class StorageSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    directory: str = ".agents/data"
    checkpoint_interval: Annotated[int, Field(ge=1, le=10000)] = 32
    retention_days: Annotated[int, Field(ge=1, le=3650)] = 30
    max_bytes: Annotated[int, Field(ge=1)] = 2 * 1024 * 1024 * 1024


class ServiceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    server: ServerSettings
    model: ModelSettings
    limits: LimitSettings
    compaction: CompactionSettings
    storage: StorageSettings


def load_settings(
    release_root: Path, profile: str = "config", *, offline: bool = False
) -> ServiceSettings:
    """Read only a named profile below release_root/.agents."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", profile):
        raise ValueError("invalid agent configuration profile")
    path = release_root / ".agents" / f"{profile}.toml"
    if profile == "config" and not path.exists() and offline:
        path = release_root / ".agents" / "config.example.toml"
    if not path.resolve().is_relative_to(release_root.resolve()):
        raise ValueError("agent configuration must remain inside the release root")
    with path.open("rb") as stream:
        document = tomllib.load(stream)
    if offline and document.get("model", {}).get("name") == "set-model-name":
        document["model"]["name"] = "offline-test-model"
    settings = ServiceSettings.model_validate(document)
    directory = release_root / settings.storage.directory
    if not directory.resolve().is_relative_to(release_root.resolve()):
        raise ValueError("storage.directory must be inside the release root")
    return settings


def model_api_key(settings: ServiceSettings) -> str:
    secret = os.environ.get(settings.model.api_key_env, "")
    if not secret:
        raise ValueError(f"missing model API key environment variable {settings.model.api_key_env}")
    return secret


def profile_data_dir(release_root: Path, settings: ServiceSettings, profile: str) -> Path:
    """Resolve one profile's private data directory under the configured base.

    The legacy database at the base path is deliberately left untouched.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", profile):
        raise ValueError("invalid agent configuration profile")
    root = release_root.resolve()
    base = release_root / settings.storage.directory
    target = base / profile
    if not base.resolve().is_relative_to(root) or not target.resolve().is_relative_to(root):
        raise ValueError("storage.directory must remain inside the release root")
    if target.is_symlink():
        raise ValueError("profile data directory must not be a symlink")
    return target
