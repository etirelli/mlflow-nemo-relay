"""Keep Social Security numbers out of the LLM request with NeMo Relay request intercepts.

The ``pii_redaction`` plugin sanitizes telemetry only: the LLM itself still
receives the SSN in the prompt. When a chat request opts in, two scope-local
Relay intercepts close that gap for the lifetime of the request scope:

* the LLM request intercept replaces every SSN in the outbound request (the
  user message and tool results echoed back to the model) with a reference
  such as ``SSN_REF_1``, and tells the model to pass references to tools;
* the tool request intercept swaps references back before the tool runs, so
  tools still receive the real value.

References are per request and never leave the process. Relay records the
rewritten request on the LLM span, so the trace shows what the model saw, and
adds a ``relay.ssn_tokenized`` event to that span.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import nemo_relay

# Same shape as the regex profile in the Relay redaction policy.
SSN_PATTERN = re.compile(r"\b(\d{3})[- ](\d{2})[- ](\d{4})\b")
# Models sometimes change the case or wrap a reference in brackets.
REFERENCE_PATTERN = re.compile(r"[\[<]?\bSSN[_-]REF[_-](\d+)\b[\]>]?", re.IGNORECASE)
TOKENIZED_MARK = "relay.ssn_tokenized"
MODEL_NOTE = (
    "Social Security numbers in this conversation were replaced with references such as "
    "SSN_REF_1 before reaching you. Treat each reference as the customer's SSN and pass it "
    "to tools exactly as written."
)


class SsnVault:
    """Per-request mapping between SSNs and the references the LLM sees."""

    def __init__(self) -> None:
        self._references: dict[str, str] = {}
        self._ssns: dict[str, str] = {}

    def __len__(self) -> int:
        return len(self._references)

    def tokenize(self, value: Any) -> Any:
        """Replace every SSN in a JSON value with its reference."""
        return _map_strings(value, lambda text: SSN_PATTERN.sub(self._reference, text))

    def detokenize(self, value: Any) -> Any:
        """Replace every known reference in a JSON value with its SSN."""
        return _map_strings(value, lambda text: REFERENCE_PATTERN.sub(self._ssn, text))

    def _reference(self, match: re.Match) -> str:
        ssn = "-".join(match.groups())
        if ssn not in self._references:
            reference = f"SSN_REF_{len(self._references) + 1}"
            self._references[ssn] = reference
            self._ssns[reference] = ssn
        return self._references[ssn]

    def _ssn(self, match: re.Match) -> str:
        return self._ssns.get(f"SSN_REF_{match.group(1)}", match.group(0))


def protect_scope(handle: nemo_relay.ScopeHandle, vault: SsnVault) -> None:
    """Register both intercepts on ``handle``. Relay removes them when the scope is popped."""
    scope_local = nemo_relay.scope_local
    scope_local.register_llm_request(handle, "ssn-tokenize", 10, False, _tokenize_llm_request(vault))
    scope_local.register_tool_request(handle, "ssn-detokenize", 10, False, _detokenize_tool_args(vault))


def _tokenize_llm_request(vault: SsnVault) -> Callable[..., nemo_relay.LLMRequestInterceptOutcome]:
    def intercept(
        _name: str, request: nemo_relay.LLMRequest, annotated: nemo_relay.AnnotatedLLMRequest | None
    ) -> nemo_relay.LLMRequestInterceptOutcome:
        if annotated is None:
            request = nemo_relay.LLMRequest(request.headers, vault.tokenize(request.content))
        else:
            # With a request codec active, Relay builds the provider body from the annotation.
            annotated.messages = _with_note(vault.tokenize(annotated.messages), vault)
            if annotated.instructions is not None:
                annotated.instructions = vault.tokenize(annotated.instructions)
        marks = []
        if vault:
            marks.append(nemo_relay.PendingMarkSpec(TOKENIZED_MARK, data={"ssn_references": len(vault)}))
        return nemo_relay.LLMRequestInterceptOutcome(request, annotated, marks)

    return intercept


def _detokenize_tool_args(vault: SsnVault) -> Callable[[str, Any], Any]:
    def intercept(_tool_name: str, args: Any) -> Any:
        return vault.detokenize(args)

    return intercept


def _with_note(messages: list[dict], vault: SsnVault) -> list[dict]:
    if not vault:
        return messages
    for message in messages:
        if message.get("role") == "system" and isinstance(message.get("content"), str):
            message["content"] = f"{message['content']}\n\n{MODEL_NOTE}"
            return messages
    return [{"role": "system", "content": MODEL_NOTE}, *messages]


def _map_strings(value: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [_map_strings(item, fn) for item in value]
    if isinstance(value, dict):
        return {key: _map_strings(item, fn) for key, item in value.items()}
    return value
