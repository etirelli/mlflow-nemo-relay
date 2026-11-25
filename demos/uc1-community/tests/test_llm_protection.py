"""Opt-in LLM protection: Relay request intercepts keep the SSN out of the LLM request.

The test drives the real FastAPI app (MLflow routing stubbed) with the scripted
model, records every message the model receives, and reads the OTLP export.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace

from fastapi.testclient import TestClient

from conftest import plugins_file
from customer_lookup_agent import app as app_module
from customer_lookup_agent.customer_db import ALL_SYNTHETIC_SSNS, SUCCESS_SSN
from customer_lookup_agent.llm_protection import MODEL_NOTE
from customer_lookup_agent.scripted_model import ScriptedCustomerLookupModel
from customer_lookup_agent.settings import get_settings

SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def has_ssn(text: str) -> bool:
    return bool(SSN_RE.search(text)) or any(s.replace("-", "") in text for s in ALL_SYNTHETIC_SSNS)


def attributes(span: dict) -> dict:
    return {a["key"]: next(iter(a["value"].values()), None) for a in span.get("attributes", [])}


def test_protected_request_keeps_the_ssn_from_the_llm(otlp_receiver, monkeypatch):
    seen: list[str] = []
    original = ScriptedCustomerLookupModel._generate

    def spy(self, messages, *args, **kwargs):
        seen.extend(f"{m.content} {json.dumps(getattr(m, 'tool_calls', None) or [])}" for m in messages)
        return original(self, messages, *args, **kwargs)

    monkeypatch.setattr(ScriptedCustomerLookupModel, "_generate", spy)
    settings = replace(get_settings(), relay_mode="redacted", relay_plugins_file=plugins_file("redacted"))
    monkeypatch.setattr(app_module, "settings", settings)
    monkeypatch.setattr(app_module, "configure_mlflow_routing", lambda _settings: "42")
    message = f"Please look up the customer with SSN {SUCCESS_SSN}."
    with TestClient(app_module.app) as client:
        body = client.post("/api/chat", json={"message": message, "protect_llm": True}).json()

    # The tool got the real SSN, and the user sees real values.
    assert body["tool_calls"][0]["status"] == "success"
    assert SUCCESS_SSN in body["reply"] and "SSN_REF_" not in body["reply"]
    # The model only ever saw the reference, in the user message and the echoed tool result.
    assert seen and not any(has_ssn(text) for text in seen)
    assert any('"ssn": "SSN_REF_1"' in text for text in seen)
    # The LLM spans record the rewritten request; without protection they would show [REDACTED-SSN].
    llm = [s for s in otlp_receiver.spans if attributes(s).get("openinference.span.kind") == "LLM"]
    requests = [attributes(s)["input.value"].replace(MODEL_NOTE, "") for s in llm]
    assert requests and all("SSN_REF_1" in r and "[REDACTED-SSN]" not in r for r in requests)
