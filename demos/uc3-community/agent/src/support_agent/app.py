"""FastAPI service: chat API plus the web chat UI."""

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
from prometheus_client import make_asgi_app
from pydantic import BaseModel, Field

from support_agent import metrics, refunds
from support_agent.agent import build_agent
from support_agent.policy import RefundPolicy, is_blocked
from support_agent.relay_runtime import configure_mlflow_routing, relay_activation
from support_agent.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("support_agent")

STATIC_DIR = Path(__file__).parent / "static"
settings = get_settings()
policy = RefundPolicy(settings.policy_version)
state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    state["experiment_id"] = configure_mlflow_routing(settings)
    async with relay_activation(settings):
        policy.register()
        state["agent"] = build_agent(settings)
        log.info(
            "Agent ready: agent=%s policy=%s (%s) llm=%s/%s experiment=%s (%s)",
            settings.agent_version,
            policy.name,
            policy.spec.summary,
            settings.llm_provider,
            settings.llm_model,
            settings.mlflow_experiment_name,
            state["experiment_id"],
        )
        yield


app = FastAPI(title="Support Agent (UC3 policy validation)", lifespan=lifespan)
# Prometheus scrape endpoint: latency, guardrail decisions, process CPU and memory.
app.mount("/metrics", make_asgi_app())
# The chat page can talk to both agent versions.
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
    # "success", "error" (the tool ran and failed) or "blocked" (Relay policy, never ran)
    status: str
    content: str


class ChatResponse(BaseModel):
    reply: str
    agent_version: str
    policy: str
    tool_calls: list[ToolOutcome]
    refunds_executed: list[dict]
    duration_ms: int
    trace_id: str | None
    mlflow_trace_url: str | None


def _experiment_url() -> str:
    return f"{settings.mlflow_public_uri}/#/experiments/{state.get('experiment_id', '')}/traces"


@app.get("/api/info")
async def info() -> dict:
    return {
        "agent_version": settings.agent_version,
        "policy": policy.name,
        "refund_limit": policy.limit,
        "policy_version": policy.version,
        "policy_summary": policy.spec.summary,
        "policies": {
            v: os.environ.get(f"PUBLIC_POLICY_{v.upper()}_URL", f"http://localhost:{8000 + i}")
            for i, v in enumerate(("v1", "v2", "v3"))
        },
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model if settings.llm_provider != "scripted" else "scripted",
        "mlflow_experiment": settings.mlflow_experiment_name,
        "mlflow_experiment_url": _experiment_url(),
    }


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": "agent" in state}


def _outcome(m: ToolMessage) -> ToolOutcome:
    content = str(m.content)
    status = "blocked" if is_blocked(content) else getattr(m, "status", "success")
    return ToolOutcome(name=m.name or "tool", status=status, content=content)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    agent = state.get("agent")
    if agent is None:
        raise HTTPException(503, "agent is still starting")
    session_id = request.session_id or uuid.uuid4().hex
    started = time.perf_counter()
    request_id = refunds.start_request()
    # One Relay agent scope per request = the root span of the MLflow trace. The agent
    # and policy versions travel with it, so MLflow can compare versions.
    handle = nemo_relay.scope.push(
        "support-request",
        nemo_relay.ScopeType.Agent,
        input={"message": request.message},
        metadata={
            "session.id": session_id,
            "demo.agent_version": settings.agent_version,
            "demo.policy": policy.name,
        },
    )
    try:
        trace_id = nemo_relay.capture_traceparent().split("-")[1]
    except Exception:
        trace_id = None
    try:
        result = await agent.ainvoke({"messages": [HumanMessage(request.message)]})
    except Exception as exc:
        policy.release(request_id)
        metrics.REQUEST_SECONDS.labels(metrics.POLICY).observe(time.perf_counter() - started)
        log.exception("agent run failed")
        nemo_relay.scope.pop(
            handle, output={"error": f"{type(exc).__name__}: {exc}"}, metadata={"otel.status_code": "ERROR"}
        )
        raise HTTPException(502, f"agent run failed: {type(exc).__name__}: {exc}") from exc

    messages = result["messages"]
    tool_calls = [_outcome(m) for m in messages if isinstance(m, ToolMessage)]
    reply = next(
        (str(m.content) for m in reversed(messages) if isinstance(m, AIMessage) and m.content),
        "(no reply)",
    )
    executed = refunds.executed_by(request_id)
    policy.release(request_id)
    metrics.REQUEST_SECONDS.labels(metrics.POLICY).observe(time.perf_counter() - started)
    nemo_relay.scope.pop(
        handle,
        output={"reply": reply, "refunds_executed": len(executed)},
        metadata={"otel.status_code": "OK"},
    )
    await nemo_relay.subscribers.flush_async()
    return ChatResponse(
        reply=reply,
        agent_version=settings.agent_version,
        policy=policy.name,
        tool_calls=tool_calls,
        refunds_executed=executed,
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
