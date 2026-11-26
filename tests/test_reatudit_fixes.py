# -*- coding: utf-8 -*-
"""Регрессионные тесты повтора аудита R-1..R-7.

R-1 — двойной реген монстра; R-2 — cast/use_item не доигрывали раунд;
R-3 — яд onHitDot не применялся к игроку; R-4 — KeyError 'resources' при
уроне заклинаниями/бомбами в реальном бою; R-5/R-6/R-7 — строки журнала.
"""

from __future__ import annotations

import random
from pathlib import Path

from cli.app import event_text
from engine.combat import combat_step, start_combat
from engine.data_loader import GameData
from engine.models import create_initial_state

_DATA_DIR = Path(__file__).parent.parent / "data"
_GD = GameData(str(_DATA_DIR))


def _make_state(
    mob_id: str = "mob_wolf_forest",
    player_hp: int = 900,
    player_skills: dict | None = None,
    inventory: list | None = None,
) -> dict:
    """Состояние с раскрытым монстром в текущем узле (по образцу test_combat_rounds)."""
    state = create_initial_state(seed=42, difficulty="normal")
    player = state["player"]
    player["skills"].update({"melee_light": 6, "melee_heavy": 6})
    if player_skills:
        player["skills"].update(player_skills)
    player["resources"]["hp"] = {"current": player_hp, "max": player_hp}
    player["resources"]["mp"] = {"current": 20, "max": 20}
    state["world"]["fedMorning"] = True
    state["world"]["fedEvening"] = True
    if inventory is not None:
        player["inventory"] = [dict(entry) for entry in inventory]
    node = state["map"]["nodes"][0]
    node["state"]["spawnRolled"] = True
    node["state"]["monster"] = {"mobId": mob_id, "revealed": True, "hp": 40, "maxHp": 40}
    return state


def _start(state: dict, seed: int, tmp_path, monster_hp: int | None = None):
    state, events = start_combat(
        state, _GD, is_ambush=False, rng=random.Random(seed),
        session_path=str(tmp_path / "session.json"),
        template_path=str(tmp_path / "template.json"),
    )
    if monster_hp is not None and state["world"].get("activeCombat"):
        monster = state["world"]["activeCombat"]["monster"]
        monster["hp"] = monster_hp
        monster["maxHp"] = max(monster["maxHp"], monster_hp)
    return state, events


def _step(state: dict, command: dict, seed: int, tmp_path):
    return combat_step(
        state, command, _GD, rng=random.Random(seed),
        session_path=str(tmp_path / "session.json"),
        template_path=str(tmp_path / "template.json"),
    )


class TestR1SingleRegen:
    """R-1: реген применяется один раз за интервал, каждое применение — с событием."""

    def test_troll_regen_is_single_and_documented(self, tmp_path) -> None:
        state = _make_state(mob_id="mob_troll_hill")
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=10)
        total_attack = 0
        total_regen = 0
        for i in range(4):
            state, events = _step(state, {"type": "attack"}, seed=100 + i, tmp_path=tmp_path)
            assert state["world"]["activeCombat"] is not None, events
            total_attack += sum(e.get("damage", 0) for e in events if e["id"] == "attack_hit")
            total_regen += sum(e.get("amount", 0) for e in events if e["id"] == "monster_regen")
        # ни одного незадокументированного применения регена
        assert state["world"]["activeCombat"]["monster"]["hp"] == 10 - total_attack + total_regen


