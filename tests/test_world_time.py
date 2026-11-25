"""Тесты для Блока 2.3: Время суток (AP), голод, еда, ночлег и респавн."""

import os
import sys
from pathlib import Path

import pytest

_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from engine.data_loader import GameData
from engine.models import create_default_player
from engine import world_time
from engine.progression import has_tight_belt

_data_dir = os.path.join(_project_root, "data")
_game_data = GameData(_data_dir)


def _make_state(**overrides):
    """Создаёт тестовое состояние с player."""
    player = create_default_player()
    state = {
        "player": player,
        "meta": {"difficultyMultiplier": 1.0, "xpRate": 1.0},
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
            "nodes": [
                {
                    "id": "node_00",
                    "type": "village",
                    "name": "Test Village",
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
            ],
        },
        "npcs": {
            "npc_innkeeper_boris": {"mood": "neutral", "reputation": "neutral", "met": False},
        },
        "flags": {},
    }
    for key, value in overrides.items():
        if key == "player":
            for k, v in value.items():
                state["player"][k] = v
        elif key == "world":
            for k, v in value.items():
                state["world"][k] = v
        elif key == "map":
            state["map"] = value
        else:
            state[key] = value
    return state


# ---------------------------------------------------------------------------
# А. Окна голода
# ---------------------------------------------------------------------------


class TestHungerDeadlines:
    def test_base_deadlines(self):
        """Базово: завтрак до шага 7, ужин до шага 17."""
        player = create_default_player()
        morning, evening = world_time.get_hunger_deadlines(player)
        assert morning == 7
        assert evening == 17

    def test_tight_belt_deadlines(self):
        """scavenging >= 6 («Тугий пояс»): сдвиг +2 → (9, 19)."""
        player = create_default_player()
        player["skills"]["scavenging"] = 6
        morning, evening = world_time.get_hunger_deadlines(player)
        assert morning == 9
        assert evening == 19


class TestIsHungryNow:
    def test_hungry_morning(self):
        """1 <= step < 7, fedMorning=False → голод."""
        state = _make_state(world={"stepOfDay": 3, "fedMorning": False, "fedEvening": False})
        assert world_time.is_hungry_now(state["world"], state["player"]) is True

    def test_not_hungry_after_breakfast(self):
        """1 <= step < 7, fedMorning=True → не голод."""
        state = _make_state(world={"stepOfDay": 3, "fedMorning": True, "fedEvening": False})
        assert world_time.is_hungry_now(state["world"], state["player"]) is False

    def test_hungry_evening(self):
        """10 <= step < 17, fedEvening=False → голод."""
        state = _make_state(world={"stepOfDay": 12, "fedMorning": True, "fedEvening": False})
        assert world_time.is_hungry_now(state["world"], state["player"]) is True

    def test_not_hungry_after_dinner(self):
        """10 <= step < 17, fedEvening=True → не голод."""
        state = _make_state(world={"stepOfDay": 12, "fedMorning": True, "fedEvening": True})
        assert world_time.is_hungry_now(state["world"], state["player"]) is False

    def test_not_hungry_at_step_1(self):
        """step=1, fedMorning=True → не голод."""
        state = _make_state(world={"stepOfDay": 1, "fedMorning": True, "fedEvening": True})
        assert world_time.is_hungry_now(state["world"], state["player"]) is False

    def test_not_hungry_at_step_20(self):
        """step=20 — после ужина, не голод."""
        state = _make_state(world={"stepOfDay": 20, "fedMorning": True, "fedEvening": True})
        assert world_time.is_hungry_now(state["world"], state["player"]) is False


# ---------------------------------------------------------------------------
# В. Продвижение времени
# ---------------------------------------------------------------------------


