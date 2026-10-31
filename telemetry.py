"""Optional tracing shared by HTTP transport and agent execution."""

import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from functools import cache

from dotenv import load_dotenv
from langfuse import Langfuse, LangfuseSpan, propagate_attributes
from langfuse.langchain import CallbackHandler
from langfuse.types import MaskOtelSpansParams, MaskOtelSpansResult, OtelSpanPatch
from opentelemetry import context, trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

load_dotenv()

SAFE_ATTRIBUTES = {
    "session.id",
    "langfuse.trace.name",
    "langfuse.trace.tags",
    "langfuse.observation.type",
    "langfuse.observation.level",
    "langfuse.observation.model.name",
    "langfuse.observation.usage_details",
    "langfuse.observation.cost_details",
    "langfuse.observation.completion_start_time",
    "langfuse.environment",
    "langfuse.release",
    "langfuse.version",
    "langfuse.internal.as_root",
    "langfuse.internal.is_app_root",
}
SAFE_METADATA = {"run_id", "parent_id", "claim_id", "state", "error_type"}
ROOT_NAMES = {"process-queue", "process-named-claim", "process-claim"}


def mask_spans(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult:
    """Export only operational fields unless content capture is explicitly enabled."""
    patches = {}
    for identifier, span in params.spans.items():
        allowed = set(SAFE_ATTRIBUTES)
        allowed.update(
            key
            for key in span.attributes
            if key.startswith(
                ("langfuse.observation.metadata.", "langfuse.trace.metadata.")
            )
            and key.rsplit(".", 1)[-1] in SAFE_METADATA
        )
        if span.name in ROOT_NAMES:
            allowed.update(
                {"langfuse.observation.input", "langfuse.observation.output"}
            )
        patches[identifier] = OtelSpanPatch(
            delete_attributes=tuple(
                key for key in span.attributes if key not in allowed
            )
        )
    return MaskOtelSpansResult(span_patches=patches)


def enabled() -> bool:
    """Require explicit opt-in and a complete project configuration."""
    return os.getenv("LANGFUSE_TRACING_ENABLED", "false").lower() == "true" and all(
        os.getenv(key)
        for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")
    )


@cache
def _client() -> Langfuse:
    return Langfuse(
        environment=os.getenv("LANGFUSE_TRACING_ENVIRONMENT", "development"),
        mask_otel_spans=(
            None
            if os.getenv("LANGFUSE_CAPTURE_CONTENT", "false").lower() == "true"
            else mask_spans
        ),
    )


def callbacks() -> list:
    """Create a fresh callback handler for each conversation."""
    if not enabled():
        return []
    _client()
    handler = CallbackHandler(public_key=os.environ["LANGFUSE_PUBLIC_KEY"])
    handler.run_inline = True
    return [handler]


@contextmanager
def observation(
    name: str, session_id: str, metadata: dict[str, str], traceparent: str | None = None
) -> Iterator[LangfuseSpan | None]:
    """Keep background work nested across HTTP without recording raw exceptions."""
    if not enabled():
        yield None
        return
    token = context.attach(
        TraceContextTextMapPropagator().extract({"traceparent": traceparent})
        if traceparent
        else context.get_current()
    )
    stack = ExitStack()
    try:
        span = stack.enter_context(
            _client().start_as_current_observation(name=name, input=metadata)
        )
        stack.enter_context(
            propagate_attributes(
                session_id=session_id, tags=["undercover"], metadata=metadata
            )
        )
        try:
            yield span
        except BaseException as error:
            span.update(level="ERROR", metadata={"error_type": type(error).__name__})
            raise
    finally:
        stack.close()
        context.detach(token)


def inject_headers(headers) -> None:
    """Propagate only W3C trace context to the configured backend."""
    if enabled() and trace.get_current_span().get_span_context().is_valid:
        TraceContextTextMapPropagator().inject(headers)


def flush() -> None:
    """Drain script events while allowing another invocation in the same process."""
    if _client.cache_info().currsize:
        _client().flush()


def shutdown() -> None:
    """Drain initialized tracing on backend or script exit."""
    if _client.cache_info().currsize:
        _client().shutdown()
        _client.cache_clear()