class TestR2CastUseItemEndRound:
    """R-2: cast/use_item доигрывают раунд (round растёт, кулдаун тикает)."""

    def test_use_item_advances_round(self, tmp_path) -> None:
        state = _make_state(inventory=[{"itemId": "pot_heal_minor", "count": 3}])
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=100)
        start_round = state["world"]["activeCombat"]["round"]
        for i in range(3):
            state, events = _step(
                state, {"type": "use_item", "itemId": "pot_heal_minor"},
                seed=50 + i, tmp_path=tmp_path,
            )
            assert not any(e["id"].startswith("err_") for e in events), events
            assert state["world"]["activeCombat"] is not None, events
        assert state["world"]["activeCombat"]["round"] == start_round + 3

    def test_cast_advances_round(self, tmp_path) -> None:
        state = _make_state(player_skills={"pyromancy": 1})
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=100)
        start_round = state["world"]["activeCombat"]["round"]
        for i in range(3):
            state, events = _step(
                state, {"type": "cast", "spellId": "spl_spark"},
                seed=60 + i, tmp_path=tmp_path,
            )
            assert not any(e["id"].startswith("err_") for e in events), events
            assert state["world"]["activeCombat"] is not None, events
        assert state["world"]["activeCombat"]["round"] == start_round + 3

    def test_cooldown_ticks_over_use_item_round(self, tmp_path) -> None:
        state = _make_state(inventory=[{"itemId": "pot_heal_minor", "count": 1}])
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=100)
        state["world"]["combatFlags"]["crushingCooldown"] = 4
        state, events = _step(
            state, {"type": "use_item", "itemId": "pot_heal_minor"},
            seed=70, tmp_path=tmp_path,
        )
        assert not any(e["id"].startswith("err_") for e in events), events
        assert state["world"]["combatFlags"]["crushingCooldown"] == 3


class TestR3OnHitDot:
    """R-3: яд паука записывается в состояние и тикает по игроку."""

    def test_spider_poison_applies_and_ticks(self, tmp_path) -> None:
        state = _make_state(mob_id="mob_spider_giant",
                            player_skills={"melee_light": 0, "melee_heavy": 0})
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=500)
        poisoned = False
        for i in range(60):
            state, events = _step(state, {"type": "attack"}, seed=200 + i, tmp_path=tmp_path)
            if state["world"]["activeCombat"] is None:
                break
            if any(e["id"] == "monster_onhit_dot" for e in events):
                poisoned = True
                effects = state["world"].get("activeEffects", [])
                dot = next((e for e in effects if e.get("id") == "onHitDot"), None)
                assert dot is not None, effects  # эффект реально записан (R-3)
                assert dot["type"] == "poison"
                assert dot["hpDeltaPerTurn"] == -1
                # яд вешается в ход монстра и тикает в конце ЭТОГО же раунда:
                # 3 -> 2 (допустимо 3, если тик ещё не случился)
                assert dot["ticksLeft"] in (2, 3), effects
                ticks_before = dot["ticksLeft"]
                # следующий раунд: тик уменьшает счётчик
                state, events = _step(state, {"type": "attack"}, seed=300 + i, tmp_path=tmp_path)
                if state["world"]["activeCombat"] is None:
                    break
                effects = state["world"].get("activeEffects", [])
                dot = next((e for e in effects if e.get("id") == "onHitDot"), None)
                assert dot is None or dot["ticksLeft"] < ticks_before, effects
                break
        assert poisoned, "яд паука не сработал ни разу за 60 раундов (шанс 25%)"