class TestAdvanceTime:
    def test_step_20_to_1_new_day(self):
        """Переход с шага 20 на шаг 1 увеличивает day на +1."""
        state = _make_state(world={"stepOfDay": 20, "fedMorning": True, "fedEvening": True})
        new_state, _ = world_time.advance_time(state, steps=1)
        assert new_state["world"]["stepOfDay"] == 1
        assert new_state["world"]["day"] == 2
        assert new_state["world"]["fedMorning"] is False
        assert new_state["world"]["fedEvening"] is False

    def test_starvation_morning(self):
        """Смерть от голода на шаге 7 (без перка)."""
        state = _make_state(world={"stepOfDay": 6, "fedMorning": False, "fedEvening": False})
        new_state, events = world_time.advance_time(state, steps=1)
        assert any(e["id"] == "player_died" for e in events)
        assert any(e["reason"] == "starvation_morning" for e in events)

    def test_starvation_morning_with_tight_belt(self):
        """Смерть от голода на шаге 9 при scavenging==6."""
        state = _make_state(
            world={"stepOfDay": 8, "fedMorning": False, "fedEvening": False},
            player={"skills": {"scavenging": 6}},
        )
        new_state, events = world_time.advance_time(state, steps=1)
        assert any(e["id"] == "player_died" for e in events)
        assert any(e["reason"] == "starvation_morning" for e in events)

    def test_starvation_evening(self):
        """Смерть от голода на шаге 17 (без перка)."""
        state = _make_state(
            world={"stepOfDay": 16, "fedMorning": True, "fedEvening": False},
        )
        new_state, events = world_time.advance_time(state, steps=1)
        assert any(e["id"] == "player_died" for e in events)
        assert any(e["reason"] == "starvation_evening" for e in events)

    def test_mp_regeneration(self):
        """MP восстанавливается каждые 5 шагов: step % 5 == 0."""
        state = _make_state(world={"stepOfDay": 4, "fedMorning": True, "fedEvening": True})
        state["player"]["resources"]["mp"]["current"] = 0
        state["player"]["resources"]["mp"]["max"] = 2
        state["player"]["level"] = 1
        new_state, _ = world_time.advance_time(state, steps=1)
        # step=5, MP regen
        assert new_state["world"]["stepOfDay"] == 5
        assert new_state["player"]["resources"]["mp"]["current"] == 1  # +level

    def test_hp_regeneration_blocked_by_hunger(self):
        """HP не восстанавливается при голоде на шаге 3 и 6."""
        state = _make_state(
            world={"stepOfDay": 2, "fedMorning": False, "fedEvening": False},
        )
        state["player"]["resources"]["hp"]["current"] = 5
        state["player"]["resources"]["hp"]["max"] = 10
        state["player"]["level"] = 1

        # step=3: hunger blocks HP regen
        state, _ = world_time.advance_time(state, steps=1)
        assert state["world"]["stepOfDay"] == 3
        assert state["player"]["resources"]["hp"]["current"] == 5  # no regen

        # step=4, 5: hunger still blocks (step 5 is MP regen only)
        state, _ = world_time.advance_time(state, steps=2)
        assert state["world"]["stepOfDay"] == 5
        assert state["player"]["resources"]["hp"]["current"] == 5  # still blocked

    def test_hp_regeneration_after_eating(self):
        """После eat_food реген HP включается."""
        state = _make_state(
            world={"stepOfDay": 2, "fedMorning": False, "fedEvening": False},
        )
        state["player"]["resources"]["hp"]["current"] = 5
        state["player"]["resources"]["hp"]["max"] = 10
        state["player"]["level"] = 1
        state["player"]["inventory"].append({"itemId": "food_berries", "count": 1})

        # съедаем (hpRestore=1)
        state, _ = world_time.eat_food(state, "food_berries", _game_data)
        # HP now 6, fedMorning=True, hunger blocked
        assert state["player"]["resources"]["hp"]["current"] == 6

        # advancing to step 3 (every 3 steps HP regen, +level=1)
        state, _ = world_time.advance_time(state, steps=1)
        assert state["world"]["stepOfDay"] == 3
        assert state["player"]["resources"]["hp"]["current"] == 7  # 6 + 1 regen

    def test_active_effects_dot(self):
        """DoT-эффект: hpDeltaPerTurn применяется каждый шаг."""
        state = _make_state(
            world={
                "stepOfDay": 1,
                "fedMorning": True,
                "fedEvening": True,
                "activeEffects": [
                    {"type": "poison", "hpDeltaPerTurn": -1, "ticksLeft": 3}
                ],
            },
        )
        state["player"]["resources"]["hp"]["current"] = 5
        state["player"]["resources"]["hp"]["max"] = 10

        new_state, events = world_time.advance_time(state, steps=1)
        assert new_state["world"]["stepOfDay"] == 2
        assert new_state["player"]["resources"]["hp"]["current"] == 4  # -1 poison
        assert new_state["world"]["activeEffects"][0]["ticksLeft"] == 2

    def test_effect_expired(self):
        """Эффект удаляется при ticksLeft <= 0."""
        state = _make_state(
            world={
                "stepOfDay": 1,
                "fedMorning": True,
                "fedEvening": True,
                "activeEffects": [
                    {"type": "poison", "hpDeltaPerTurn": -1, "ticksLeft": 1}
                ],
            },
        )
        new_state, events = world_time.advance_time(state, steps=1)
        assert len(new_state["world"]["activeEffects"]) == 0
        assert any(e["id"] == "effect_expired" for e in events)

    def test_dot_death(self):
        """Смерть от DoT при hp <= 0."""
        state = _make_state(
            world={
                "stepOfDay": 1,
                "fedMorning": True,
                "fedEvening": True,
                "activeEffects": [
                    {"type": "poison", "hpDeltaPerTurn": -5, "ticksLeft": 1}
                ],
            },
        )
        state["player"]["resources"]["hp"]["current"] = 3
        state["player"]["resources"]["hp"]["max"] = 10

        new_state, events = world_time.advance_time(state, steps=1)
        assert any(e["id"] == "player_died" for e in events)
        assert any(e["reason"] == "dot_damage" for e in events)


