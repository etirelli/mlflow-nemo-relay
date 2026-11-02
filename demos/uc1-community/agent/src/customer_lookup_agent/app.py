"""FastAPI service: chat API plus a minimal web chat UI."""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import nemo_relay
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field

from customer_lookup_agent.agent import build_agent
from customer_lookup_agent.relay_runtime import configure_mlflow_routing, relay_activation
from customer_lookup_agent.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("customer_lookup_agent")

STATIC_DIR = Path(__file__).parent / "static"
settings = get_settings()
state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    state["experiment_id"] = configure_mlflow_routing(settings)
    async with relay_activation(settings):
        state["agent"] = build_agent(settings)
        log.info(
            "Agent ready: relay_mode=%s llm=%s/%s experiment=%s (%s)",
            settings.relay_mode,
            settings.llm_provider,
            settings.llm_model,
            settings.mlflow_experiment_name,
            state["experiment_id"],
        )
        yield


app = FastAPI(title="Customer Lookup Agent (UC1 demo)", lifespan=lifespan)
# The single chat page can talk to both the redacted and the baseline agent.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None


class ToolOutcome(BaseModel):
    name: str
    status: str
    content: str


class ChatResponse(BaseModel):
    reply: str
    relay_mode: str
    tool_calls: list[ToolOutcome]
    duration_ms: int
    trace_id: str | None
    mlflow_trace_url: str | None


def _experiment_url() -> str:
    return f"{settings.mlflow_public_uri}/#/experiments/{state.get('experiment_id', '')}/traces"


@app.get("/api/info")
async def info() -> dict:
    return {
        "relay_mode": settings.relay_mode,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model if settings.llm_provider != "scripted" else "scripted",
        "mlflow_experiment": settings.mlflow_experiment_name,
        "mlflow_experiment_url": _experiment_url(),
        # Browser-facing URLs of both agents, so the chat page can switch modes.
        "agents": {
            "redacted": os.environ.get("PUBLIC_REDACTED_AGENT_URL", "http://localhost:8000"),
            "baseline": os.environ.get("PUBLIC_BASELINE_AGENT_URL", "http://localhost:8001"),
        },
    }


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": "agent" in state}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    agent = state.get("agent")
    if agent is None:
        raise HTTPException(503, "agent is still starting")
    session_id = request.session_id or uuid.uuid4().hex
    started = time.perf_counter()
    # One Relay agent scope per request becomes the root span of the MLflow trace.
    # Its input and output hold the raw user message and agent reply. In redacted
    # mode, Relay sanitizes the exported copies before they leave the process.
    handle = nemo_relay.scope.push(
        "customer-lookup-request",
        nemo_relay.ScopeType.Agent,
        input={"message": request.message},
        metadata={"session.id": session_id, "demo.relay_mode": settings.relay_mode},
    )
    try:
        trace_id = nemo_relay.capture_traceparent().split("-")[1]
    except Exception:  # the trace id is informative only
        trace_id = None
    try:
        result = await agent.ainvoke({"messages": [HumanMessage(request.message)]})
    except Exception as exc:
        log.exception("agent run failed")
        nemo_relay.scope.pop(
            handle,
            output={"error": f"{type(exc).__name__}: {exc}"},
            metadata={"otel.status_code": "ERROR"},
        )
        raise HTTPException(502, f"agent run failed: {type(exc).__name__}: {exc}") from exc

    messages = result["messages"]
    tool_calls = [
        ToolOutcome(name=m.name or "tool", status=getattr(m, "status", "success"), content=str(m.content))
        for m in messages
        if isinstance(m, ToolMessage)
    ]
    reply = next(
        (str(m.content) for m in reversed(messages) if isinstance(m, AIMessage) and m.content),
        "(no reply)",
    )
    nemo_relay.scope.pop(handle, output={"reply": reply}, metadata={"otel.status_code": "OK"})
    await nemo_relay.subscribers.flush_async()
    return ChatResponse(
        reply=reply,
        relay_mode=settings.relay_mode,
        tool_calls=tool_calls,
        duration_ms=int((time.perf_counter() - started) * 1000),
        trace_id=trace_id,
        mlflow_trace_url=(
            f"{settings.mlflow_public_uri}/#/experiments/{state['experiment_id']}/traces"
            f"?selectedEvaluationId=tr-{trace_id}"
            if trace_id
            else _experiment_url()
        ),
    )


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
