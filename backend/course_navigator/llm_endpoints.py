"""Shared provider-specific addressing for storage, credentials and transport."""
from urllib.parse import urlparse


def _service_base(value: str, provider_type: str) -> str:
    base = value.strip().rstrip("/")
    suffixes = ("/messages", "/models") if provider_type == "anthropic" else ("/chat/completions", "/models")
    for suffix in suffixes:
        if base.endswith(suffix):
            # A complete endpoint is explicit, including its version path.
            return base[:-len(suffix)].rstrip("/")
    if provider_type == "anthropic":
        parsed = urlparse(base)
        if ((parsed.hostname == "api.anthropic.com" and not parsed.path)
                or base.endswith("/anthropic")):
            base += "/v1"
    return base


def llm_endpoint(value: str, provider_type: str, operation: str = "chat") -> str:
    base = _service_base(value, provider_type)
    suffix = "models" if operation == "models" else ("messages" if provider_type == "anthropic" else "chat/completions")
    return f"{base}/{suffix}"


def llm_service_identity(value: str, provider_type: str) -> tuple[str, str, str]:
    return provider_type, llm_endpoint(value, provider_type), llm_endpoint(value, provider_type, "models")
