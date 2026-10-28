"""The LLM edges: prose in, structured request out; result in, prose out.

The model is never on the hot path. It does two jobs, both deterministic in
shape and both validated:

1. `request_from_text` — turn a sentence into a request document, then run it
   through the same strict validator a hand-written TOML file goes through.
2. `justify` — explain a computed result in prose. It cannot change numbers
   because it only sees the rendered payload and its output is printed, never
   merged back.

Anything the model returns is data. It never reaches a price, a sum or a gate.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Protocol

from .config import Request
from .errors import LLMError

DEFAULT_TIMEOUT_SECONDS = 300

PROMPT_TEMPLATE = """You translate a shopping request into JSON for a tool.
Return ONLY a JSON object, no prose, no markdown fence.

Schema:
{{
  "meta": {{"name": "<short name>", "notes": "<optional>"}},
  "items": [
    {{
      "label": "<short unique slug>",
      "query": "<Polish Allegro search query>",
      "quantity": <int >= 1>,
      "max_price_grosze": <int, PLN * 100>,
      "allow_used": <true|false>,
      "required_specs": {{"<param>": "<value>"}},
      "min_rating": <number 1..5 or omit>
    }}
  ]
}}

Rules:
- Prices in grosze (45.99 zl => 4599).
- allowed condition: if the user did not say used/outlet/refurbished, set allow_used=false.
- required_specs only for constraints the user actually stated (model, size, voltage).
- Never invent a budget the user did not state: omit the item rather than guessing.

Request:
{text}
"""

JUSTIFY_TEMPLATE = """Explain this shopping plan to the person who asked for it.

Use only the facts in the JSON. Do not add prices, sellers or specs that are not
there. Do not recommend anything outside the plan. Three short paragraphs:
what was chosen, why it won, and what would change the answer.

Plan:
{payload}
"""


class Runner(Protocol):
    def __call__(self, prompt: str, model: str | None = None) -> str: ...


def run_opencode(prompt: str, model: str | None = None) -> str:
    """One `opencode run` invocation. No API keys, no SDK, no retries."""
    command = ["opencode", "run"]
    if model:
        command += ["--model", model]
    command.append(prompt)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as e:
        raise LLMError("opencode is not on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise LLMError(f"opencode timed out after {DEFAULT_TIMEOUT_SECONDS}s") from e
    if completed.returncode != 0:
        raise LLMError(
            f"opencode exited {completed.returncode}",
            detail=completed.stderr.strip()[:500] or None,
        )
    return completed.stdout


def _extract_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("model answer contains no JSON object")
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"model answer is not valid JSON: {e}") from e
    if not isinstance(value, dict):
        raise LLMError("model answer must be a JSON object")
    return value


def request_from_text(
    text: str, *, runner: Runner = run_opencode, model: str | None = None
) -> Request:
    """Prose -> validated Request. Invalid output fails; it is never repaired."""
    if not text.strip():
        raise LLMError("empty request text")
    answer = runner(PROMPT_TEMPLATE.format(text=text.strip()), model)
    payload = _extract_json_object(answer)
    missing_budget = [
        item.get("label")
        for item in payload.get("items", [])
        if not isinstance(item, dict) or int(item.get("max_price_grosze", 0) or 0) <= 0
    ]
    if missing_budget:
        raise LLMError(
            f"no budget stated for items {missing_budget}",
            detail="state a maximum price; the tool will not invent one",
        )
    return Request.from_toml(payload)


def justify(
    payload: dict[str, Any], *, runner: Runner = run_opencode, model: str | None = None
) -> str:
    """Explain a rendered run payload. Output is for humans; nothing merges back."""
    answer = runner(
        JUSTIFY_TEMPLATE.format(payload=json.dumps(payload, ensure_ascii=False, indent=2)), model
    )
    text = answer.strip()
    if not text:
        raise LLMError("model returned an empty justification")
    return text


def request_to_toml(request: Request) -> str:
    """Emit the same document the validator accepts, so the output is editable."""
    lines = ["[meta]", f'name = "{_escape(request.name)}"']
    if request.notes:
        lines.append(f'notes = "{_escape(request.notes)}"')
    lines.append("")
    for item in request.items:
        lines.append("[[items]]")
        lines.append(f'label = "{_escape(item.label)}"')
        lines.append(f'query = "{_escape(item.query)}"')
        lines.append(f"quantity = {item.quantity}")
        lines.append(f"max_price_grosze = {int(item.max_price_grosze)}")
        lines.append(f"allow_used = {'true' if item.allow_used else 'false'}")
        if item.required_specs:
            pairs = ", ".join(
                f'{_escape(key)} = "{_escape(value)}"' for key, value in item.required_specs.items()
            )
            lines.append(f"required_specs = {{ {pairs} }}")
        if item.min_rating is not None:
            lines.append(f"min_rating = {item.min_rating}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
