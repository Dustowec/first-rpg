"""Р РµРіСЂРµСЃСЃРёРѕРЅРЅС‹Рµ С‚РµСЃС‚С‹ KI-1: Р·Р°РІРµСЂС€РµРЅРёРµ Р±РѕРµРІРѕРіРѕ СЂР°СѓРЅРґР° (СЂР°СѓРЅРґС‹, РєСѓР»РґР°СѓРЅС‹, DoT, СЂРµРіРµРЅ)."""

from __future__ import annotations

import random
from pathlib import Path

from engine.combat import combat_step, start_combat
from engine.data_loader import GameData
from engine.models import create_initial_state

_DATA_DIR = Path(__file__).parent.parent / "data"
_GD = GameData(str(_DATA_DIR))


def _make_state(
    mob_id: str = "mob_wolf_forest",
    mob_hp: int = 40,
    player_hp: int = 10,
    player_skills: dict | None = None,
    active_effects: list | None = None,
) -> dict:
    """РЎРѕСЃС‚РѕСЏРЅРёРµ СЃ СЂР°СЃРєСЂС‹С‚С‹Рј РјРѕРЅСЃС‚СЂРѕРј РІ С‚РµРєСѓС‰РµРј СѓР·Р»Рµ."""
    state = create_initial_state(seed=42, difficulty="normal")
    player = state["player"]
    # melee_light >= 6 вЂ” В«Р”Р»РёРЅРЅРѕРµ РґСЂРµРІРєРѕВ»: РёРіСЂРѕРє РІСЃРµРіРґР° Р±СЊС‘С‚ РїРµСЂРІС‹Рј (РґРµС‚РµСЂРјРёРЅРёР·Рј С‚РµСЃС‚Р°)
    player["skills"].update({"melee_light": 6, "melee_heavy": 6})
    if player_skills:
        player["skills"].update(player_skills)
    player["resources"]["hp"] = {"current": player_hp, "max": player_hp}
    player["resources"]["mp"] = {"current": 20, "max": 20}
    state["world"]["fedMorning"] = True
    state["world"]["fedEvening"] = True
    state["world"]["activeEffects"] = list(active_effects or [])

    node = state["map"]["nodes"][0]
    node["state"]["spawnRolled"] = True
    node["state"]["monster"] = {"mobId": mob_id, "revealed": True, "hp": mob_hp, "maxHp": mob_hp}
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


class TestRoundAdvances:

    def test_each_player_turn_is_one_round(self, tmp_path) -> None:
        """N Р·Р°РІРµСЂС€С‘РЅРЅС‹С… С…РѕРґРѕРІ Р°С‚Р°РєРё -> round РІС‹СЂРѕСЃ РЅР° N."""
        state = _make_state(mob_hp=60, player_hp=120)
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=60)
        start_round = state["world"]["activeCombat"]["round"]

        for i in range(3):
            state, events = _step(state, {"type": "attack"}, seed=100 + i, tmp_path=tmp_path)
            assert state["world"]["activeCombat"] is not None, events

        assert state["world"]["activeCombat"]["round"] == start_round + 3


