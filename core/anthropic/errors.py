"""User-facing error formatting shared by API, providers, and integrations."""

import httpx
import openai


def get_user_facing_error_message(
    e: Exception,
    *,
    read_timeout_s: float | None = None,
) -> str:
    """Return a readable, non-empty error message for users.

    Known transport and OpenAI SDK exception types are mapped to stable wording
    before falling back to ``str(e)``, so empty or noisy SDK messages do not skip
    the mapped path.
    """
    if isinstance(e, httpx.ReadTimeout):
        if read_timeout_s is not None:
            return f"Provider request timed out after {read_timeout_s:g}s."
        return "Provider request timed out."
    if isinstance(e, httpx.ConnectTimeout):
        return "Could not connect to provider."
    if isinstance(e, TimeoutError):
        if read_timeout_s is not None:
            return f"Provider request timed out after {read_timeout_s:g}s."
        return "Request timed out."

    if isinstance(e, openai.RateLimitError):
        return "Provider rate limit reached. Please retry shortly."
    if isinstance(e, openai.AuthenticationError):
        return "Provider authentication failed. Check API key."
    if isinstance(e, openai.BadRequestError):
        # Check if error message contains image/vision-related info
        raw_msg = str(e).lower()
        if any(
            kw in raw_msg for kw in ["image", "vision", "multimodal", "content_policy"]
        ):
            base_msg = "Invalid request sent to provider."
            # Extract relevant part of error message
            raw_str = str(e)
            if "image" in raw_msg:
                return f"{base_msg} The model may not support image input. Use a vision-capable model (e.g., Qwen-VL, Llama 3.2 Vision, GPT-4o)."
            if "vision" in raw_msg or "multimodal" in raw_msg:
                return f"{base_msg} {raw_str[:150]}"
        return "Invalid request sent to provider."

    name = type(e).__name__
    status_code = getattr(e, "status_code", None)
    if name == "RateLimitError":
        return "Provider rate limit reached. Please retry shortly."
    if name == "AuthenticationError":
        return "Provider authentication failed. Check API key."
    if name == "InvalidRequestError":
        # Check if error message contains image/vision-related info
        msg = str(e).strip()
        msg_lower = msg.lower()
        if any(
            kw in msg_lower
            for kw in [
                "image",
                "vision",
                "multimodal",
                "content_policy",
                "unsupported",
                "not support",
            ]
        ):
            return f"{msg} The model may not support image input. Use a vision-capable model (e.g., Qwen-VL, Llama 3.2 Vision, GPT-4o)."
        return "Invalid request sent to provider."
    if name == "OverloadedError":
        return "Provider is currently overloaded. Please retry."
    if name == "APIError":
        if status_code in (502, 503, 504):
            return "Provider is temporarily unavailable. Please retry."
        # Check if error message or raw_error contains image/vision-related info
        msg = str(e).strip()
        msg_lower = msg.lower()
        raw_error = getattr(e, "raw_error", None)
        raw_error_str = str(raw_error).lower() if raw_error else ""
        if any(
            kw in msg_lower or kw in raw_error_str
            for kw in ["image", "vision", "multimodal", "unsupported", "not support"]
        ):
            return f"{msg} The model may not support image input. Use a vision-capable model (e.g., Qwen-VL, Llama 3.2 Vision, GPT-4o)."
        return "Provider API request failed."
    if name.endswith("ProviderError") or name == "ProviderError":
        # Check if error message or raw_error contains image/vision-related info
        msg = str(e).strip()
        msg_lower = msg.lower()
        raw_error = getattr(e, "raw_error", None)
        raw_error_str = str(raw_error).lower() if raw_error else ""
        if any(
            kw in msg_lower or kw in raw_error_str
            for kw in ["image", "vision", "multimodal", "unsupported", "not support"]
        ):
            return f"{msg} The model may not support image input. Use a vision-capable model (e.g., Qwen-VL, Llama 3.2 Vision, GPT-4o)."
        return "Provider request failed."

    message = str(e).strip()
    if message:
        # Check for image-related keywords in generic exceptions
        msg_lower = message.lower()
        if any(
            kw in msg_lower
            for kw in ["image", "vision", "multimodal", "unsupported", "not support"]
        ):
            return f"{message} The model may not support image input. Use a vision-capable model (e.g., Qwen-VL, Llama 3.2 Vision, GPT-4o)."
        return message

    return "Provider request failed unexpectedly."


def format_user_error_preview(exc: Exception, *, max_len: int = 200) -> str:
    """Truncate a user-facing error string for short chat replies."""
    return get_user_facing_error_message(exc)[:max_len]


def append_request_id(message: str, request_id: str | None) -> str:
    """Append request_id suffix when available."""
    base = message.strip() or "Provider request failed unexpectedly."
    if request_id:
        return f"{base} (request_id={request_id})"
    return base