# ---------------------------------------------------------------------------
# В. Употребление еды
# ---------------------------------------------------------------------------


class TestEatFood:
    def test_eat_food_restores_hp(self):
        """Еда восстанавливает HP."""
        state = _make_state()
        state["player"]["inventory"].append({"itemId": "food_berries", "count": 1})
        state["player"]["resources"]["hp"]["current"] = 5

        new_state, events = world_time.eat_food(state, "food_berries", _game_data)
        # hpRestore=1
        assert new_state["player"]["resources"]["hp"]["current"] == 6

    def test_eat_food_closes_morning_window(self):
        """Еда на шаге 3 закрывает утреннее окно."""
        state = _make_state(world={"stepOfDay": 3, "fedMorning": False, "fedEvening": False})
        state["player"]["inventory"].append({"itemId": "food_berries", "count": 1})

        new_state, events = world_time.eat_food(state, "food_berries", _game_data)
        assert new_state["world"]["fedMorning"] is True
        assert any(e["id"] == "hunger_satisfied" and e["meal"] == "morning" for e in events)

    def test_eat_food_closes_evening_window(self):
        """Еда на шаге 12 закрывает вечернее окно."""
        state = _make_state(world={"stepOfDay": 12, "fedMorning": True, "fedEvening": False})
        state["player"]["inventory"].append({"itemId": "food_berries", "count": 1})

        new_state, events = world_time.eat_food(state, "food_berries", _game_data)
        assert new_state["world"]["fedEvening"] is True
        assert any(e["id"] == "hunger_satisfied" and e["meal"] == "evening" for e in events)

    def test_eat_food_no_ap_cost(self):
        """Поедание не тратит AP (шаг суток не меняется)."""
        state = _make_state(world={"stepOfDay": 5, "fedMorning": True, "fedEvening": True})
        state["player"]["inventory"].append({"itemId": "food_berries", "count": 1})

        new_state, _ = world_time.eat_food(state, "food_berries", _game_data)
        assert new_state["world"]["stepOfDay"] == 5

    def test_eat_food_invalid_item(self):
        """Непищевой предмет — ошибка."""
        state = _make_state()
        new_state, events = world_time.eat_food(state, "pot_heal_minor", _game_data)
        assert events[0]["id"] == "err_invalid_food"

    def test_eat_food_not_in_inventory(self):
        """Предмет отсутствует в инвентаре — ошибка."""
        state = _make_state()
        new_state, events = world_time.eat_food(state, "food_cabbage", _game_data)
        assert events[0]["id"] == "err_invalid_food"

    def test_red_mushroom_poison(self):
        """Красный гриб закрывает окно голода, но вешает poison."""
        state = _make_state(world={"stepOfDay": 3, "fedMorning": False, "fedEvening": False})
        state["player"]["inventory"].append({"itemId": "food_red_mushroom", "count": 1})

        new_state, events = world_time.eat_food(state, "food_red_mushroom", _game_data)
        assert new_state["world"]["fedMorning"] is True
        assert any(e["id"] == "hunger_satisfied" for e in events)
        # Poison effect applied
        effects = new_state["world"]["activeEffects"]
        assert len(effects) == 1
        assert effects[0]["type"] == "poison"
        assert effects[0]["hpDeltaPerTurn"] == -1
        assert effects[0]["ticksLeft"] == 3

    def test_red_mushroom_kills_low_hp(self):
        """Красный гриб может убить персонажа с 1–2 HP при 3 шагах poison."""
        state = _make_state(world={"stepOfDay": 3, "fedMorning": True, "fedEvening": True})
        state["player"]["inventory"].append({"itemId": "food_red_mushroom", "count": 1})
        state["player"]["resources"]["hp"]["current"] = 2
        state["player"]["resources"]["hp"]["max"] = 10

        # Съедаем — poison на 3 шага (-3 HP)
        state, _ = world_time.eat_food(state, "food_red_mushroom", _game_data)

        # Шаг 1: poison -1 → HP=1
        state, _ = world_time.advance_time(state, steps=1)
        assert state["player"]["resources"]["hp"]["current"] == 1
        # Шаг 2: poison -1 → HP=0 → death
        state, events = world_time.advance_time(state, steps=1)
        assert any(e["id"] == "player_died" for e in events)


