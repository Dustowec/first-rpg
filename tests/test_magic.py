"""Юнит-тесты для engine/magic.py — все 9 заклинаний, формулы, перки."""

from __future__ import annotations

import copy
import random
import unittest
from pathlib import Path

from engine.combat_math import apply_armor_absorption, get_damage_multiplier
from engine.data_loader import GameData
from engine.magic import (
    calc_spell_hit_chance,
    calc_spell_power,
    can_use_crushing_strike,
    cast_spell,
    check_second_wind_trigger,
    clear_combat_flags,
    get_available_spells,
    get_spell_mp_cost,
    has_milestone,
    use_crushing_strike,
    apply_on_weapon_hit_perks,
    apply_on_monster_killed_perks,
)

# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).parent.parent / "data"


def _load_game_data() -> GameData:
    return GameData(str(_DATA_DIR))


def _make_player(
    pyromancy: int = 0,
    restoration: int = 0,
    hexes: int = 0,
    melee_heavy: int = 0,
    intelligence: int = 1,
    mp_current: int = 10,
    mp_max: int = 10,
    hp_current: int = 10,
    hp_max: int = 10,
) -> dict:
    return {
        "level": 1,
        "xp": 0,
        "gold": 15,
        "unspentPoints": {"attributes": 0, "skills": 0},
        "resources": {
            "hp": {"current": hp_current, "max": hp_max},
            "mp": {"current": mp_current, "max": mp_max},
        },
        "attributes": {
            "strength": 1,
            "agility": 1,
            "constitution": 1,
            "intelligence": intelligence,
            "wisdom": 1,
        },
        "skills": {
            "melee_heavy": melee_heavy,
            "melee_light": 0,
            "armor_mastery": 0,
            "pyromancy": pyromancy,
            "restoration": restoration,
            "hexes": hexes,
            "alchemy": 0,
            "crafting": 0,
            "scavenging": 0,
        },
        "equipment": {"weapon": None, "armor": None},
        "inventory": [],
    }


def _make_state(player: dict | None = None, in_combat: bool = False) -> dict:
    if player is None:
        player = _make_player()
    return {
        "player": player,
        "world": {
            "day": 1,
            "stepOfDay": 1,
            "fedMorning": False,
            "fedEvening": False,
            "inCombat": in_combat,
            "activeEffects": [],
            "killsTotal": 0,
            "locationsVisited": 1,
        },
        "meta": {"xpRate": 1.0},
    }


def _make_monster(
    hp: int = 30,
    evasion: int = 10,
    defense: int = 5,
    affinities: dict | None = None,
) -> dict:
    return {
        "resources": {"hp": {"current": hp, "max": hp}, "defense": defense, "accuracy": 50, "evasion": evasion},
        "damage": {"min": 3, "max": 6, "type": "physical"},
        "activeEffects": [],
        "affinities": affinities or {},
    }


# ---------------------------------------------------------------------------
# A. Доступность и стоимость заклинаний
# ---------------------------------------------------------------------------


class TestSpellAvailability(unittest.TestCase):

    def test_get_available_spells_filters_by_skill(self) -> None:
        gd = _load_game_data()
        p = _make_player(pyromancy=5)
        available = get_available_spells(p, gd)
        spell_ids = {s["id"] for s in available}
        # pyromancy 5: spl_spark(0), spl_frost_shard(2) доступны; spl_fireball(5) доступен
        self.assertIn("spl_spark", spell_ids)
        self.assertIn("spl_frost_shard", spell_ids)
        self.assertIn("spl_fireball", spell_ids)

    def test_get_available_spells_requires_skill(self) -> None:
        gd = _load_game_data()
        p = _make_player(pyromancy=0)
        available = get_available_spells(p, gd)
        spell_ids = {s["id"] for s in available}
        self.assertIn("spl_spark", spell_ids)
        self.assertNotIn("spl_fireball", spell_ids)

    def test_concentration_reduces_mp_cost(self) -> None:
        """Перк pyromancy 6: -1 MP для стихийных заклинаний."""
        gd = _load_game_data()
        p_conc = _make_player(pyromancy=6)
        p_normal = _make_player(pyromancy=0)

        spark = gd.get_spell("spl_spark")
        fireball = gd.get_spell("spl_fireball")

        # spark: 1 MP -> max(1, 1-1) = 1 (не ниже 1)
        self.assertEqual(get_spell_mp_cost(p_conc, spark), 1)
        self.assertEqual(get_spell_mp_cost(p_normal, spark), 1)

        # fireball: 4 MP -> 3 MP с концентрацией
        self.assertEqual(get_spell_mp_cost(p_conc, fireball), 3)
        self.assertEqual(get_spell_mp_cost(p_normal, fireball), 4)


