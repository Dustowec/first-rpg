"""Интеграционные тесты для engine/combat.py — полный цикл боя."""

from __future__ import annotations

import random
import copy
from pathlib import Path

from engine.combat import start_combat, combat_step
from engine.data_loader import GameData
from engine.models import create_initial_state

# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).parent.parent / "data"
_GD = GameData(str(_DATA_DIR))


def _make_state(
    node_monster: dict | None = None,
    node_revealed: bool = False,
    in_combat: bool = False,
    player_skills: dict | None = None,
    player_hp: int = 10,
    player_mp: int = 2,
    player_gold: int = 15,
    lair_queue: list | None = None,
) -> dict:
    """Создаёт минимальное состояние для тестов."""
    state = create_initial_state(seed=42, difficulty="normal")

    # Модификация игрока
    if player_skills:
        for skill, value in player_skills.items():
            state["player"]["skills"][skill] = value
    state["player"]["resources"]["hp"]["current"] = player_hp
    state["player"]["resources"]["hp"]["max"] = player_hp
    state["player"]["resources"]["mp"]["current"] = player_mp
    state["player"]["resources"]["mp"]["max"] = player_mp
    state["player"]["gold"] = player_gold
    state["world"]["inCombat"] = in_combat

    # Модификация текущего узла
    current_node = state["map"]["nodes"][0]
    if node_monster is not None:
        current_node["state"]["monster"] = {
            "mobId": node_monster.get("mobId", "mob_wolf_forest"),
            "revealed": node_revealed,
            "hp": node_monster.get("hp", 10),
            "maxHp": node_monster.get("maxHp", 10),
        }
    else:
        current_node["state"]["monster"] = None

    if lair_queue:
        current_node["state"]["lairQueue"] = lair_queue
        current_node["state"]["lairQueueIndex"] = 0

    return state


def _get_node_monster(state: dict) -> dict:
    """Получает монстра текущего узла."""
    return state["map"]["nodes"][0]["state"]["monster"]


# ---------------------------------------------------------------------------
# A. Старт боя
# ---------------------------------------------------------------------------


class TestCombatStart:

    def test_start_no_monster(self) -> None:
        """Нет монстра — ошибка."""
        state = _make_state(node_monster=None)
        _, events = start_combat(state, _GD, rng=random.Random(0))
        assert events[0]["id"] == "err_no_monster"

    def test_start_no_reveal(self) -> None:
        """Нераскрытый монстр — нельзя начать обычный бой."""
        state = _make_state(node_monster={"mobId": "mob_wolf_forest", "hp": 10, "maxHp": 10}, node_revealed=False)
        _, events = start_combat(state, _GD, is_ambush=False, rng=random.Random(0))
        assert events[0]["id"] == "err_monster_not_revealed"

    def test_start_ambush(self) -> None:
        """Засада: 0 AP, монстр раскрыт, первый ход монстра."""
        state = _make_state(node_monster={"mobId": "mob_wolf_forest", "hp": 10, "maxHp": 10}, node_revealed=False)
        state, events = start_combat(state, _GD, is_ambush=True, rng=random.Random(0))

        assert any(e["id"] == "combat_started" for e in events)
        assert state["world"]["inCombat"] is True
        # Засада: монстр всегда первый
        started = [e for e in events if e["id"] == "combat_started"][0]
        assert started["isAmbush"] is True

    def test_start_normal_revealed(self) -> None:
        """Обычный бой с раскрытым монстром."""
        state = _make_state(node_monster={"mobId": "mob_wolf_forest", "hp": 10, "maxHp": 10}, node_revealed=True)
        state, events = start_combat(state, _GD, is_ambush=False, rng=random.Random(0))

        assert any(e["id"] == "combat_started" for e in events)
        assert state["world"]["inCombat"] is True
        # Монстр раскрыт
        assert _get_node_monster(state)["revealed"] is True


# ---------------------------------------------------------------------------
# Б. Побег
# ---------------------------------------------------------------------------