# ---------------------------------------------------------------------------
# Г. Ночлег
# ---------------------------------------------------------------------------


class TestRestAtInn:
    def test_rest_not_in_village(self):
        """Ночлег вне деревни — ошибка."""
        state = _make_state()
        state["map"]["nodes"] = [
            {"id": "node_00", "type": "biome", "name": "Forest", "connections": []}
        ]
        new_state, events = world_time.rest_at_inn(state, _game_data)
        assert events[0]["id"] == "err_not_in_village"

    def test_rest_not_enough_gold(self):
        """Мало золота — ошибка."""
        state = _make_state(player={"gold": 3})
        new_state, events = world_time.rest_at_inn(state, _game_data)
        assert events[0]["id"] == "err_not_enough_gold"
        assert events[0]["required"] == 5

    def test_rest_advances_day(self):
        """Ночлег переводит время на day+1, stepOfDay=1."""
        state = _make_state(
            player={"gold": 100},
            world={"stepOfDay": 15, "fedMorning": True, "fedEvening": False},
        )
        new_state, events = world_time.rest_at_inn(state, _game_data)
        assert any(e["id"] == "inn_rested" for e in events)
        rested_event = [e for e in events if e["id"] == "inn_rested"][0]
        assert rested_event["cost"] == 5
        assert rested_event["newDay"] == 2
        assert new_state["world"]["stepOfDay"] == 1

    def test_rest_closes_evening(self):
        """Ночлег закрывает вечернее окно и переносит на новое утро."""
        state = _make_state(
            player={"gold": 100},
            world={"stepOfDay": 15, "fedMorning": True, "fedEvening": False},
        )
        new_state, events = world_time.rest_at_inn(state, _game_data)
        # После advance_time наступил новый день, fedEvening сброшено
        # Но ключевое — нет смерти от голода
        assert not any(e["id"] == "player_died" for e in events)
        assert new_state["world"]["stepOfDay"] == 1
        assert new_state["world"]["day"] == 2

    def test_rest_prevents_starvation(self):
        """Ночлег предотвращает голодную смерть во сне."""
        state = _make_state(
            player={"gold": 100},
            world={"stepOfDay": 6, "fedMorning": False, "fedEvening": False},
        )
        # Не ели — голод. Но ночлег закрывает окна и переносит время.
        new_state, events = world_time.rest_at_inn(state, _game_data)
        # Нет смерти от голода
        assert not any(e.get("reason") == "starvation_morning" for e in events)
        assert not any(e.get("reason") == "starvation_evening" for e in events)
        # Нет общей смерти
        assert not any(e["id"] == "player_died" for e in events)

    def test_rest_deducts_gold(self):
        """Ночлег списывает 5 золота."""
        state = _make_state(player={"gold": 100})
        new_state, _ = world_time.rest_at_inn(state, _game_data)
        assert new_state["player"]["gold"] == 95


