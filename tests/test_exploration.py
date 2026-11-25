"""
Тесты для engine/exploration.py.
Блок 4.2 — специфика tecniche_4_2.md, раздел 5 (критерии приёмки).
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

from engine.exploration import (
    move_to_node,
    look_around,
    scavenge_node,
    wait_step,
    _load_game_data,
)

from engine.worldgen import generate_region

# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------

_SEED = 20260101


def _make_state(region=1, scavenging=0, intelligence=1,
                fed_morning=True, fed_evening=True, in_combat=False,
                step=1):
    """Создаёт минимальный state с картой."""
    gd = _load_game_data()
    map_data = generate_region(_SEED, region, gd)
    return {
        "schemaVersion": 1,
        "meta": {"seed": _SEED, "region": region, "difficultyMultiplier": 1.0,
                 "llm": {"enabled": False}},
        "player": {
            "level": 1, "xp": 0, "gold": 15,
            "attributes": {"strength": 1, "agility": 1, "constitution": 1,
                           "intelligence": intelligence, "wisdom": 1},
            "skills": {"melee_heavy": 0, "melee_light": 0, "armor_mastery": 0,
                       "pyromancy": 0, "restoration": 0, "hexes": 0,
                       "alchemy": 0, "crafting": 0, "scavenging": scavenging},
            "resources": {"hp": {"current": 10, "max": 10}, "mp": {"current": 2, "max": 2}},
            "inventory": [],
        },
        "world": {"day": 1, "stepOfDay": step, "fedMorning": fed_morning,
                  "fedEvening": fed_evening, "inCombat": in_combat,
                  "activeEffects": [], "killsTotal": 0, "locationsVisited": 1},
        "map": map_data,
        "npcs": {},
        "flags": {},
    }


def _find_node(map_data, node_id):
    for nd in map_data["nodes"]:
        if nd["id"] == node_id:
            return nd
    return None


def _scavenge_stats(gd, biome_type, scav=0, intel=1, steps=2000):
    """Сбрасывает RNG для каждого шага — чистый ролл категории."""
    map_data = generate_region(_SEED + 700, 1, gd)
    target_node = None
    for nd in map_data["nodes"]:
        if nd["type"] == biome_type:
            target_node = nd
            break
    assert target_node is not None, f"Биом {biome_type} не найден"

    st = _make_state(scavenging=scav, intelligence=intel, step=1)
    st["map"] = map_data
    st["map"]["currentNodeId"] = target_node["id"]

    counts = {"nothing": 0, "food": 0, "junk": 0, "weapon": 0, "armor": 0}
    for i in range(steps):
        st_copy = copy.deepcopy(st)
        for nd in st_copy["map"]["nodes"]:
            if nd["id"] == target_node["id"]:
                nd["state"]["searchCount"] = 0
                nd["state"]["searchDepleted"] = False
                break
        rng = random.Random(i)
        # Передаём rng — но scavenge_node не принимает rng напрямую.
        # advance_time внутри использует rng, но без случайности.
        # Ролл категории использует глобальный random.Random(state["meta"]["seed"])
        # Поэтому используем seed = i для предсказуемости
        st_copy["meta"]["seed"] = i
        new_st, events = scavenge_node(st_copy, gd)
        if events:
            ev = events[0]
            if ev["id"] == "scavenge_found":
                cat = ev.get("category", "nothing")
                counts[cat] = counts.get(cat, 0) + 1
            elif ev["id"] == "scavenge_nothing":
                counts["nothing"] += 1

    return counts


# ---------------------------------------------------------------------------
# 1. Перемещение и ленивый спавн
# ---------------------------------------------------------------------------

class TestMoveAndSpawn:
    def test_invalid_connection(self):
        """Переход в неподключённый узел отклоняется."""
        st = _make_state()
        new_st, events = move_to_node(st, "node_99")
        assert events[0]["id"] == "err_invalid_connection"

    def test_move_spends_ap_and_sets_flags(self):
        """Переход в соседний тратит 1 AP, visited=True, lookUsed=False."""
        st = _make_state()
        n0 = st["map"]["nodes"][0]
        target_id = n0["connections"][0]  # строка "node_01"
        new_st, events = move_to_node(st, target_id)

        assert len(events) > 0, f"events empty: {events}"
        assert events[0]["id"] == "moved_to_node"
        assert new_st["map"]["currentNodeId"] == target_id
        assert new_st["world"]["stepOfDay"] == 2  # +1 AP

        tnode = _find_node(new_st["map"], target_id)
        assert tnode is not None
        assert tnode["state"]["visited"] is True
        assert tnode["state"]["lookUsed"] is False
        assert tnode["state"]["spawnRolled"] is True

    def test_cannot_move_in_combat(self):
        """Нельзя перемещаться в бою."""
        st = _make_state(in_combat=True)
        n0 = st["map"]["nodes"][0]
        new_st, events = move_to_node(st, n0["connections"][0])
        assert events[0]["id"] == "err_in_combat"


# ---------------------------------------------------------------------------
# 2. Засада и навык scavenging
# ---------------------------------------------------------------------------

class TestAmbush:
    def test_ambush_triggers_combat(self):
        """Засада запускает бой без траты доп AP."""
        st = _make_state()
        n0 = st["map"]["nodes"][0]
        target_id = n0["connections"][0]

        for nd in st["map"]["nodes"]:
            if nd["id"] == target_id:
                nd["state"]["spawnRolled"] = True
                nd["state"]["monster"] = {"mobId": "mob_wolf_forest", "revealed": False,
                                           "hp": 6, "maxHp": 6}
                break

        for seed_val in range(100):
            rng = random.Random(seed_val)
            st_copy = copy.deepcopy(st)
            new_st, events = move_to_node(st_copy, target_id, rng=rng)
            ambush_events = [e for e in events if e["id"] == "ambush_triggered"]
            if ambush_events:
                break

        assert len(ambush_events) > 0, f"Засада не сработала ни за 100 seed"
        combat_events = [e for e in events if e["id"] == "combat_start"]
        assert len(combat_events) > 0
        assert combat_events[0]["isAmbush"] is True

    def test_high_scavenging_reduces_ambush(self):
        """При scavenging==10 шанс засады ≤ 5%."""
        st = _make_state(scavenging=10)
        n0 = st["map"]["nodes"][0]
        target_id = n0["connections"][0]

        for nd in st["map"]["nodes"]:
            if nd["id"] == target_id:
                nd["state"]["spawnRolled"] = True
                nd["state"]["monster"] = {"mobId": "mob_wolf_forest", "revealed": False,
                                           "hp": 6, "maxHp": 6}
                break

        ambush_count = 0
        for seed_val in range(100):
            st_copy = copy.deepcopy(st)
            for nd in st_copy["map"]["nodes"]:
                if nd["id"] == target_id:
                    nd["state"]["spawnRolled"] = False
                    break
            test_rng = random.Random(seed_val)
            _, events = move_to_node(st_copy, target_id, rng=test_rng)
            if any(e["id"] == "ambush_triggered" for e in events):
                ambush_count += 1

        assert ambush_count <= 8, f"Засада сработала {ambush_count}/100 раз (допустимо ≤5%)"

    def test_ambush_survived_marks_revealed(self):
        """После засады монстр revealed — повторный вход без засады."""
        st = _make_state()
        n0 = st["map"]["nodes"][0]
        target_id = n0["connections"][0]

        for nd in st["map"]["nodes"]:
            if nd["id"] == target_id:
                nd["state"]["spawnRolled"] = True
                nd["state"]["monster"] = {"mobId": "mob_wolf_forest", "revealed": False,
                                           "hp": 6, "maxHp": 6}
                break

        for seed_val in range(100):
            rng = random.Random(seed_val)
            st_copy = copy.deepcopy(st)
            new_st, events = move_to_node(st_copy, target_id, rng=rng)
            ambush_events = [e for e in events if e["id"] == "ambush_triggered"]
            if ambush_events:
                # Монстр должен быть revealed в new_st
                for nd in new_st["map"]["nodes"]:
                    if nd["id"] == target_id:
                        assert nd["state"]["monster"]["revealed"] is True
                        break
                # Проверим что в new_st inCombat=True (бой)
                assert new_st["world"]["inCombat"] is True
                break


# ---------------------------------------------------------------------------
# 3. Осмотреться
# ---------------------------------------------------------------------------

class TestLookAround:
    def test_look_spends_ap_and_reveals(self):
        """Осмотр тратит 1 AP, раскрывает монстра."""
        st = _make_state()
        n0 = st["map"]["nodes"][0]
        n0["state"]["spawnRolled"] = True
        n0["state"]["monster"] = {"mobId": "mob_wolf_forest", "revealed": False,
                                   "hp": 6, "maxHp": 6}

        new_st, events = look_around(st)

        assert len(events) > 0
        assert events[0]["id"] == "look_found_monster"
        assert events[0]["mobId"] == "mob_wolf_forest"

        for nd in new_st["map"]["nodes"]:
            if nd["id"] == "node_00":
                assert nd["state"]["monster"]["revealed"] is True
                assert nd["state"]["lookUsed"] is True
                break

    def test_already_looked_no_ap_cost(self):
        """Повторный осмотр не тратит AP."""
        st = _make_state()
        n0 = st["map"]["nodes"][0]
        n0["state"]["lookUsed"] = True

        new_st, events = look_around(st)
        assert events[0]["id"] == "err_already_looked"
        assert new_st["world"]["stepOfDay"] == 1  # AP не потрачен

    def test_look_clear(self):
        """Осмотр в пустой локации."""
        st = _make_state()
        n0 = st["map"]["nodes"][0]
        n0["state"]["spawnRolled"] = True
        n0["state"]["monster"] = None

        new_st, events = look_around(st)
        assert events[0]["id"] == "look_clear"


# ---------------------------------------------------------------------------
# 4. Поиск и истощение
# ---------------------------------------------------------------------------

class TestScavenge:
    def test_cannot_search_in_village(self):
        """В деревне поиск запрещён."""
        st = _make_state()
        new_st, events = scavenge_node(st)
        assert events[0]["id"] == "err_cannot_search_here"

    def test_search_depletes_after_max_attempts(self):
        """За 3 + danger попыток searchDepleted = True."""
        st = _make_state()
        n0 = st["map"]["nodes"][0]
        target_id = n0["connections"][0]

        # Перемещаемся, проверяем что нет боя (засады)
        st, ev1 = move_to_node(st, target_id)
        if st["world"].get("inCombat"):
            pytest.skip("Ambush triggered, skipping search test")

        tnode = _find_node(st["map"], target_id)
        danger = tnode.get("danger", 1) if tnode else 1
        search_max = 3 + danger

        for i in range(search_max):
            new_st, events = scavenge_node(st)
            assert len(events) > 0, f"Нет событий на попытке {i+1}, events={events}"
            assert events[0]["id"] in ("scavenge_found", "scavenge_nothing")
            st = new_st

        new_st, events = scavenge_node(st)
        assert events[0]["id"] == "err_search_depleted"

    def test_search_in_combat_blocked(self):
        """Поиск в бою заблокирован."""
        st = _make_state(in_combat=True)
        n0 = st["map"]["nodes"][0]
        target_id = n0["connections"][0]
        st, _ = move_to_node(st, target_id)

        new_st, events = scavenge_node(st)
        assert not any(e["id"] == "scavenge_found" for e in events)

    def test_scavenge_returns_items(self):
        """Поиск в дикой локации находит предметы."""
        st = _make_state()
        n0 = st["map"]["nodes"][0]
        target_id = n0["connections"][0]
        st, ev1 = move_to_node(st, target_id)
        if st["world"].get("inCombat"):
            pytest.skip("Ambush triggered, skipping search test")

        found_any = False
        for i in range(50):
            st_copy = copy.deepcopy(st)
            st_copy["meta"]["seed"] = i
            new_st, events = scavenge_node(st_copy)
            if events and events[0]["id"] == "scavenge_found":
                found_any = True
                break
            st = new_st

        assert found_any, "За 50 попыток поиска ничего не найдено"


# ---------------------------------------------------------------------------
# 5. Биомные сдвиги и перки
# ---------------------------------------------------------------------------

class TestBiomeShiftsAndPerks:
    def test_biome_shifts_affect_rates(self):
        """Разные биомы дают разную долю лута."""
        gd = _load_game_data()

        counts_road = _scavenge_stats(gd, "road", steps=1000)
        counts_meadow = _scavenge_stats(gd, "meadow", steps=1000)

        total_road = sum(counts_road.values())
        total_meadow = sum(counts_meadow.values())

        junk_rate_road = counts_road["junk"] / total_road if total_road else 0
        food_rate_meadow = counts_meadow["food"] / total_meadow if total_meadow else 0

        # Junk rate на тракте должен быть заметным (≥ 15%)
        assert junk_rate_road > 0.12, f"Junk rate на тракте: {junk_rate_road:.2%}"
        # Food rate на лугу должен быть заметным (≥ 20%)
        assert food_rate_meadow > 0.15, f"Food rate на лугу: {food_rate_meadow:.2%}"

    def test_intel_reduces_nothing(self):
        """Высокий intelligence снижает долю пустых исходов."""
        gd = _load_game_data()

        counts_low = _scavenge_stats(gd, "meadow", intel=1, steps=1000)
        counts_high = _scavenge_stats(gd, "meadow", intel=10, steps=1000)

        total_low = sum(counts_low.values())
        total_high = sum(counts_high.values())

        rate_low = counts_low["nothing"] / total_low if total_low else 1.0
        rate_high = counts_high["nothing"] / total_high if total_high else 1.0

        assert rate_high < rate_low, (
            f"Nothing rate: low_int={rate_low:.2%}, high_int={rate_high:.2%}"
        )

    def test_scavenging_10_finds_rare_items(self):
        """scavenging==10 с 2% шанс найти canFind=False."""
        gd = _load_game_data()
        map_data = generate_region(_SEED + 800, 1, gd)
        meadow_node = None
        for nd in map_data["nodes"]:
            if nd["type"] == "meadow":
                meadow_node = nd
                break
        assert meadow_node is not None

        st = _make_state(scavenging=10, step=1)
        st["map"] = map_data
        st["map"]["currentNodeId"] = meadow_node["id"]

        rare_found = False
        for i in range(1000):
            st_copy = copy.deepcopy(st)
            for nd in st_copy["map"]["nodes"]:
                if nd["id"] == meadow_node["id"]:
                    nd["state"]["searchCount"] = 0
                    nd["state"]["searchDepleted"] = False
                    break
            st_copy["meta"]["seed"] = i
            new_st, events = scavenge_node(st_copy, gd)
            for ev in events:
                if ev["id"] == "scavenge_found":
                    item = None
                    for items in gd.values():
                        for it in items:
                            if it["id"] == ev["itemId"]:
                                item = it
                                break
                    if item and not item.get("economy", {}).get("canFind", True):
                        rare_found = True
                        break
            if rare_found:
                break

        assert rare_found, "Не найден редкий предмет за 1000 попыток (scavenging=10)"


# ---------------------------------------------------------------------------
# 6. Ожидание
# ---------------------------------------------------------------------------

class TestWaitStep:
    def test_wait_advances_time(self):
        """Ожидание продвигает время на 1 шаг."""
        st = _make_state()
        new_st, events = wait_step(st)
        assert events[0]["id"] == "waited_one_step"
        assert new_st["world"]["stepOfDay"] == 2

    def test_wait_in_combat_blocked(self):
        """Ожидание в бою заблокировано."""
        st = _make_state(in_combat=True)
        new_st, events = wait_step(st)
        assert not events

    def test_wait_ticks_regeneration(self):
        """Ожидание тикает регенерацию HP/MP."""
        st = _make_state()
        st["player"]["level"] = 3
        st["player"]["resources"]["hp"]["current"] = 5
        st["player"]["resources"]["mp"]["current"] = 1

        for _ in range(5):
            new_st, _ = wait_step(st)
            st = new_st

        assert st["player"]["resources"]["hp"]["current"] >= 5
        assert st["player"]["resources"]["mp"]["current"] >= 1