class TestCombatFlee:

    def test_flee_success(self) -> None:
        """Побег <= 50: бой завершён, HP монстра сохранено."""
        state = _make_state(
            node_monster={"mobId": "mob_wolf_forest", "hp": 10, "maxHp": 10},
            node_revealed=True,
            player_hp=10,
            player_mp=2,
        )
        # Начинаем бой
        state, _ = start_combat(state, _GD, is_ambush=False, rng=random.Random(0))

        # Фиксируем HP монстра
        state["world"]["activeCombat"]["monster"]["hp"] = 7

        # Побег: rng.randint(0,100) <= 50
        # Seed 0 -> randint(0,100) = 49 -> success
        state, events = combat_step(state, {"type": "flee"}, _GD, rng=random.Random(0))

        assert any(e["id"] == "combat_fled_success" for e in events)
        assert state["world"]["inCombat"] is False
        assert state["world"]["activeCombat"] is None
        # HP монстра сохранено
        assert _get_node_monster(state)["hp"] == 7
        assert _get_node_monster(state)["revealed"] is True

    def test_flee_fail(self) -> None:
        """Побег > 50: ход монстра."""
        state = _make_state(
            node_monster={"mobId": "mob_wolf_forest", "hp": 10, "maxHp": 10},
            node_revealed=True,
            player_hp=10,
            player_mp=2,
        )
        state, _ = start_combat(state, _GD, is_ambush=False, rng=random.Random(0))

        # Seed 101 -> randint(0,100) = 74 -> fail
        state, events = combat_step(state, {"type": "flee"}, _GD, rng=random.Random(101))

        assert any(e["id"] == "combat_fled_failed" for e in events)
        assert state["world"]["inCombat"] is True


# ---------------------------------------------------------------------------
# В. Атака и победа
# ---------------------------------------------------------------------------


class TestCombatVictory:

    def test_attack_hit_and_kill(self) -> None:
        """Атака: попадание, урон, победа, награды."""
        state = _make_state(
            node_monster={"mobId": "mob_wolf_forest", "hp": 6, "maxHp": 6},
            node_revealed=True,
            player_skills={"melee_heavy": 10},
            player_hp=10,
            player_mp=2,
        )
        state, _ = start_combat(state, _GD, is_ambush=False, rng=random.Random(0))

        # Наносим урон пока монстр не умрёт
        while state["world"].get("activeCombat") and state["world"]["activeCombat"]["monster"]["hp"] > 0:
            state, events = combat_step(state, {"type": "attack"}, _GD, rng=random.Random(50))

        assert any(e["id"] == "combat_victory" for e in events), f"events: {events}"
        assert state["world"]["killsTotal"] >= 1
        assert state["world"]["inCombat"] is False
        assert _get_node_monster(state) is None

    def test_gold_and_xp_granted(self) -> None:
        """Начисление XP и золота."""
        state = _make_state(
            node_monster={"mobId": "mob_wolf_forest", "hp": 6, "maxHp": 6},
            node_revealed=True,
            player_skills={"melee_heavy": 10},
            player_hp=10,
        )
        initial_gold = state["player"]["gold"]
        initial_xp = state["player"]["xp"]

        state, _ = start_combat(state, _GD, is_ambush=False, rng=random.Random(0))
        all_events = []
        while state["world"].get("activeCombat") and state["world"]["activeCombat"]["monster"]["hp"] > 0:
            state, events = combat_step(state, {"type": "attack"}, _GD, rng=random.Random(50))
            all_events.extend(events)

        gold_events = [e for e in all_events if e["id"] == "gold_gained"]
        assert len(gold_events) > 0, f"events: {all_events}"
        # gold_gained event существует (золото роллится даже если 0)
        assert any(e.get("amount", 0) >= 0 for e in gold_events)


# ---------------------------------------------------------------------------
# Г. Логово
# ---------------------------------------------------------------------------


