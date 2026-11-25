"""
Тесты для engine/worldgen.py.
Блок 4.1 — специфика tecniche_4_1.md, раздел 6 (критерии приёмки).
"""

from __future__ import annotations

import copy
import json
import random
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from engine.worldgen import (
    generate_region,
    enter_next_region,
    validate_region_nodes,
    _p_spawn_for_type,
)

# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------

_SEED = 20260101
_REGION_1 = 1


def _load_state(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. Детерминизм
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_identical_maps(self):
        """Два вызова generate_region с одинаковым сидом дают идентичный результат."""
        m1 = generate_region(_SEED, _REGION_1)
        m2 = generate_region(_SEED, _REGION_1)
        # Сравниваем JSON-представление (побайтово)
        assert json.dumps(m1, sort_keys=True, ensure_ascii=False) == \
               json.dumps(m2, sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 2. Инварианты графа
# ---------------------------------------------------------------------------

class TestGraphInvariants:
    def _get_map(self):
        return generate_region(_SEED, _REGION_1)

    def test_node_count(self):
        m = self._get_map()
        assert len(m["nodes"]) == 25

    def test_node_00_is_village_degree_3(self):
        m = self._get_map()
        n0 = m["nodes"][0]
        assert n0["type"] == "village"
        assert len(n0["connections"]) == 3

    def test_other_nodes_degree_2_to_4(self):
        m = self._get_map()
        for i in range(1, 25):
            deg = len(m["nodes"][i]["connections"])
            assert 2 <= deg <= 4, f"node_{i:02d} degree={deg}"

    def test_mirror_connections(self):
        m = self._get_map()
        id_map = {nd["id"]: nd for nd in m["nodes"]}
        for nd in m["nodes"]:
            for conn_id in nd["connections"]:
                assert nd["id"] in id_map[conn_id]["connections"]

    def test_no_self_loops(self):
        m = self._get_map()
        for nd in m["nodes"]:
            assert nd["id"] not in nd["connections"]

    def test_connected_from_node_00(self):
        m = self._get_map()
        id_map = {nd["id"]: nd for nd in m["nodes"]}
        visited = set()
        queue = ["node_00"]
        visited.add("node_00")
        while queue:
            curr_id = queue.pop(0)
            for conn_id in id_map[curr_id]["connections"]:
                if conn_id not in visited:
                    visited.add(conn_id)
                    queue.append(conn_id)
        assert len(visited) == 25

    def test_single_lair_on_depth_6(self):
        m = self._get_map()
        lairs = [nd for nd in m["nodes"] if nd["type"] == "lair"]
        assert len(lairs) == 1
        assert lairs[0]["depth"] == 6


# ---------------------------------------------------------------------------
# 3. Плотность спавна
# ---------------------------------------------------------------------------

class TestSpawnDensity:
    def test_density_range_for_multiple_seeds(self):
        """Для серии из 20 сидов средняя плотность всегда в [0.20, 0.50]."""
        densities = []
        for i in range(20):
            seed = _SEED + i * 1000
            m = generate_region(seed, _REGION_1)
            wild = [nd for nd in m["nodes"] if nd["type"] not in ("village", "lair")]
            avg = sum(_p_spawn_for_type(nd["type"]) for nd in wild) / len(wild)
            densities.append(avg)

        for d in densities:
            assert 0.20 <= d <= 0.50, f"density={d}"


# ---------------------------------------------------------------------------
# 4. Уникальность имён
# ---------------------------------------------------------------------------

class TestNameUniqueness:
    def test_all_names_unique(self):
        m = generate_region(_SEED, _REGION_1)
        names = [nd["name"] for nd in m["nodes"]]
        assert len(names) == len(set(names)), f"Дубликаты имён: {names}"


# ---------------------------------------------------------------------------
# 5. Переход в «Дальние тропы»
# ---------------------------------------------------------------------------

class TestEnterNextRegion:
    def _make_base_state(self, map_data: dict) -> dict:
        return {
            "schemaVersion": 1,
            "meta": {"seed": _SEED, "region": 1, "llm": {
                "enabled": True,
                "endpoint": "http://127.0.0.1:8080/v1/chat/completions",
                "model": "Qwen3-4B-Instruct-Q4_K_M",
                "timeoutSec": 15,
            }},
            "player": {"level": 1, "xp": 0, "gold": 15},
            "world": {"inCombat": False, "locationsVisited": 1},
            "map": map_data,
            "npcs": {},
            "flags": {},
        }

    def test_cannot_enter_with_alive_boss(self):
        """Нельзя перейти, если босс в логове жив."""
        m = generate_region(_SEED, _REGION_1)
        # Находим лагерь и ставим монстра
        lair_id = None
        for nd in m["nodes"]:
            if nd["type"] == "lair":
                nd["state"]["monster"] = {"mobId": "mob_troll_hill", "revealed": False}
                lair_id = nd["id"]
                nd["id"] = "node_00"  # игрок в логове
                break
        # Убираем дубликат id у оригинальной деревни
        for nd in m["nodes"]:
            if nd["id"] == "node_00" and nd["type"] == "village":
                nd["id"] = "node_village_temp"
                break

        state = self._make_base_state(m)
        state["map"]["currentNodeId"] = "node_00"

        new_state, events = enter_next_region(state)
        assert events[0]["id"] == "err_lair_not_cleared"

    def test_enter_after_clearing_lair(self):
        """После зачистки логова enter_next_region работает."""
        m = generate_region(_SEED, _REGION_1)
        # Закрываем логово
        lair_node = None
        for nd in m["nodes"]:
            if nd["type"] == "lair":
                lair_node = nd
                break

        # Игрок в логове, монстр None
        for nd in m["nodes"]:
            nd["id"] = f"node_{m['nodes'].index(nd):02d}"
        m["currentNodeId"] = lair_node["id"]

        state = self._make_base_state(m)
        state["map"]["currentNodeId"] = lair_node["id"]

        new_state, events = enter_next_region(state)

        assert events[0]["id"] == "region_changed"
        assert new_state["meta"]["region"] == 2
        assert new_state["map"]["currentNodeId"] == "node_00"
        assert new_state["map"]["nodes"][0]["type"] == "camp"
        assert new_state["map"]["nodes"][0]["npcId"] is not None
        assert "1" in new_state.get("archivedRegions", {})

    def test_cannot_enter_from_non_lair(self):
        """Нельзя перейти, если игрок не в логове."""
        m = generate_region(_SEED, _REGION_1)
        state = self._make_base_state(m)
        state["map"]["currentNodeId"] = "node_00"  # деревня

        new_state, events = enter_next_region(state)
        assert events[0]["id"] == "err_not_in_lair"
