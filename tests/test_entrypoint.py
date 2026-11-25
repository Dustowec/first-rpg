"""Тесты точки входа: флаг --new и хилер сессии."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.storage import new_game, save_state, load_state
from scripts.generate_template import generate_template


@pytest.fixture()
def entry(monkeypatch):
    """Импортирует main.py с заглушкой run_cli (без интерактива)."""
    stub = types.ModuleType("cli.app")
    stub.run_cli = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "cli.app", stub)
    spec = importlib.util.spec_from_file_location("main_under_test", _root / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_args_defaults(entry):
    args = entry.parse_args([])
    assert args.new is False and args.seed is None and args.difficulty == "normal"


def test_parse_args_new_with_seed_and_difficulty(entry):
    args = entry.parse_args(["--new", "--seed", "42", "--difficulty", "hard"])
    assert args.new is True and args.seed == 42 and args.difficulty == "hard"


def test_start_new_game_overwrites_progress(entry, tmp_path):
    template = str(tmp_path / "t.json")
    session = str(tmp_path / "s.json")
    generate_template(template)
    old = new_game(template_path=template, session_path=session)
    old["player"]["gold"] = 999
    old["world"]["day"] = 5
    save_state(old, session)
    fresh = entry.start_new_game(session, template)
    assert fresh["player"]["gold"] == 15 and fresh["world"]["day"] == 1
    assert load_state(session, template)[0]["player"]["gold"] == 15


def test_start_new_game_applies_seed_and_difficulty(entry, tmp_path):
    template = str(tmp_path / "t.json")
    session = str(tmp_path / "s.json")
    generate_template(template)
    st = entry.start_new_game(session, template, seed=42, difficulty="hard")
    assert st["meta"]["seed"] == 42
    assert st["meta"]["difficultyMultiplier"] == 1.4
    assert len(st["map"]["nodes"]) == 25
    assert st["map"]["nodes"][0]["connections"]


def test_main_new_flag_starts_fresh(entry, tmp_path, monkeypatch):
    template = str(tmp_path / "t.json")
    session = str(tmp_path / "s.json")
    generate_template(template)
    old = new_game(template_path=template, session_path=session)
    old["player"]["gold"] = 500
    save_state(old, session)
    captured = {}
    monkeypatch.setattr(entry, "run_cli", lambda state, gd, **kw: captured.update(state=state))
    entry.main(["--new", "--session", session, "--template", template])
    assert captured["state"]["player"]["gold"] == 15
