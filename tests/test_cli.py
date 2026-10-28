from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar

import pytest

from allegro_shopping.cli import main
from allegro_shopping.errors import FetchFailure


def test_version_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "allegro-shopping" in capsys.readouterr().out


def test_cache_stats_on_empty_hoard(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--db", str(tmp_path / "hoard.db"), "cache", "stats"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"offers": 0, "sellers": 0, "products": 0, "searches": 0}


def test_missing_request_file_is_a_config_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--db", str(tmp_path / "hoard.db"), "plan", str(tmp_path / "absent.toml")])
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_unknown_item_in_explain_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request = tmp_path / "request.toml"
    request.write_text(
        """
[meta]
name = "one"

[[items]]
label = "a"
query = "q"
quantity = 1
max_price_grosze = 100
allow_used = false
""",
        encoding="utf-8",
    )
    code = main(
        [
            "--db",
            str(tmp_path / "hoard.db"),
            "explain",
            "1000001",
            "--request",
            str(request),
            "--item",
            "nope",
        ]
    )
    assert code == 1
    assert "no item" in capsys.readouterr().err


def test_doctor_reports_every_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--db", str(tmp_path / "hoard.db"), "doctor"])
    out = capsys.readouterr().out
    for name in ("python", "rules", "hoard", "chrome", "playwright", "profile"):
        assert f"] {name}:" in out
    assert code in (0, 1, 2)


FIXTURES = Path(__file__).parent / "fixtures" / "allegro"
LISTING = (FIXTURES / "listing-wago.html").read_text(encoding="utf-8")
OFFER = (FIXTURES / "offer-wago-221.html").read_text(encoding="utf-8")


class FakeSource:
    """Stands in for PlaywrightPageSource: same fetch/open surface, no Chrome."""

    instances: ClassVar[list[FakeSource]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.fetched: list[str] = []
        self.markup: dict[str, str] = {}
        FakeSource.instances.append(self)

    @contextmanager
    def open(self):  # type: ignore[no-untyped-def]
        yield self

    def fetch(self, url: str, ready_selector: str) -> str:
        del ready_selector
        self.fetched.append(url)
        if url not in self.markup:
            raise FetchFailure(f"no fixture for {url}")
        return self.markup[url]


@pytest.fixture
def fake_pages(monkeypatch: pytest.MonkeyPatch) -> type[FakeSource]:
    FakeSource.instances.clear()
    monkeypatch.setattr("allegro_shopping.cli.PlaywrightPageSource", FakeSource)
    return FakeSource


def request_file(tmp_path: Path) -> Path:
    path = tmp_path / "request.toml"
    path.write_text(
        """
[meta]
name = "Wago restock"

[[items]]
label = "wago-3"
query = "wago 221"
quantity = 1
max_price_grosze = 6000
allow_used = false
""",
        encoding="utf-8",
    )
    return path


def test_search_with_fixture_prints_table(tmp_path: Path, fake_pages, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    class ListingSource(FakeSource):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self.markup = {"https://allegro.pl/listing?string=wago+221": LISTING}

    monkeypatch.setattr("allegro_shopping.cli.PlaywrightPageSource", ListingSource)
    code = main(["--db", str(tmp_path / "hoard.db"), "search", "wago 221"])
    out = capsys.readouterr().out
    assert code == 0
    assert "18330930177" in out
    assert "skipped 1 cards" in out


def test_plan_writes_report(tmp_path: Path, fake_pages, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    request = request_file(tmp_path)
    offers = {
        "https://allegro.pl/oferta/18330930177": OFFER,
        "https://allegro.pl/oferta/18462382353": OFFER,
        "https://allegro.pl/oferta/18529923195": OFFER,
    }

    class PlanSource(FakeSource):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self.markup = {"https://allegro.pl/listing?string=wago+221": LISTING, **offers}

    monkeypatch.setattr("allegro_shopping.cli.PlaywrightPageSource", PlanSource)
    out_dir = tmp_path / "runs"
    code = main(
        ["--db", str(tmp_path / "hoard.db"), "plan", str(request), "--out", str(out_dir)]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert "# Wago restock" in captured.out
    assert list(out_dir.glob("*.md")) and list(out_dir.glob("*.json"))


def test_explain_prints_term_breakdown(tmp_path: Path, fake_pages, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    request = request_file(tmp_path)
    offers = {
        "https://allegro.pl/oferta/18330930177": OFFER,
        "https://allegro.pl/oferta/18462382353": OFFER,
        "https://allegro.pl/oferta/18529923195": OFFER,
    }

    class PlanSource(FakeSource):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self.markup = {"https://allegro.pl/listing?string=wago+221": LISTING, **offers}

    monkeypatch.setattr("allegro_shopping.cli.PlaywrightPageSource", PlanSource)
    db = str(tmp_path / "hoard.db")
    main(["--db", db, "plan", str(request), "--out", str(tmp_path / "runs")])
    capsys.readouterr()
    code = main(
        ["--db", db, "explain", "18330930177", "--request", str(request), "--item", "wago-3"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "weight" in out and "weakest term" in out


def test_capture_writes_the_page(tmp_path: Path, fake_pages, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    class CaptureSource(FakeSource):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self.markup = {"https://allegro.pl/listing?string=wago": LISTING}

    monkeypatch.setattr("allegro_shopping.cli.PlaywrightPageSource", CaptureSource)
    out = tmp_path / "fixture.html"
    code = main(
        [
            "--db",
            str(tmp_path / "hoard.db"),
            "capture",
            "https://allegro.pl/listing?string=wago",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert out.read_text(encoding="utf-8") == LISTING


def test_offer_without_id_is_a_parse_failure(
    tmp_path: Path, fake_pages, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    class EmptySource(FakeSource):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self.markup = {
                "https://allegro.pl/listing?string=wago+221": "<html><body>nothing</body></html>"
            }

    monkeypatch.setattr("allegro_shopping.cli.PlaywrightPageSource", EmptySource)
    code = main(["--db", str(tmp_path / "hoard.db"), "search", "wago 221"])
    assert code == 5


def test_verify_reports_drift(tmp_path: Path, fake_pages, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    request = request_file(tmp_path)
    offers = {
        "https://allegro.pl/oferta/18330930177": OFFER,
        "https://allegro.pl/oferta/18462382353": OFFER,
        "https://allegro.pl/oferta/18529923195": OFFER,
    }
    changed = OFFER.replace('"amount": "45.99"', '"amount": "49.99"')

    class PlanSource(FakeSource):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self.markup = {"https://allegro.pl/listing?string=wago+221": LISTING, **offers}

    monkeypatch.setattr("allegro_shopping.cli.PlaywrightPageSource", PlanSource)
    db = str(tmp_path / "hoard.db")
    main(["--db", db, "plan", str(request), "--out", str(tmp_path / "runs")])
    run_file = next((tmp_path / "runs").glob("*.json"))

    class DriftSource(FakeSource):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self.markup = {url: changed for url in offers}

    monkeypatch.setattr("allegro_shopping.cli.PlaywrightPageSource", DriftSource)
    code = main(["--db", db, "verify", str(run_file)])
    captured = capsys.readouterr()
    assert code == 9
    assert "DRIFT" in captured.out
    assert "re-plan" in captured.err


def test_request_from_text_writes_editable_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    import json as _json

    from allegro_shopping import llm

    payload = {
        "meta": {"name": "wago"},
        "items": [
            {
                "label": "wago-3",
                "query": "wago 221-413",
                "quantity": 1,
                "max_price_grosze": 6000,
                "allow_used": False,
            }
        ],
    }
    monkeypatch.setattr(llm, "run_opencode", lambda prompt, model=None: _json.dumps(payload))
    out = tmp_path / "request.toml"
    code = main(["request-from-text", "one wago up to 60 zl", "--out", str(out)])
    assert code == 0
    assert "max_price_grosze = 6000" in out.read_text(encoding="utf-8")
    # The file we wrote is accepted by the real loader.
    from allegro_shopping.config import load_request

    assert int(load_request(out).items[0].max_price_grosze) == 6000


def test_request_from_text_rejects_a_budgetless_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    import json as _json

    from allegro_shopping import llm

    payload = {
        "meta": {"name": "wago"},
        "items": [
            {
                "label": "wago-3",
                "query": "wago",
                "quantity": 1,
                "max_price_grosze": 0,
                "allow_used": False,
            }
        ],
    }
    monkeypatch.setattr(llm, "run_opencode", lambda prompt, model=None: _json.dumps(payload))
    code = main(["request-from-text", "buy wago"])
    assert code == 10
    assert "no budget" in capsys.readouterr().err


def test_justify_prints_model_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # type: ignore[no-untyped-def]
    from allegro_shopping import llm

    run_file = tmp_path / "run.json"
    run_file.write_text('{"basket": null}', encoding="utf-8")
    monkeypatch.setattr(llm, "run_opencode", lambda prompt, model=None: "It is cheaper.")
    assert main(["justify", str(run_file)]) == 0
    assert "It is cheaper." in capsys.readouterr().out


def test_shop_dry_run_prints_the_parsed_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    import json as _json

    from allegro_shopping import llm

    payload = {
        "meta": {"name": "wago"},
        "items": [
            {
                "label": "wago-3",
                "query": "wago 221-413",
                "quantity": 2,
                "max_price_grosze": 6000,
                "allow_used": False,
            }
        ],
    }
    monkeypatch.setattr(llm, "run_opencode", lambda prompt, model=None: _json.dumps(payload))
    code = main(["shop", "dwa wago do 60 zl", "--dry-run"])
    captured = capsys.readouterr()
    assert code == 0
    assert "quantity = 2" in captured.err


def test_shop_runs_and_writes_a_report(
    tmp_path: Path, fake_pages, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    import json as _json

    from allegro_shopping import llm

    payload = {
        "meta": {"name": "wago"},
        "items": [
            {
                "label": "wago-3",
                "query": "wago 221",
                "quantity": 1,
                "max_price_grosze": 6000,
                "allow_used": False,
            }
        ],
    }
    offers = {
        "https://allegro.pl/oferta/18330930177": OFFER,
        "https://allegro.pl/oferta/18462382353": OFFER,
        "https://allegro.pl/oferta/18529923195": OFFER,
    }

    class ShopSource(FakeSource):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self.markup = {"https://allegro.pl/listing?string=wago+221": LISTING, **offers}

    monkeypatch.setattr("allegro_shopping.cli.PlaywrightPageSource", ShopSource)
    monkeypatch.setattr(llm, "run_opencode", lambda prompt, model=None: _json.dumps(payload))
    out_dir = tmp_path / "runs"
    code = main(["--db", str(tmp_path / "h.db"), "shop", "one wago", "--out", str(out_dir)])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert "# wago" in captured.out
    assert list(out_dir.glob("*.md"))