class TestCrushingStrikeCooldown:

    def test_cooldown_ticks_and_restores(self, tmp_path) -> None:
        """В«РЎРѕРєСЂСѓС€РµРЅРёРµВ»: РєСѓР»РґР°СѓРЅ 4, СѓРјРµРЅСЊС€Р°РµС‚СЃСЏ РЅР° 1 Р·Р° СЂР°СѓРЅРґ Рё РІРѕР·РІСЂР°С‰Р°РµС‚СЃСЏ Рє 0."""
        state = _make_state(
            mob_hp=400, player_hp=600,
            player_skills={"melee_heavy": 10},
        )
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=60)

        # РџРµСЂРІРѕРµ РїСЂРёРјРµРЅРµРЅРёРµ РґРѕСЃС‚СѓРїРЅРѕ Рё СЃС‚Р°РІРёС‚ РєСѓР»РґР°СѓРЅ
        state, events = _step(state, {"type": "crushing_strike"}, seed=11, tmp_path=tmp_path)
        assert not any(e["id"] == "err_skill_on_cooldown" for e in events), events
        cooldown_after_use = state["world"]["combatFlags"]["crushingCooldown"]
        assert cooldown_after_use > 0

        # РќР° СЃР»РµРґСѓСЋС‰РµРј С…РѕРґСѓ вЂ” РµС‰С‘ РЅРµР»СЊР·СЏ
        state_denied, events = _step(state, {"type": "crushing_strike"}, seed=12, tmp_path=tmp_path)
        assert any(e["id"] == "err_skill_on_cooldown" for e in events)

        # РћС‚Р±РёРІР°РµРјСЃСЏ РѕР±С‹С‡РЅРѕР№ Р°С‚Р°РєРѕР№, РїРѕРєР° РЅРµ РёСЃС‚РµС‡С‘С‚ РєСѓР»РґР°СѓРЅ
        for i in range(cooldown_after_use):
            state, events = _step(state, {"type": "attack"}, seed=200 + i, tmp_path=tmp_path)
            assert state["world"]["activeCombat"] is not None, events
        assert state["world"]["combatFlags"]["crushingCooldown"] == 0

        # РўРµРїРµСЂСЊ СЃРЅРѕРІР° РґРѕСЃС‚СѓРїРЅРѕ
        state, events = _step(state, {"type": "crushing_strike"}, seed=31, tmp_path=tmp_path)
        assert not any(e["id"] == "err_skill_on_cooldown" for e in events), events


class TestCombatDotTicks:

    def test_monster_poison_ticks_each_round(self, tmp_path) -> None:
        """РЇРґ РЅР° РјРѕРЅСЃС‚СЂРµ РЅР°РЅРѕСЃРёС‚ СѓСЂРѕРЅ СЂР°Р· РІ СЂР°СѓРЅРґ Рё С‚РёРєР°РµС‚."""
        state = _make_state(mob_hp=60, player_hp=200)
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=60)
        state["world"]["activeCombat"]["monster"]["activeEffects"] = [
            {"type": "poison", "hpDeltaPerTurn": -2, "ticksLeft": 3}
        ]
        hp_before = state["world"]["activeCombat"]["monster"]["hp"]

        state, events = _step(state, {"type": "attack"}, seed=5, tmp_path=tmp_path)

        ticks = [e for e in events if e["id"] == "monster_dot_tick"]
        assert len(ticks) == 1, events
        assert ticks[0]["damage"] == 2
        # Сверяем монотонность: DoT учтён, ничего не «отрегенерировало»
        monster_now = state["world"]["activeCombat"]["monster"]
        assert monster_now["hp"] < hp_before
        assert monster_now["activeEffects"][0]["ticksLeft"] == 2

    def test_monster_dies_from_dot_yields_victory(self, tmp_path) -> None:
        """РЎРјРµСЂС‚СЊ РјРѕРЅСЃС‚СЂР° РѕС‚ DoT = РѕР±С‹С‡РЅР°СЏ РїРѕР±РµРґР° (combat_victory), Р±РµР· Р·Р°РІРёСЃС€РµРіРѕ Р±РѕСЏ."""
        state = _make_state(mob_hp=60, player_hp=200)
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=60)
        monster = state["world"]["activeCombat"]["monster"]
        monster["hp"] = 1
        monster["maxHp"] = 1
        monster["activeEffects"] = [{"type": "poison", "hpDeltaPerTurn": -5, "ticksLeft": 3}]

        state, events = _step(state, {"type": "attack"}, seed=5, tmp_path=tmp_path)

        ids = [e["id"] for e in events]
        assert state["world"]["inCombat"] is False, ids
        assert state["world"]["activeCombat"] is None
        assert "combat_victory" in ids
        assert sum(1 for e in events if e["id"] == "combat_victory") == 1


class TestTrollRegen:

    def test_troll_regenerates_on_even_rounds(self, tmp_path) -> None:
        """mob_troll_hill (regenIntervalRounds=2) СЂРµРіРµРЅРµСЂРёСЂСѓРµС‚ РЅР° РєР°Р¶РґРѕРј С‡С‘С‚РЅРѕРј СЂР°СѓРЅРґРµ."""
        state = _make_state(mob_id="mob_troll_hill", mob_hp=60, player_hp=400)
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=60)
        state["world"]["activeCombat"]["monster"]["hp"] = 10  # РјРµСЃС‚Рѕ РїРѕРґ СЂРµРіРµРЅ

        regen_events: list[dict] = []
        for i in range(4):
            state, events = _step(state, {"type": "attack"}, seed=300 + i, tmp_path=tmp_path)
            assert state["world"]["activeCombat"] is not None, events
            regen_events.extend(e for e in events if e["id"] == "monster_regen")

        # Р—Р° 4 СЂР°СѓРЅРґР° СЂРµРіРµРЅ СЃСЂР°Р±Р°С‚С‹РІР°РµС‚ РЅР° РєР°Р¶РґРѕРј С‡С‘С‚РЅРѕРј вЂ” РЅРµ РјРµРЅСЊС€Рµ 2 СЂР°Р·
        assert len(regen_events) >= 2, regen_events
        assert all(e["amount"] == 1 for e in regen_events)


