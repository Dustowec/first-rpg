"""Точка входа (Блок 5.3): GameData -> load_state -> CLI."""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cli.app import run_cli
from engine.constants import DEFAULT_SESSION_PATH, DEFAULT_TEMPLATE_PATH
from engine.data_loader import GameData
from engine.storage import load_state


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
    """Пересоздаёт неиграбельную сессию. Возвращает True, если сессия сброшена.

    Признаки мёртвого сейва:
    - карта меньше эталонной (сейв из устаревшего шаблона на 1 узел);
    - у всех узлов пустые connections (граф без рёбер — выйти некуда).

    Живые сессии не затрагиваются: прогресс игрока сохраняется.
    """
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


def main() -> None:
    ensure_template()
    heal_stale_session()
    game_data = GameData(str(PROJECT_ROOT / "data"))
    state, events = load_state(DEFAULT_SESSION_PATH, DEFAULT_TEMPLATE_PATH)
    rng = random.Random(state.get("meta", {}).get("seed", 20260101))
    run_cli(state, game_data, rng=rng)


if __name__ == "__main__":
    main()