# ---------------------------------------------------------------------------
# Д. Респавн монстров
# ---------------------------------------------------------------------------


class TestMonsterRespawn:
    def _make_biome_node(self, node_id: str, biome_id: str, cleared: bool = True):
        """Создаёт узел с биомом и зачищенным состоянием."""
        return {
            "id": node_id,
            "type": "biome",
            "biomeId": biome_id,
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

    def test_respawn_on_day_5(self):
        """В зачищенном диком узле монстр появляется на 5-й день."""
        state = _make_state()
        # Добавляем биомный узел
        biome_node = self._make_biome_node("node_01", "biome_meadow")
        state["map"]["nodes"].append(biome_node)

        # Прогоняем 5 дней (каждый день advance_time с шага 20→1)
        for day in range(5):
            state["world"]["stepOfDay"] = 20
            state, _ = world_time.advance_time(state, steps=1, game_data=_game_data)
            # После перехода на новый день daysSinceCleared увеличивается
            # На 5-й день должен быть респавн

        # Проверяем: node_01 должен иметь монстра
        node = [n for n in state["map"]["nodes"] if n["id"] == "node_01"][0]
        assert node["state"]["monster"] is not None
        assert "mobId" in node["state"]["monster"]
        assert node["state"]["monster"]["revealed"] is False

    def test_no_respawn_in_village(self):
        """В деревне монстры не респавнятся."""
        state = _make_state()
        # Прогоняем 5 дней
        for _ in range(5):
            state["world"]["stepOfDay"] = 20
            state, _ = world_time.advance_time(state, steps=1)

        village_node = [n for n in state["map"]["nodes"] if n["id"] == "node_00"][0]
        # В деревне монстр не появляется
        assert village_node["state"]["monster"] is None

    def test_no_respawn_with_existing_monster(self):
        """Не респавнит, если монстр уже жив."""
        state = _make_state()
        biome_node = self._make_biome_node("node_01", "biome_meadow")
        biome_node["state"]["monster"] = {"mobId": "mob_wolf_forest", "revealed": True, "hp": 10, "maxHp": 10}
        state["map"]["nodes"].append(biome_node)

        for _ in range(5):
            state["world"]["stepOfDay"] = 20
            state, _ = world_time.advance_time(state, steps=1)

        node = [n for n in state["map"]["nodes"] if n["id"] == "node_01"][0]
        # Монстр не респавнится — он уже есть
        assert node["state"]["monster"] is not None
        assert node["state"]["monster"]["mobId"] == "mob_wolf_forest"

    def test_respawn_event(self):
        """Событие monster_respawned при респавне."""
        state = _make_state()
        biome_node = self._make_biome_node("node_01", "biome_meadow")
        state["map"]["nodes"].append(biome_node)

        all_events: list[dict] = []
        for _ in range(5):
            state["world"]["stepOfDay"] = 20
            state, events = world_time.advance_time(state, steps=1, game_data=_game_data)
            all_events.extend(events)

        assert any(e["id"] == "monster_respawned" for e in all_events)
        respawn_event = [e for e in all_events if e["id"] == "monster_respawned"][0]
        assert respawn_event["nodeId"] == "node_01"
        assert "mobId" in respawn_event
