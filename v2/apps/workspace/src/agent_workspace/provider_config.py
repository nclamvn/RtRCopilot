"""Opt-in private server profile. Never discovers legacy provider credentials."""
import json
import os
from pathlib import Path
import re
import stat
import tempfile

ENDPOINT = "https://api.openai.com/v1"
MODEL = re.compile(r"^(?:openai:|openai-responses:)[a-zA-Z0-9][a-zA-Z0-9._-]{0,100}$")
KEYS = {"version", "model", "base_url", "api_key", "external_processing", "fixture_tools_enabled"}
MODEL_SETTINGS = {"openai_store": False, "openai_reasoning_effort": "low", "max_tokens": 2048}


def validate_profile(profile):
    if not isinstance(profile, dict) or set(profile) != KEYS or profile.get("version") != 1:
        raise ValueError("private_configuration_invalid")
    if not isinstance(profile["model"], str) or not MODEL.fullmatch(profile["model"]):
        raise ValueError("private_configuration_invalid")
    if profile["base_url"] != ENDPOINT:
        raise ValueError("unsupported_provider_endpoint")
    if not isinstance(profile["api_key"], str) or not 8 <= len(profile["api_key"]) <= 1024 or any(c.isspace() for c in profile["api_key"]):
        raise ValueError("private_configuration_invalid")
    if type(profile["external_processing"]) is not bool or type(profile["fixture_tools_enabled"]) is not bool:
        raise ValueError("private_configuration_invalid")
    return profile


def load_profile(path: Path):
    # O_NOFOLLOW avoids lstat/open races. Only explicitly named private files load.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 16384:
            raise ValueError("private_configuration_permissions")
        with os.fdopen(descriptor, "r", closefd=False) as stream:
            return validate_profile(json.load(stream))
    finally:
        os.close(descriptor)


def write_profile(path: Path, profile):
    validate_profile(profile)
    # Private directory is user-selected; refuse symlink components or replacement
    # of an existing unsafe file. Atomic replace only follows a private tempfile.
    path = path.absolute()
    for parent in [path.parent, *path.parents]:
        if parent.is_symlink():
            raise ValueError("private_configuration_symlink")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        load_profile(path)
    descriptor, scratch = tempfile.mkstemp(prefix=".workspace-profile-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(profile, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(scratch, path)
    finally:
        if os.path.exists(scratch):
            os.unlink(scratch)


def readiness(settings):
    reason = settings.configuration_error
    if reason is None and settings.model:
        if not MODEL.fullmatch(settings.model):
            reason = "unsupported_provider"
        elif settings.base_url != ENDPOINT:
            reason = "unsupported_provider_endpoint"
        elif not settings.api_key:
            reason = "workspace_api_key_not_configured"
        elif not settings.external_processing:
            reason = "external_processing_not_approved"
    elif reason is None:
        reason = "model_not_configured"
    return {"configured": reason is None, "endpoint": "OpenAI HTTPS Responses" if settings.base_url == ENDPOINT else "unsupported", "external_processing": bool(settings.external_processing), "storage": False, "transport": "responses", "requires_restart": True}, reason


def build_model(settings, *, http_client=None):
    """Constructs a client without a network call; HTTP tests inject MockTransport."""
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIResponsesModel
    from pydantic_ai.providers.openai import OpenAIProvider
    _, reason = readiness(settings)
    if reason:
        raise ValueError(reason)
    client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url,
                         max_retries=0, timeout=settings.deadline_seconds, http_client=http_client)
    # max_tokens bounds total reasoning + visible output, not visible text alone.
    return OpenAIResponsesModel(settings.model.split(":", 1)[1],
        provider=OpenAIProvider(openai_client=client),
        settings=MODEL_SETTINGS.copy())
