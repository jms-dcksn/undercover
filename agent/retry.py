"""One bounded retry layer for transient provider errors."""

from http import HTTPStatus

import httpx
import openai
from langchain.agents.middleware import ModelRetryMiddleware
from langchain_core.exceptions import (
    ModelConnectionError,
    ModelError,
    ModelRateLimitError,
    ModelTimeoutError,
)


def transient(error: Exception) -> bool:
    """Retry transport errors, rate limits and server errors, never validation/auth."""
    if isinstance(
        error, (ModelConnectionError, ModelRateLimitError, ModelTimeoutError)
    ):
        return True
    if isinstance(error, ModelError):
        return error.is_retryable
    if isinstance(
        error, (TimeoutError, httpx.TransportError, openai.APIConnectionError)
    ):
        return True
    return isinstance(error, openai.APIStatusError) and (
        error.status_code == HTTPStatus.TOO_MANY_REQUESTS
        or error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR
    )


def middleware() -> ModelRetryMiddleware:
    """Allow two provider calls per model step within the caller's deadline."""
    return ModelRetryMiddleware(
        max_retries=1,
        retry_on=transient,
        on_failure="error",
        initial_delay=0.1,
        max_delay=0.1,
        jitter=False,
    )
