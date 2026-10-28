from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from allegro_shopping import llm
from allegro_shopping.config import load_request
from allegro_shopping.errors import LLMError

VALID = {
    "meta": {"name": "wago restock"},
    "items": [
        {
            "label": "wago-3",
            "query": "wago 221-413",
            "quantity": 2,
            "max_price_grosze": 6000,
            "allow_used": False,
            "required_specs": {"Model": "221-413"},
            "min_rating": 4.0,
        }
    ],
}


def runner(answer: str):
    def call(prompt: str, model: str | None = None) -> str:
        del prompt, model
        return answer

    return call


def test_request_from_text_validates_and_parses() -> None:
    request = llm.request_from_text("dwa wago 221-413 do 60 zl", runner=runner(json.dumps(VALID)))
    assert request.name == "wago restock"
    assert request.items[0].quantity == 2
    assert request.items[0].required_specs == {"Model": "221-413"}


def test_request_from_text_tolerates_code_fence() -> None:
    answer = "```json\n" + json.dumps(VALID) + "\n```"
    assert llm.request_from_text("x", runner=runner(answer)).items[0].label == "wago-3"


def test_request_from_text_rejects_non_json() -> None:
    with pytest.raises(LLMError, match="no JSON object"):
        llm.request_from_text("x", runner=runner("sure, I will buy that"))


def test_request_from_text_rejects_invented_budget() -> None:
    payload = json.loads(json.dumps(VALID))
    payload["items"][0]["max_price_grosze"] = 0
    with pytest.raises(LLMError, match="no budget"):
        llm.request_from_text("x", runner=runner(json.dumps(payload)))


def test_request_from_text_rejects_unknown_keys() -> None:
    payload = json.loads(json.dumps(VALID))
    payload["items"][0]["max_price_pln"] = 60
    with pytest.raises(Exception, match="unknown keys"):
        llm.request_from_text("x", runner=runner(json.dumps(payload)))


def test_request_to_toml_round_trips(tmp_path: Path) -> None:
    request = llm.request_from_text("x", runner=runner(json.dumps(VALID)))
    path = tmp_path / "request.toml"
    path.write_text(llm.request_to_toml(request), encoding="utf-8")
    again = load_request(path)
    assert again == request


def test_justify_rejects_empty_answer() -> None:
    with pytest.raises(LLMError, match="empty"):
        llm.justify({"basket": None}, runner=runner("   "))


def test_justify_returns_model_text() -> None:
    assert llm.justify({"basket": None}, runner=runner("It wins on price.")) == "It wins on price."


def test_run_opencode_reports_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(LLMError, match="not on PATH"):
        llm.run_opencode("hi")


def test_run_opencode_reports_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="opencode", timeout=1)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(LLMError, match="timed out"):
        llm.run_opencode("hi")


def test_run_opencode_reports_non_zero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    class Completed:
        returncode = 2
        stdout = ""
        stderr = "model not found"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Completed())
    with pytest.raises(LLMError, match="exited 2"):
        llm.run_opencode("hi")