class TestR4SpellBombDamage:
    """R-4: урон заклинаний и бомб по реальному (плоскому) монстру."""

    def test_cast_spark_damages_and_burns(self, tmp_path) -> None:
        state = _make_state(player_skills={"pyromancy": 10})
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=50)
        hit = False
        for i in range(30):
            state, events = _step(
                state, {"type": "cast", "spellId": "spl_spark"},
                seed=400 + i, tmp_path=tmp_path,
            )
            if state["world"]["activeCombat"] is None:
                break
            spell_casts = [e for e in events if e["id"] == "spell_cast"]
            if spell_casts:
                damage = spell_casts[0]["damage"]
                # burn из каста тикает в конце этого же раунда (spl_spark: -1/ход)
                dot_ticks = sum(e.get("damage", 0) for e in events if e["id"] == "monster_dot_tick")
                monster = state["world"]["activeCombat"]["monster"]
                # урон перенесён в возвращённое состояние (write-back R-4)
                assert monster["hp"] == 50 - damage - dot_ticks, (monster["hp"], damage, dot_ticks)
                # burn тоже перенесён через внешнюю ссылку цели
                assert any(eff.get("id") == "burn" for eff in monster.get("activeEffects", []))
                hit = True
                break
            # промах — ход всё равно доигран; восстанавливаем HP для следующей попытки
            assert state["world"]["activeCombat"]["round"] > 1
            state["world"]["activeCombat"]["monster"]["hp"] = 50
            state["world"]["activeCombat"]["monster"]["maxHp"] = 50
        assert hit, "spl_spark не попал за 30 попыток"

    def test_bomb_damages_and_round_advances(self, tmp_path) -> None:
        state = _make_state(inventory=[{"itemId": "bmb_fire", "count": 2}])
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=50)
        start_round = state["world"]["activeCombat"]["round"]
        hit = False
        for i in range(30):
            state, events = _step(
                state, {"type": "use_item", "itemId": "bmb_fire"},
                seed=500 + i, tmp_path=tmp_path,
            )
            if state["world"]["activeCombat"] is None:
                break
            bombs = [e for e in events if e["id"] == "bomb_hit"]
            if bombs:
                damage = bombs[0]["damage"]
                monster = state["world"]["activeCombat"]["monster"]
                assert monster["hp"] == 50 - damage, (monster["hp"], damage)
                # раунд доигран (R-2 вместе с R-4)
                assert state["world"]["activeCombat"]["round"] == start_round + i + 1
                hit = True
                break
            # промах — реставрируем бомбу и HP для следующей попытки
            state["player"]["inventory"].append({"itemId": "bmb_fire", "count": 1})
            state["world"]["activeCombat"]["monster"]["hp"] = 50
            state["world"]["activeCombat"]["monster"]["maxHp"] = 50
        assert hit, "bmb_fire не попал за 30 попыток"

    def test_bomb_kill_yields_victory(self, tmp_path) -> None:
        state = _make_state(inventory=[{"itemId": "bmb_fire", "count": 5}])
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=3)
        victory = False
        for i in range(30):
            state, events = _step(
                state, {"type": "use_item", "itemId": "bmb_fire"},
                seed=600 + i, tmp_path=tmp_path,
            )
            if any(e["id"] == "bomb_hit" for e in events):
                ids = [e["id"] for e in events]
                # событие бомбы не выбрасывается при килле (журнал видит удар)
                assert "bomb_hit" in ids, ids
                assert "combat_victory" in ids, ids
                assert state["world"]["activeCombat"] is None
                assert state["world"]["inCombat"] is False
                victory = True
                break
            if state["world"]["activeCombat"] is None:
                break
            state["player"]["inventory"].append({"itemId": "bmb_fire", "count": 1})
            state["world"]["activeCombat"]["monster"]["hp"] = 3
            state["world"]["activeCombat"]["monster"]["maxHp"] = 3
        assert victory, "бомба не попала за 30 попыток"


class TestJournalStrings:
    """R-5/R-6/R-7: строки журнала без сырых плейсхолдеров и id."""

    def test_battle_victory_without_placeholders(self) -> None:
        text = event_text({"id": "combat_victory"}, _GD)
        assert "{" not in text and "}" not in text
        assert text.strip()

    def test_reaudit_event_ids_rendered(self) -> None:
        cases = {
            "monster_onhit_dot": "отрав",
            "effect_expired": "истек",
            "monster_effect_expired": "законч",
            "sys_permadeath_reset": "сброш",
        }
        for eid, fragment in cases.items():
            text = event_text({"id": eid}, _GD)
            assert text != eid, (eid, text)
            assert fragment in text.lower(), (eid, text)
            assert "{" not in text

    def test_dead_combat_started_key_removed(self) -> None:
        # R-7: ключ combat_started никем не читается — удалён
        assert "combat_started" not in _GD.strings
        # рендер combat_started идёт через battle_start
        text = event_text({"id": "combat_started", "enemy": "Волк", "mobId": "mob_wolf_forest"}, _GD)
        assert "Волк" in text
