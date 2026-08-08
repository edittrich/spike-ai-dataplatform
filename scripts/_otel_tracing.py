#!/usr/bin/env python3
"""
===============================================================================
Real OpenTelemetry Tracing Setup
===============================================================================
Configures the process-global OTel TracerProvider once, exporting real spans
via OTLP/gRPC to the `otel_collector` service (which forwards to `tempo` for
storage and TraceQL querying through Grafana). This is Part 5 item 2 in the
hardening plan: `scripts/llmops_telemetry.py` has claimed "OpenTelemetry-
Compatible JSON Trace Spans" in its own docstring since it was written, but
that was only ever a JSON dict shaped like a span -- no OTel SDK import
anywhere, no exporter, nothing leaving the process. This module is what makes
that claim actually true.

Design choices, and why:
  - Fails OPEN, not closed, by design -- unlike scripts/_embedding_backend.py's
    fail-closed default. A missing/unreachable collector must never break a
    tool call; it should just mean traces don't get exported. The OTel SDK's
    BatchSpanProcessor already behaves this way natively (export failures are
    logged and dropped in a background thread, never raised to the caller),
    so nothing extra is needed here beyond not raising on *setup* either.
  - OTEL_TRACES_ENABLED=0 opts out entirely (skips configuring a real
    exporter, leaving the OTel API's own no-op default in place) for anyone
    who doesn't want to run the extra otel_collector/tempo containers --
    every span-creating call site in this codebase is written to work
    identically either way, since the OTel API is safe to call with no
    configured backend.
  - Configures the global TracerProvider exactly once per process
    (idempotent) so every module that calls trace.get_tracer(__name__)
    anywhere in this codebase shares one export pipeline, rather than each
    needing its own setup.

IMPORTANT for callers: OTEL_EXPORTER_OTLP_ENDPOINT/OTEL_TRACES_ENABLED below
are read at *import time*, so this module must be imported *after*
`scripts._dotenv_boot.load_env()` has run in the importing script -- same
caveat as `_neo4j_conn.py`/`_openmetadata_client.py`/`_embedding_backend.py`.
===============================================================================
"""

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger("OTelTracing")

TRACES_ENABLED = os.getenv("OTEL_TRACES_ENABLED", "1").strip() == "1"
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4317")
SERVICE_NAME_VALUE = os.getenv("OTEL_SERVICE_NAME", "ai-dataplatform-mcp-server")

_configured = False


def configure_tracing():
    """Idempotently installs a real TracerProvider as the OTel global default.
    Safe to call multiple times (only the first call has any effect) and
    safe to call even when no collector is reachable -- span export failures
    happen in BatchSpanProcessor's background thread, never here."""
    global _configured
    if _configured:
        return
    _configured = True

    if not TRACES_ENABLED:
        logger.info("OTel tracing disabled (OTEL_TRACES_ENABLED=0) -- spans will be created but never exported.")
        return

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: SERVICE_NAME_VALUE}))
    # timeout=5: bounds each export attempt (including the gRPC exporter's
    # own internal retries on transient errors like UNAVAILABLE) to 5s --
    # left at the client library's default (10s, itself retried against
    # by BatchSpanProcessor's own shutdown flush), a process with no
    # collector reachable at all took ~7s longer to exit than one with
    # tracing disabled, on every single run. 5s per export attempt, plus a
    # matching export_timeout_millis on the processor below so the one
    # flush-and-retry attempt at process shutdown is bounded the same way,
    # keeps the "collector isn't running" case fast without giving up on a
    # collector that's merely slow to answer a single request.
    exporter = OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True, timeout=5)
    provider.add_span_processor(BatchSpanProcessor(exporter, export_timeout_millis=5000))
    trace.set_tracer_provider(provider)
    logger.info(f"OTel tracing configured: exporting to {OTLP_ENDPOINT} as service '{SERVICE_NAME_VALUE}'.")


def get_tracer(name: str):
    """Returns a tracer for `name` (conventionally __name__). Configures
    tracing on first use if it hasn't been already -- callers don't need to
    remember to call configure_tracing() themselves."""
    configure_tracing()
    return trace.get_tracer(name)