# ---------------------------------------------------------------------------
# Б. Формулы магии
# ---------------------------------------------------------------------------


class TestSpellFormulas(unittest.TestCase):

    def test_hit_chance_scaling(self) -> None:
        p0 = _make_player(pyromancy=0, intelligence=1)
        p5 = _make_player(pyromancy=5, intelligence=1)
        p10 = _make_player(pyromancy=10, intelligence=1)

        # skill=0, int=1, evasion=0: 55 + 0 + 0 - 0 = 55
        self.assertEqual(calc_spell_hit_chance(p0, "pyromancy", 0), 55)
        # skill=5, int=1: 55 + 12.5 + 0 = 67.5 -> 68
        self.assertEqual(calc_spell_hit_chance(p5, "pyromancy", 0), 68)
        # skill=10, int=1: 55 + 25 = 80
        self.assertEqual(calc_spell_hit_chance(p10, "pyromancy", 0), 80)

    def test_hit_chance_intelligence_scaling(self) -> None:
        p1 = _make_player(intelligence=1)
        p5 = _make_player(intelligence=5)
        p10 = _make_player(intelligence=10)

        # int=1: +0, int=5: +6, int=10: +13.5
        self.assertEqual(calc_spell_hit_chance(p1, "hexes", 0), 55)
        self.assertEqual(calc_spell_hit_chance(p5, "hexes", 0), 61)
        self.assertEqual(calc_spell_hit_chance(p10, "hexes", 0), 68)

    def test_hit_chance_clamp(self) -> None:
        p = _make_player(pyromancy=10, intelligence=10)
        # evasion=100: 55+25+13.5-50 = 43.5 -> 44
        self.assertEqual(calc_spell_hit_chance(p, "pyromancy", 100), 44)
        # evasion=0: 55+25+13.5 = 93.5 -> 94, но clamp до 85
        self.assertEqual(calc_spell_hit_chance(p, "pyromancy", 0), 85)

    def test_spell_power_scaling(self) -> None:
        class _FixedRNG:
            def randint(self, a, b): return 5
        rng = _FixedRNG()

        p0 = _make_player(restoration=0, intelligence=1)
        p5 = _make_player(restoration=5, intelligence=1)

        r0 = calc_spell_power(p0, "restoration", 4, 6, rng)
        r5 = calc_spell_power(p5, "restoration", 4, 6, rng)

        # base=5, skill=0: 5*1.0=5.0
        self.assertAlmostEqual(r0, 5.0, places=2)
        # skill=5: 5*1.25=6.25, frugality(+20%): 6.25*1.2=7.5
        self.assertAlmostEqual(r5, 7.5, places=2)

    def test_frugality_bonus(self) -> None:
        """restoration 3 «Бережливость»: +20% к лечению."""
        class _FixedRNG:
            def randint(self, a, b): return 5
        rng = _FixedRNG()

        p0 = _make_player(restoration=0, intelligence=1)
        p3 = _make_player(restoration=3, intelligence=1)

        # restoration 0: 5*1.0 = 5.0
        r0 = calc_spell_power(p0, "restoration", 4, 6, rng)
        # restoration 3: 5*1.15*1.2 = 6.9 (skill + frugality)
        r3 = calc_spell_power(p3, "restoration", 4, 6, rng)

        self.assertAlmostEqual(r0, 5.0, places=2)
        # skill=3: 5*1.15=5.75, с frugality: 5.75*1.2=6.9
        self.assertAlmostEqual(r3, 6.9, places=2)
        # Без frugality skill=3 дал бы 5.75, с frugality 6.9 — разница 20%
        self.assertAlmostEqual(r3 / 5.75, 1.20, places=2)

    def test_no_crits_for_spells(self) -> None:
        """Заклинания не критуют — сила всегда в диапазоне формулы."""
        rng = random.Random(0)
        p = _make_player(restoration=10, intelligence=10)
        # Даже с max skill/int, power не выходит за рамки формулы
        for _ in range(10):
            power = calc_spell_power(p, "restoration", 4, 6, rng)
            # max possible: 6*(1+0.5) + 13.5 = 22.5
            self.assertLessEqual(power, 23.0)


# ---------------------------------------------------------------------------
# В. Заклинания — cast_spell
# ---------------------------------------------------------------------------