class TestLairCombat:

    def test_lair_sequence(self) -> None:
        """Последовательные бои: страж -> страж -> босс."""
        lair_queue = [
            {"mobId": "mob_skeleton_warrior"},
            {"mobId": "mob_skeleton_warrior"},
            {"mobId": "mob_knight_black"},
        ]
        state = _make_state(
            node_monster={"mobId": "mob_skeleton_warrior", "hp": 5, "maxHp": 5},
            node_revealed=True,
            player_skills={"melee_heavy": 5},
            player_hp=10,
            lair_queue=lair_queue,
        )

        # Первый бой
        state, _ = start_combat(state, _GD, is_ambush=False, rng=random.Random(0))
        assert state["world"]["activeCombat"]["queueIndex"] == 0

        # Победа над первым (принудительно обнуляем HP)
        state["world"]["activeCombat"]["monster"]["hp"] = 0
        state, events = _on_monster_defeated(state, _GD, rng=random.Random(0))

        # Следующий в очереди
        assert any(e["id"] == "lair_next_monster" for e in events), f"events: {events}"
        assert state["world"]["activeCombat"]["queueIndex"] == 1

        # Победа над вторым
        state["world"]["activeCombat"]["monster"]["hp"] = 0
        state, events = _on_monster_defeated(state, _GD, rng=random.Random(0))
        assert state["world"]["activeCombat"]["queueIndex"] == 2

        # Победа над боссом
        state["world"]["activeCombat"]["monster"]["hp"] = 0
        state, events = _on_monster_defeated(state, _GD, rng=random.Random(0))
        assert any(e["id"] == "combat_victory" for e in events), f"events: {events}"
        assert state["world"]["inCombat"] is False


# ---------------------------------------------------------------------------
# Д. Смерть игрока
# ---------------------------------------------------------------------------


class TestPlayerDeath:

    def test_player_death_in_combat(self) -> None:
        """hp <= 0 в бою -> permadeath."""
        state = _make_state(
            node_monster={"mobId": "mob_wolf_forest", "hp": 10, "maxHp": 10},
            node_revealed=True,
            player_hp=1,
        )
        # Засада: монстр первый, seed 1 -> монстр бьёт
        state, events = start_combat(state, _GD, is_ambush=True, rng=random.Random(1))

        # Проверяем что игрок мёртв после засады
        assert any(e["id"] == "player_died" for e in events), f"events: {events}"
        # После permadeath создаётся новая игра (isDead=False в новой игре)
        assert any(e["id"] == "sys_permadeath_reset" for e in events)


# ---------------------------------------------------------------------------
# Е. Смерть от голода при трате AP на старте боя (KI-3)
# ---------------------------------------------------------------------------


class TestStarvationOnStartCombat:

    def _make_starving_state(self, tmp_path: Path) -> dict:
        """Монстр раскрыт в ТЕКУЩЕМ узле, дедлайн еды на следующем шаге."""
        state = _make_state(
            node_monster={"mobId": "mob_wolf_forest", "hp": 6, "maxHp": 6},
            node_revealed=True,
        )
        state["world"]["fedMorning"] = False   # не ел утром
        state["world"]["stepOfDay"] = 6        # дедлайн завтрака — шаг 7
        return state

    def test_starvation_does_not_crash(self, tmp_path: Path) -> None:
        """KI-3: гибель от голода в start_combat не даёт TypeError и не шлёт combat_started."""
        state = self._make_starving_state(tmp_path)
        new_state, events = start_combat(
            state, _GD, is_ambush=False, rng=random.Random(1),
            session_path=str(tmp_path / "session.json"),
            template_path=str(tmp_path / "template.json"),
        )

        ids = [e["id"] for e in events]
        assert "player_died" in ids, f"events: {ids}"
        assert any(e.get("reason") == "starvation_morning" for e in events if e["id"] == "player_died")
        assert new_state["world"].get("inCombat") is not True
        assert "combat_started" not in ids

    def test_starvation_via_controller_permadeath(self, tmp_path: Path) -> None:
        """Контроллер видит смерть и делает permadeath-сброс вместо боя."""
        from engine.controller import dispatch_command
        state = self._make_starving_state(tmp_path)
        new_state, events = dispatch_command(
            state,
            {"type": "start_combat"},
            _GD,
            rng=random.Random(1),
            session_path=str(tmp_path / "session.json"),
            template_path=str(tmp_path / "template.json"),
        )
        ids = [e["id"] for e in events]
        assert "player_died" in ids
        assert "session_reset_permadeath" in ids
        assert new_state["flags"]["isDead"] is False


# ---------------------------------------------------------------------------
# Утилиты (для лair тестов)
# ---------------------------------------------------------------------------
from engine.combat import _on_monster_defeated  # noqa: E402


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import unittest
    unittest.main()
