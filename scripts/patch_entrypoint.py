"""Патч Блока 5.3: флаг --new для main.py + тесты точки входа.

Запуск: python scripts/patch_entrypoint.py
Перезаписывает main.py и tests/test_entrypoint.py целиком (идемпотентно).
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MAIN_PY = '''"""Точка входа (Блок 5.3): GameData -> load_state -> CLI.

Запуск:
    python main.py                  # продолжить сохранённую игру
    python main.py --new            # начать новую (старая сессия перезаписывается)
    python main.py --new --seed 42  # новая игра с другим зерном карты
    python main.py --new --difficulty hard
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cli.app import run_cli
from engine.constants import DEFAULT_SESSION_PATH, DEFAULT_TEMPLATE_PATH, DIFFICULTY_MULTIPLIERS
from engine.data_loader import GameData
from engine.storage import load_state, new_game


def _read_json(path: str) -> dict | None:
    """Читает JSON-файл или возвращает None (нет файла / битый)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def ensure_template(template_path: str = DEFAULT_TEMPLATE_PATH) -> None:
    """Гарантирует актуальный шаблон: 25 узлов и 7 NPC (seed 20260101)."""
    from scripts.generate_template import generate_template

    data = _read_json(template_path)
    nodes = (data or {}).get("map", {}).get("nodes", [])
    if len(nodes) != 25:
        generate_template(template_path)


def heal_stale_session(
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
) -> bool:
    """Пересоздаёт неиграбельную сессию (карта меньше эталона / граф без рёбер)."""
    template = _read_json(template_path)
    session = _read_json(session_path)
    if template is None or session is None:
        return False

    template_nodes = template.get("map", {}).get("nodes", [])
    session_nodes = session.get("map", {}).get("nodes", [])
    if not session_nodes:
        return False

    stale = len(session_nodes) < len(template_nodes)
    edgeless = all(not node.get("connections") for node in session_nodes)
    if stale or edgeless:
        try:
            os.remove(session_path)
        except OSError:
            return False
        return True
    return False


def start_new_game(
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
    seed: int | None = None,
    difficulty: str = "normal",
) -> dict:
    """Явный старт новой игры (--new): старая сессия перезаписывается."""
    state = new_game(
        template_path=template_path,
        session_path=session_path,
        difficulty=difficulty,
        seed=seed,
    )
    if seed is not None:
        # новое зерно — новый граф региона (§ 29.2)
        from engine.worldgen import generate_region
        from engine.storage import save_state

        state["map"] = generate_region(seed, state["meta"].get("region", 1))
        save_state(state, session_path)
    return state


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="LLM Game v2.0 — текстовая RPG-рогалик",
    )
    parser.add_argument("--new", action="store_true",
                        help="начать новую игру (текущая сессия будет перезаписана)")
    parser.add_argument("--seed", type=int, default=None,
                        help="зерно генерации карты (по умолчанию из шаблона)")
    parser.add_argument("--difficulty", choices=sorted(DIFFICULTY_MULTIPLIERS), default="normal",
                        help="сложность новой игры (по умолчанию normal)")
    parser.add_argument("--session", default=DEFAULT_SESSION_PATH,
                        help="путь файла сессии")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE_PATH,
                        help="путь файла шаблона")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    ensure_template(args.template)

    if args.new:
        state = start_new_game(args.session, args.template, args.seed, args.difficulty)
    else:
        heal_stale_session(args.session, args.template)
        state, events = load_state(args.session, args.template)

    game_data = GameData(str(PROJECT_ROOT / "data"))
    rng = random.Random(state.get("meta", {}).get("seed", 20260101))
    run_cli(state, game_data, session_path=args.session, template_path=args.template, rng=rng)


if __name__ == "__main__":
    main()
'''

TESTS_PY = '''"""Тесты точки входа: флаг --new и хилер сессии."""

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
'''


def write(relative: str, source: str) -> None:
    path = ROOT / relative
    ast.parse(source)                      # синтаксис проверяем ДО записи
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    print(f"записан {relative} ({len(source.splitlines())} строк)")


def main() -> None:
    write("main.py", MAIN_PY)
    write("tests/test_entrypoint.py", TESTS_PY)
    print("Готово. Проверка: pytest -q")


if __name__ == "__main__":
    main()