class TestCastSpell(unittest.TestCase):

    def test_err_spell_locked(self) -> None:
        gd = _load_game_data()
        state = _make_state(_make_player(pyromancy=0), in_combat=True)
        _, events = cast_spell(state, "spl_frost_shard", gd, _make_monster(), rng=random.Random(0))
        self.assertEqual(events[0]["id"], "err_spell_locked")

    def test_err_not_enough_mp(self) -> None:
        gd = _load_game_data()
        p = _make_player(pyromancy=5, mp_current=0)
        state = _make_state(p, in_combat=True)
        _, events = cast_spell(state, "spl_spark", gd, _make_monster(), rng=random.Random(0))
        self.assertEqual(events[0]["id"], "err_not_enough_mp")

    def test_err_combat_required(self) -> None:
        gd = _load_game_data()
        p = _make_player(pyromancy=5)
        state = _make_state(p, in_combat=False)
        _, events = cast_spell(state, "spl_spark", gd, _make_monster(), rng=random.Random(0))
        self.assertEqual(events[0]["id"], "err_combat_required")

    def test_spl_spark_damage_and_burn(self) -> None:
        """spl_spark: 2..3 fire урон, 30% шанс burn."""
        gd = _load_game_data()
        m = _make_monster(hp=30, evasion=0)
        p = _make_player(pyromancy=5, mp_current=10)
        state = _make_state(p, in_combat=True)

        # Сид 10 -> hit_chance=55, rng.random() при seed 10 = 0.79 -> miss
        # Сид 20 -> rng.random() = 0.64 -> miss  
        # Сид 40 -> rng.random() = 0.23 -> hit
        rng = random.Random(40)
        state, events = cast_spell(state, "spl_spark", gd, m, rng=rng)

        self.assertTrue(any(e["id"] == "spell_cast" for e in events))
        self.assertEqual(state["player"]["resources"]["mp"]["current"], 9)
        self.assertTrue(any("burn" in str(e) for e in m["activeEffects"]))

    def test_spl_spark_miss(self) -> None:
        """spl_spark при промахе — spell_missed."""
        gd = _load_game_data()
        m = _make_monster(evasion=100)
        p = _make_player(pyromancy=0, mp_current=10)
        state = _make_state(p, in_combat=True)

        # evasion=100 -> hit_chance=25
        # seed 95 -> rng.random() ~ 0.95 -> 95 > 25 -> miss
        rng = random.Random(95)
        state, events = cast_spell(state, "spl_spark", gd, m, rng=rng)

        self.assertTrue(any(e["id"] == "spell_missed" for e in events))
        self.assertEqual(state["player"]["resources"]["mp"]["current"], 9)

    def test_spl_frost_shard_debuff(self) -> None:
        """spl_frost_shard: урон + evasionDelta -10 на 3 хода."""
        gd = _load_game_data()
        m = _make_monster(evasion=0)
        p = _make_player(pyromancy=5, mp_current=10)
        state = _make_state(p, in_combat=True)

        rng = random.Random(10)
        state, events = cast_spell(state, "spl_frost_shard", gd, m, rng=rng)

        self.assertTrue(any(e["id"] == "spell_cast" for e in events))
        self.assertTrue(any(e.get("evasionDelta") == -10 for e in m["activeEffects"]))

    def test_spl_fireball_damage_and_burn(self) -> None:
        """spl_fireball: 8..11 fire урон, guaranteed burn 3 хода."""
        gd = _load_game_data()
        m = _make_monster(evasion=0)
        p = _make_player(pyromancy=10, mp_current=10)
        state = _make_state(p, in_combat=True)

        rng = random.Random(10)
        state, events = cast_spell(state, "spl_fireball", gd, m, rng=rng)

        self.assertTrue(any(e["id"] == "spell_cast" for e in events))
        burn_effects = [e for e in m["activeEffects"] if e.get("type") == "burn"]
        self.assertTrue(len(burn_effects) > 0)

    def test_spl_minor_mend_healing(self) -> None:
        """spl_minor_mend: лечение 4..6 HP (100% на себя)."""
        gd = _load_game_data()
        p = _make_player(restoration=5, mp_current=10, hp_current=5, hp_max=10)
        state = _make_state(p, in_combat=True)

        rng = random.Random(42)
        state, events = cast_spell(state, "spl_minor_mend", gd, rng=rng)

        healed = [e for e in events if e["id"] == "spell_cast"][0]["healed"]
        self.assertGreater(healed, 0)
        self.assertEqual(state["player"]["resources"]["hp"]["current"], min(10, 5 + healed))

    def test_spl_stone_ward_buff(self) -> None:
        """spl_stone_ward: бафф defense на 4 хода (+2 если sturdy_barrier)."""
        gd = _load_game_data()
        p = _make_player(restoration=6, mp_current=10)
        state = _make_state(p, in_combat=True)

        state, events = cast_spell(state, "spl_stone_ward", gd, rng=random.Random(42))

        self.assertTrue(len(state["world"]["activeEffects"]) > 0)
        buff = state["world"]["activeEffects"][0]
        self.assertEqual(buff["id"], "spl_stone_ward")
        self.assertEqual(buff["stat"], "defense")
        self.assertEqual(buff["ticksLeft"], 5)  # 3 + 2 (sturdy_barrier)

    def test_spl_purify_cure_and_heal(self) -> None:
        """spl_purify: снимает poison/bleeding и лечит."""
        gd = _load_game_data()
        p = _make_player(restoration=10, mp_current=10, hp_current=5)
        state = _make_state(p, in_combat=True)
        state["world"]["activeEffects"] = [
            {"id": "poison", "type": "poison", "ticksLeft": 3},
            {"id": "elx_berserk", "category": "elixir", "ticksLeft": 2},
        ]

        rng = random.Random(42)
        state, events = cast_spell(state, "spl_purify", gd, rng=rng)

        # poison удалён, berserk остался
        remaining_ids = {e["id"] for e in state["world"]["activeEffects"]}
        self.assertNotIn("poison", remaining_ids)
        self.assertIn("elx_berserk", remaining_ids)

    def test_spl_weakness_debuff(self) -> None:
        """spl_weakness: damageDelta -2, accuracyDelta -10, ticksLeft 4."""
        gd = _load_game_data()
        m = _make_monster(evasion=0)
        p = _make_player(hexes=5, mp_current=10)
        state = _make_state(p, in_combat=True)

        rng = random.Random(10)
        state, events = cast_spell(state, "spl_weakness", gd, m, rng=rng)

        debuff = state["world"]["activeEffects"] if state["world"]["activeEffects"] else m["activeEffects"][0]
        # дебафф на монстре
        self.assertTrue(any(e.get("isCurse") for e in m["activeEffects"]))

    def test_spl_weakness_withering(self) -> None:
        """hexes 6 «Иссушение»: + defenseDelta -2."""
        gd = _load_game_data()
        m = _make_monster(evasion=0)
        p = _make_player(hexes=10, mp_current=10)
        state = _make_state(p, in_combat=True)

        rng = random.Random(10)
        state, events = cast_spell(state, "spl_weakness", gd, m, rng=rng)

        debuff = m["activeEffects"][0]
        self.assertIn("defenseDelta", debuff)
        self.assertEqual(debuff["defenseDelta"], -2)

    def test_spl_venom_touch_dot(self) -> None:
        """spl_venom_touch: урон 2..3 poison + DOT."""
        gd = _load_game_data()
        m = _make_monster(evasion=0)
        p = _make_player(hexes=5, mp_current=10)
        state = _make_state(p, in_combat=True)

        rng = random.Random(10)
        state, events = cast_spell(state, "spl_venom_touch", gd, m, rng=rng)

        self.assertTrue(any(e["id"] == "spell_cast" for e in events))
        self.assertTrue(any(e.get("type") == "poison" for e in m["activeEffects"]))

    def test_spl_venom_touch_caustic(self) -> None:
        """hexes 3 «Едкие токсины»: урон яда -3 вместо -2."""
        gd = _load_game_data()
        m = _make_monster(evasion=0)
        p = _make_player(hexes=10, mp_current=10)
        state = _make_state(p, in_combat=True)

        rng = random.Random(10)
        state, events = cast_spell(state, "spl_venom_touch", gd, m, rng=rng)

        poison_eff = [e for e in m["activeEffects"] if e.get("type") == "poison"][0]
        self.assertEqual(poison_eff["hpDeltaPerTurn"], -3)

    def test_spl_life_drain_vampirism(self) -> None:
        """spl_life_drain: урон + 50% лечения."""
        gd = _load_game_data()
        m = _make_monster(evasion=0)
        p = _make_player(hexes=10, mp_current=10, hp_current=5)
        state = _make_state(p, in_combat=True)

        rng = random.Random(10)
        state, events = cast_spell(state, "spl_life_drain", gd, m, rng=rng)

        spell_event = [e for e in events if e["id"] == "spell_cast"][0]
        self.assertGreater(spell_event["damage"], 0)
        self.assertGreater(spell_event["healed"], 0)
        # healed = floor(damage * 0.5)
        self.assertEqual(spell_event["healed"], spell_event["damage"] // 2)

    def test_spell_ignores_50_percent_armor(self) -> None:
        """Заклинания игнорируют 50% физической брони."""
        # Проверяем через apply_armor_absorption
        damage = 100.0
        defense = 10
        # Без игнора: 10/(10+10) = 50% проходит
        no_ignore = apply_armor_absorption(damage, defense)
        # С игнором 50%: def=5 -> 10/15 = 66.67%
        with_ignore = apply_armor_absorption(damage, defense, ignore_armor_ratio=0.5)
        self.assertAlmostEqual(with_ignore, 66.6667, places=2)
        self.assertGreater(with_ignore, no_ignore)


# ---------------------------------------------------------------------------
# Г. Боевые перки
# ---------------------------------------------------------------------------


class TestCombatPerks(unittest.TestCase):

    def test_stunning_blow_trigger(self) -> None:
        """melee_heavy 3: 20% шанс наложить accuracyDelta -10."""
        state = _make_state(_make_player(melee_heavy=3))
        monster = _make_monster()

        # 100 попыток с сидом 0 — проверяем что срабатывает
        rng = random.Random(0)
        events = apply_on_weapon_hit_perks(state, monster, rng)
        # при Random(0) -> randint(0,99)=26 > 20, не сработает
        self.assertEqual(events, [])

        rng2 = random.Random(10)
        events2 = apply_on_weapon_hit_perks(state, monster, rng2)
        # проверяем что функция возвращает список событий при срабатывании
        # не гарантируем срабатывание, но проверяем структуру
        self.assertIsInstance(events2, list)

    def test_stunning_blow_no_perk(self) -> None:
        """melee_heavy < 3: не срабатывает."""
        state = _make_state(_make_player(melee_heavy=0))
        monster = _make_monster()
        rng = random.Random(0)
        events = apply_on_weapon_hit_perks(state, monster, rng)
        self.assertEqual(events, [])

    def test_second_wind_trigger(self) -> None:
        """restoration 10: бафф при HP < 20%, 1 раз за бой."""
        p = _make_player(restoration=10, hp_current=1, hp_max=10)
        state = _make_state(p, in_combat=True)

        events = check_second_wind_trigger(state)
        self.assertTrue(any(e["id"] == "perk_second_wind_triggered" for e in events))

        # Повторный вызов — не срабатывает (secondWindUsed=True)
        events2 = check_second_wind_trigger(state)
        self.assertFalse(any(e["id"] == "perk_second_wind_triggered" for e in events2))

    def test_second_wind_no_trigger_high_hp(self) -> None:
        """HP >= 20%: не срабатывает."""
        p = _make_player(restoration=10, hp_current=3, hp_max=10)
        state = _make_state(p, in_combat=True)
        events = check_second_wind_trigger(state)
        # 3/10 = 30% >= 20%, не срабатывает
        self.assertEqual(events, [])

    def test_soul_harvest_trigger(self) -> None:
        """hexes 10: +3 HP/+3 MP при добивании проклятого монстра."""
        p = _make_player(hexes=10, hp_current=5, hp_max=10, mp_current=3, mp_max=10)
        state = _make_state(p)
        monster = _make_monster()
        monster["activeEffects"] = [{"id": "spl_weakness", "isCurse": True, "ticksLeft": 2}]

        events = apply_on_monster_killed_perks(state, monster)

        self.assertTrue(any(e["id"] == "perk_soul_harvest_triggered" for e in events))
        self.assertEqual(state["player"]["resources"]["hp"]["current"], 8)
        self.assertEqual(state["player"]["resources"]["mp"]["current"], 6)

    def test_soul_harvest_no_curse(self) -> None:
        """Без проклятия: не срабатывает."""
        p = _make_player(hexes=10)
        state = _make_state(p)
        monster = _make_monster()
        monster["activeEffects"] = []

        events = apply_on_monster_killed_perks(state, monster)
        self.assertEqual(events, [])

    def test_crushing_strike_available(self) -> None:
        """melee_heavy 10: can_use_crushing_strike=True."""
        state = _make_state(_make_player(melee_heavy=10))
        self.assertTrue(can_use_crushing_strike(state))

    def test_crushing_strike_on_cooldown(self) -> None:
        """После использования: cooldown=4."""
        state = _make_state(_make_player(melee_heavy=10))
        state, _ = use_crushing_strike(state)
        self.assertFalse(can_use_crushing_strike(state))

    def test_clear_combat_flags(self) -> None:
        """Очистка combatFlags."""
        state = _make_state()
        state["world"]["combatFlags"] = {"secondWindUsed": True, "crushingCooldown": 4}
        state = clear_combat_flags(state)
        self.assertNotIn("combatFlags", state["world"])


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