class TestCombatEffectsCleared:

    def test_effects_cleared_on_victory(self, tmp_path) -> None:
        """Р‘РѕРµРІС‹Рµ СЌС„С„РµРєС‚С‹ (combatOnly) СЃРЅРёРјР°СЋС‚СЃСЏ РїСЂРё РїРѕР±РµРґРµ."""
        state = _make_state(mob_hp=60, player_hp=200)
        state["world"]["activeEffects"] = [
            {"id": "onHitDot", "type": "poison", "hpDeltaPerTurn": -1, "ticksLeft": 3, "combatOnly": True},
        ]
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=60)
        state["world"]["activeCombat"]["monster"]["hp"] = 1
        state["world"]["activeCombat"]["monster"]["maxHp"] = 1

        for i in range(20):
            state, events = _step(state, {"type": "attack"}, seed=50 + i, tmp_path=tmp_path)
            if not state["world"]["inCombat"]:
                break
        else:
            raise AssertionError(f"бой не закончился: {events}")

        assert all(not e.get("combatOnly") for e in state["world"]["activeEffects"])

    def test_effects_cleared_on_flee(self, tmp_path) -> None:
        """Р‘РѕРµРІС‹Рµ СЌС„С„РµРєС‚С‹ СЃРЅРёРјР°СЋС‚СЃСЏ РїСЂРё СѓСЃРїРµС€РЅРѕРј РїРѕР±РµРіРµ."""
        state = _make_state(
            mob_hp=60, player_hp=200,
            active_effects=[{"id": "poison", "hpDeltaPerTurn": -1, "ticksLeft": 3, "combatOnly": True}],
        )
        state, _ = _start(state, seed=1, tmp_path=tmp_path, monster_hp=60)

        for seed in range(30):
            trial, events = _step(state, {"type": "flee"}, seed=seed, tmp_path=tmp_path)
            if any(e["id"] == "combat_fled_success" for e in events):
                assert trial["world"]["activeEffects"] == []
                return
        raise AssertionError("РїРѕР±РµРі РЅРµ СѓРґР°Р»СЃСЏ РЅРё Р·Р° 30 СЃРёРґРѕРІ")


class TestMonsterAttackEvents:

    def test_enemy_attack_event_emitted(self, tmp_path) -> None:
        """KI-2: С…РѕРґ РјРѕРЅСЃС‚СЂР° РїРѕСЂРѕР¶РґР°РµС‚ battle_enemy_attack / battle_enemy_miss."""
        state = _make_state(mob_hp=60, player_hp=200)
        state, events = _start(state, seed=1, tmp_path=tmp_path, monster_hp=60)
        # melee_light >= 6 — игрок бьёт первым: ход монстра будет в этом шаге
        assert any(e["id"] == "combat_started" for e in events), events

        state, events = _step(state, {"type": "attack"}, seed=9, tmp_path=tmp_path)
        enemy_events = [
            e for e in events if e["id"] in ("battle_enemy_attack", "battle_enemy_miss")
        ]
        assert len(enemy_events) == 1, events
        assert enemy_events[0]["enemy"]
        assert "mobId" in enemy_events[0]
        if enemy_events[0]["id"] == "battle_enemy_attack":
            assert enemy_events[0]["damage"] >= 0

    def test_combat_started_event_carries_enemy_name(self, tmp_path) -> None:
        """combat_started содержит имя врага для battle_start."""
        state = _make_state(mob_hp=60, player_hp=200)
        _, events = _start(state, seed=1, tmp_path=tmp_path, monster_hp=60)
        started = [e for e in events if e["id"] == "combat_started"][0]
        assert started["enemy"]


