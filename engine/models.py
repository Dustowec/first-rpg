"""Фабрики, типизация и валидатор состояния игры (state)."""

from __future__ import annotations

import copy
import json
import os
from typing import Any

from .constants import (
    ATTRIBUTES,
    ATTR_MAX,
    ATTR_MIN,
    DEFAULT_DIFFICULTY,
    DEFAULT_TEMPLATE_PATH,
    DIFFICULTY_MULTIPLIERS,
    SKILLS,
    SKILL_MAX,
    SKILL_MIN,
    SCHEMA_VERSION,
    STARTING_UNSPENT_ATTR_POINTS,
    LEVEL_MIN,
    LEVEL_MAX,
)

# ---------------------------------------------------------------------------
# Фабрики
# ---------------------------------------------------------------------------


def create_default_player() -> dict[str, Any]:
    """Возвращает эталонный профиль игрока 1-го уровня."""
    return {
        "id": "player_default",
        "level": 1,
        "xp": 0,
        "gold": 15,
        "unspentPoints": {"attributes": STARTING_UNSPENT_ATTR_POINTS, "skills": 0},
        "resources": {
            "hp": {"current": 10, "max": 10},
            "mp": {"current": 2, "max": 2},
        },
        "attributes": {attr: 1 for attr in ATTRIBUTES},
        "skills": {skill: 0 for skill in SKILLS},
        "equipment": {
            "weapon": {
                "itemId": "wpn_club_simple",
                "durability": {"current": 15, "max": 15},
            },
            "armor": {
                "itemId": "arm_cloth_poor",
                "durability": {"current": 15, "max": 15},
            },
        },
        "inventory": [
            {"itemId": "food_berries", "count": 2},
            {"itemId": "food_bread", "count": 1},
            {"itemId": "pot_heal_minor", "count": 1},
        ],
    }


def _create_village_node() -> dict[str, Any]:
    """Возвращает узел деревни (node_00) для начального state."""
    return {
        "id": "node_00",
        "type": "village",
        "name": "Приграничная деревня",
        "danger": 0,
        "depth": 0,
        "connections": [],
        "state": {
            "visited": True,
            "lookUsed": False,
            "searchCount": 0,
            "searchMax": 0,
            "searchDepleted": True,
            "spawnRolled": True,
            "monster": None,
            "daysSinceCleared": 0,
        },
    }


def create_initial_state(
    seed: int = 20260101,
    difficulty: str = DEFAULT_DIFFICULTY,
    template_path_override: str | None = None,
) -> dict[str, Any]:
    """Создаёт и возвращает начальное состояние игры.

    Функция чистая: только собирает состояние, ничего не пишет на диск
    (KI-5: раньше без override она перезаписывала state_template.json в корне
    репо — эталон новой игры — и делала это из тестов). Единственный писатель
    шаблона — scripts/generate_template.py.

    Args:
        seed: Seed для генерации мира.
        difficulty: Уровень сложности.
        template_path_override: Необязательный путь для записи снимка состояния
            (совместимость с прежним контрактом: вызывающие тесты ждут файл).
            Без него функция файлов не создаёт.
    """
    multiplier = DIFFICULTY_MULTIPLIERS.get(difficulty, 1.0)

    state: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "meta": {
            "seed": seed,
            "region": 1,
            "difficulty": difficulty,
            "difficultyMultiplier": multiplier,
            "xpRate": 1.0,
            "llm": {
                "enabled": True,
                "endpoint": "http://127.0.0.1:8080/v1/chat/completions",
                "model": "Qwen3-4B-Instruct-Q4_K_M",
                "timeoutSec": 15,
            },
        },
        "player": create_default_player(),
        "world": {
            "day": 1,
            "stepOfDay": 1,
            "fedMorning": False,
            "fedEvening": False,
            "inCombat": False,
            "activeEffects": [],
            "killsTotal": 0,
            "locationsVisited": 1,
        },
        "map": {
            "currentNodeId": "node_00",
            "nodes": [_create_village_node()],
        },
        "npcs": {
            "npc_elder_miroslav": {"mood": "neutral", "reputation": "neutral", "met": False},
            "npc_merchant_ganna": {"mood": "neutral", "reputation": "neutral", "met": False},
            "npc_blacksmith_kolm": {"mood": "neutral", "reputation": "neutral", "met": False},
            "npc_innkeeper_boris": {"mood": "neutral", "reputation": "neutral", "met": False},
            "npc_herbalist_vela": {"mood": "neutral", "reputation": "neutral", "met": False},
        },
        "flags": {
            "introShown": False,
            "isDead": False,
            "deathReason": None,
        },
    }

    # Снимок состояния — только по явному пути (тесты); без него — ничего на диск
    if template_path_override:
        with open(template_path_override, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    return state


# ---------------------------------------------------------------------------
# Валидатор
# ---------------------------------------------------------------------------


def validate_state(state: dict[str, Any]) -> None:
    """Проверяет корректность state и выбрасывает ValueError при ошибках.

    Проверяет:
    - Наличие верхнеуровневых ключей.
    - schemaVersion == 1.
    - Все 5 атрибутов в диапазоне 1..10.
    - Все 9 навыков в диапазоне 0..10.
    - Уровень игрока в диапазоне 1..20.
    - currentNodeId существует среди map["nodes"].
    """
    required_keys = ["schemaVersion", "meta", "player", "world", "map", "npcs", "flags"]
    for key in required_keys:
        if key not in state:
            raise ValueError(f"Отсутствует обязательный ключ: {key}")

    if state["schemaVersion"] != SCHEMA_VERSION:
        raise ValueError(
            f"Неподдерживаемая версия схемы: {state['schemaVersion']}, "
            f"ожидается {SCHEMA_VERSION}"
        )

    player = state["player"]

    # Атрибуты: все 5 ключей, диапазон 1..10
    attrs = player.get("attributes", {})
    for attr in ATTRIBUTES:
        if attr not in attrs:
            raise ValueError(f"Отсутствует атрибут игрока: {attr}")
        val = attrs[attr]
        if not (ATTR_MIN <= val <= ATTR_MAX):
            raise ValueError(
                f"Атрибут '{attr}' = {val} вне диапазона [{ATTR_MIN}..{ATTR_MAX}]"
            )

    # Навыки: все 9 ключей, диапазон 0..10
    skills = player.get("skills", {})
    for skill in SKILLS:
        if skill not in skills:
            raise ValueError(f"Отсутствует навык игрока: {skill}")
        val = skills[skill]
        if not (SKILL_MIN <= val <= SKILL_MAX):
            raise ValueError(
                f"Навык '{skill}' = {val} вне диапазона [{SKILL_MIN}..{SKILL_MAX}]"
            )

    # Уровень
    level = player.get("level")
    if level is None or not (LEVEL_MIN <= level <= LEVEL_MAX):
        raise ValueError(
            f"Уровень игрока {level} вне диапазона [{LEVEL_MIN}..{LEVEL_MAX}]"
        )

    # currentNodeId
    map_data = state["map"]
    current_id = map_data.get("currentNodeId")
    node_ids = {n["id"] for n in map_data.get("nodes", [])}
    if current_id not in node_ids:
        raise ValueError(
            f"currentNodeId '{current_id}' не найден среди узлов: {sorted(node_ids)}"
        )


# ---------------------------------------------------------------------------
# Генерация шаблона при прямом запуске
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    state = create_initial_state()
    print(f"state_template.json создан. schemaVersion={state['schemaVersion']}")
