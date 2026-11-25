#!/usr/bin/env python3
"""
Генератор эталонного state_template.json.
Блок 4.1 — специфика tecniche_4_1.md, раздел 5.

Запуск: python scripts/generate_template.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Добавляем корень проекта в path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from engine.worldgen import generate_region

# ---------------------------------------------------------------------------
# Стартовый игрок (§11)
# ---------------------------------------------------------------------------

def _make_player() -> dict:
    return {
        "id": "player_default",
        "level": 1,
        "xp": 0,
        "gold": 15,
        "unspentPoints": {
            "attributes": 3,
            "skills": 0,
        },
        "resources": {
            "hp": {"current": 10, "max": 10},
            "mp": {"current": 2, "max": 2},
        },
        "attributes": {
            "strength": 1,
            "agility": 1,
            "constitution": 1,
            "intelligence": 1,
            "wisdom": 1,
        },
        "skills": {
            "melee_heavy": 0,
            "melee_light": 0,
            "armor_mastery": 0,
            "pyromancy": 0,
            "restoration": 0,
            "hexes": 0,
            "alchemy": 0,
            "crafting": 0,
            "scavenging": 0,
        },
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
        "inventory": [],
    }


# ---------------------------------------------------------------------------
# Стартовый мир (§32.3)
# ---------------------------------------------------------------------------

def _make_world() -> dict:
    return {
        "day": 1,
        "stepOfDay": 1,
        "fedMorning": False,
        "fedEvening": False,
        "inCombat": False,
        "activeEffects": [],
        "killsTotal": 0,
        "locationsVisited": 1,
    }


# ---------------------------------------------------------------------------
# NPC (§31.3)
# ---------------------------------------------------------------------------

_ALL_NPC_IDS = [
    "npc_elder_miroslav",
    "npc_merchant_ganna",
    "npc_blacksmith_kolm",
    "npc_innkeeper_boris",
    "npc_herbalist_vela",
    "npc_hunter_rask",
    "npc_wanderer_kit",
]


def _make_npcs() -> dict:
    return {nid: {"mood": "neutral", "reputation": "neutral", "met": False} for nid in _ALL_NPC_IDS}


# ---------------------------------------------------------------------------
# Главный генератор шаблона
# ---------------------------------------------------------------------------

def generate_template(output_path: str | Path) -> None:
    """Генерирует и сохраняет state_template.json."""
    seed = 20260101
    region = 1

    map_data = generate_region(seed, region)

    template = {
        "schemaVersion": 1,
        "meta": {
            "seed": seed,
            "region": region,
            "llm": {
                "enabled": True,
                "endpoint": "http://127.0.0.1:8080/v1/chat/completions",
                "model": "Qwen3-4B-Instruct-Q4_K_M",
                "timeoutSec": 15,
            },
        },
        "player": _make_player(),
        "world": _make_world(),
        "map": map_data,
        "npcs": _make_npcs(),
        "flags": {
            "introShown": False,
        },
    }

    out = Path(output_path)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)

    print(f"state_template.json written to {out}")


if __name__ == "__main__":
    out_path = project_root / "state_template.json"
    generate_template(out_path)
