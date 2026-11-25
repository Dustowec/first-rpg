"""Менеджер сохранений: атомарная запись, загрузка, бекап, permadeath."""

from __future__ import annotations

import copy
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Tuple

from .constants import (
    DEFAULT_SESSION_PATH,
    DEFAULT_TEMPLATE_PATH,
    DEFAULT_DIFFICULTY,
)
from .models import create_initial_state, validate_state


# ---------------------------------------------------------------------------
# Сохранение
# ---------------------------------------------------------------------------


def save_state(state: dict[str, Any], path: str = DEFAULT_SESSION_PATH) -> None:
    """Атомарно сохраняет state в JSON.

    1. Валидирует state.
    2. Пишет во временный файл .tmp.
    3. fsync + os.replace для атомарности.
    """
    validate_state(state)

    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, path)


# ---------------------------------------------------------------------------
# Новая игра
# ---------------------------------------------------------------------------


def new_game(
    template_path: str = DEFAULT_TEMPLATE_PATH,
    session_path: str = DEFAULT_SESSION_PATH,
    difficulty: str = DEFAULT_DIFFICULTY,
    seed: int | None = None,
) -> dict[str, Any]:
    """Создаёт новую игру из шаблона или генерирует шаблон.

    Если template_path существует — загружает и применяет difficulty/seed.
    Если нет — генерирует через create_initial_state().
    Сохраняет в session_path и возвращает state.
    """
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = create_initial_state(seed=seed or 20260101, difficulty=difficulty)

    # Применяем сложность
    from .constants import DIFFICULTY_MULTIPLIERS

    state["meta"]["difficulty"] = difficulty
    state["meta"]["difficultyMultiplier"] = DIFFICULTY_MULTIPLIERS.get(difficulty, 1.0)

    if seed is not None:
        state["meta"]["seed"] = seed

    save_state(state, session_path)
    return state


# ---------------------------------------------------------------------------
# Загрузка
# ---------------------------------------------------------------------------


def _backup_path(session_path: str) -> str:
    """Возвращает путь для бекапа: state_backup_ГГГГММДД-ЧЧММ.json."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    base = os.path.splitext(session_path)[0]
    ext = os.path.splitext(session_path)[1] or ".json"
    return f"{base}_backup_{timestamp}{ext}"


def load_state(
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
) -> Tuple[dict[str, Any], list[dict[str, Any]]]:
    """Загружает сессию с полной обработкой ошибок.

    Возвращает (state, events).
    Events — список словарей с id и дополнительными полями.
    """
    events: list[dict[str, Any]] = []

    # Сессии нет — новая игра
    if not os.path.exists(session_path):
        state = new_game(template_path=template_path, session_path=session_path)
        events.append({"id": "sys_new_game"})
        return state, events

    # Пытаемся прочитать и валидировать
    try:
        with open(session_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        validate_state(state)
    except Exception:
        # Битый файл — бекап + новая игра
        bp = _backup_path(session_path)
        try:
            shutil.copy2(session_path, bp)
        except Exception:
            pass  # бекап необязателен, если файл битый
        events.append({"id": "sys_corrupted_backup", "backupPath": bp})
        state = new_game(template_path=template_path, session_path=session_path)
        return state, events

    # Permadeath — полный сброс
    if state.get("flags", {}).get("isDead") is True:
        try:
            os.remove(session_path)
        except OSError:
            pass
        events.append({"id": "sys_permadeath_reset"})
        state = new_game(template_path=template_path, session_path=session_path)
        return state, events

    return state, events


# ---------------------------------------------------------------------------
# Смерть игрока
# ---------------------------------------------------------------------------


def handle_player_death(
    state: dict[str, Any],
    reason: str,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
) -> Tuple[dict[str, Any], list[dict[str, Any]]]:
    """Обработка смерти игрока: помечает флаг, удаляет сейв, создаёт новый.

    Возвращает (fresh_state, events).
    """
    state["flags"]["isDead"] = True
    state["flags"]["deathReason"] = reason

    events: list[dict[str, Any]] = [
        {"id": "player_died", "reason": reason},
        {"id": "sys_permadeath_reset"},
    ]

    try:
        os.remove(session_path)
    except OSError:
        pass

    fresh_state = new_game(template_path=template_path, session_path=session_path)
    return fresh_state, events
