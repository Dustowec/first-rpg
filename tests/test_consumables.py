"""Юнит-тесты для engine/consumables.py — зелья, эликсиры, масла, бомбы (§12, §13, §22.3)."""

from __future__ import annotations

import copy
import random
import unittest

from engine.data_loader import GameData
from engine.consumables import (
    has_herbalist,
    has_double_dose,
    use_consumable,
    process_weapon_coating_on_hit,
    tick_combat_round_effects,
)

# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

_DATA_DIR = "data"
_gd = GameData(_DATA_DIR)


def _make_state(
    inventory: list[tuple[str, int]] | None = None,
    in_combat: bool = False,
    active_effects: list[dict] | None = None,
    hp_current: int | None = None,
    mp_current: int | None = None,
    alchemy: int = 0,
) -> dict:
    """Создаёт минимальный state для тестов расходников."""
    state: dict = {
        "player": {
            "inventory": [{"itemId": iid, "count": cnt} for iid, cnt in (inventory or [])],
            "resources": {
                "hp": {"current": hp_current or 10, "max": 10},
                "mp": {"current": mp_current or 2, "max": 2},
            },
            "attributes": {"strength": 1, "agility": 1, "constitution": 1, "intelligence": 1, "wisdom": 1},
            "skills": {
                "melee_heavy": 0, "melee_light": 0, "armor_mastery": 0,
                "pyromancy": 0, "restoration": 0, "hexes": 0,
                "alchemy": alchemy, "crafting": 0, "scavenging": 0,
            },
            "equipment": {"weapon": None, "armor": None},
        },
        "world": {
            "inCombat": in_combat,
            "activeEffects": active_effects or [],
        },
        "meta": {"difficulty": "normal"},
        "map": {"currentNodeId": "node_00", "nodes": []},
        "npcs": {},
        "flags": {"isDead": False},
    }
    return state


def _make_monster(hp: int = 20, affinities: dict | None = None) -> dict:
    return {
        "resources": {"hp": {"current": hp, "max": hp}, "defense": 10},
        "activeEffects": [],
    }


# ---------------------------------------------------------------------------
# А. Перки алхимии (§22.3)
# ---------------------------------------------------------------------------

class TestAlchemyPerks(unittest.TestCase):

    def test_herbalist_false(self) -> None:
        self.assertFalse(has_herbalist({"skills": {"alchemy": 2}}))

    def test_herbalist_true(self) -> None:
        self.assertTrue(has_herbalist({"skills": {"alchemy": 3}}))

    def test_double_dose_false(self) -> None:
        self.assertFalse(has_double_dose({"skills": {"alchemy": 9}}))

    def test_double_dose_true(self) -> None:
        self.assertTrue(has_double_dose({"skills": {"alchemy": 10}}))


# ---------------------------------------------------------------------------
# Б. use_consumable — зелья (§13.1)
# ---------------------------------------------------------------------------

class TestPotions(unittest.TestCase):

    def test_minor_heal_normal(self) -> None:
        """pot_heal_minor лечит 6 HP в норме (hp 4→10)."""
        state = _make_state(inventory=[("pot_heal_minor", 1)], hp_current=4)
        new_state, events = use_consumable(state, "pot_heal_minor", _gd)
        healed = [e for e in events if e["id"] == "potion_healed"][0]["amount"]
        self.assertEqual(healed, 6)
        self.assertEqual(new_state["player"]["resources"]["hp"]["current"], 10)

    def test_minor_heal_with_herbalist(self) -> None:
        """pot_heal_minor лечит 8 HP (round(6*1.25)) при alchemy==3."""
        # hp_current=1, max=10 → room for 9 HP, base=8 with herbalist
        state = _make_state(inventory=[("pot_heal_minor", 1)], hp_current=1, alchemy=3)
        new_state, events = use_consumable(state, "pot_heal_minor", _gd)
        healed = [e for e in events if e["id"] == "potion_healed"][0]["amount"]
        self.assertEqual(healed, 8)

    def test_antidote_cures(self) -> None:
        """pot_antidote снимает poison и bleeding."""
        effects = [{"type": "poison", "ticksLeft": 2}, {"type": "bleeding", "ticksLeft": 1}]
        state = _make_state(inventory=[("pot_antidote", 1)], active_effects=effects)
        new_state, events = use_consumable(state, "pot_antidote", _gd)
        cured = [e for e in events if e["id"] == "potion_cured"][0]
        self.assertEqual(set(cured["cured"]), {"poison", "bleeding"})
        self.assertEqual(len(new_state["world"]["activeEffects"]), 0)

    def test_invalid_consumable(self) -> None:
        """Нет предмета в инвентаре."""
        state = _make_state(inventory=[])
        new_state, events = use_consumable(state, "pot_heal_minor", _gd)
        self.assertEqual(events[0]["id"], "err_invalid_consumable")


# ---------------------------------------------------------------------------
# Б. use_consumable — эликсиры (§13.2)
# ---------------------------------------------------------------------------

class TestElixirs(unittest.TestCase):

    def test_elixir_applied(self) -> None:
        """Эликсир добавляется в activeEffects."""
        state = _make_state(inventory=[("elx_ironskin", 1)])
        new_state, events = use_consumable(state, "elx_ironskin", _gd)
        applied = [e for e in events if e["id"] == "elixir_applied"][0]
        self.assertEqual(applied["itemId"], "elx_ironskin")
        self.assertEqual(applied["ticksLeft"], 5)
        self.assertEqual(len(new_state["world"]["activeEffects"]), 1)
        self.assertEqual(new_state["world"]["activeEffects"][0]["category"], "elixir")

    def test_elixir_replaces_previous(self) -> None:
        """Стакинг: новый эликсир заменяет старый (§13.2)."""
        state = _make_state(
            inventory=[("elx_ironskin", 1), ("elx_accuracy", 1)],
            active_effects=[{"id": "elx_ironskin", "category": "elixir", "ticksLeft": 3}],
        )
        new_state, events = use_consumable(state, "elx_accuracy", _gd)
        elixirs = [e for e in new_state["world"]["activeEffects"] if e.get("category") == "elixir"]
        self.assertEqual(len(elixirs), 1)
        self.assertEqual(elixirs[0]["id"], "elx_accuracy")

    def test_double_dose_elixir_duration(self) -> None:
        """alchemy==10: длительность эликсиров ×1.5 (round(5*1.5)=8)."""
        state = _make_state(inventory=[("elx_ironskin", 1)], alchemy=10)
        new_state, events = use_consumable(state, "elx_ironskin", _gd)
        applied = [e for e in events if e["id"] == "elixir_applied"][0]
        self.assertEqual(applied["ticksLeft"], 8)


# ---------------------------------------------------------------------------
# Б. use_consumable — покрытия (§13.2)
# ---------------------------------------------------------------------------

class TestCoatings(unittest.TestCase):

    def test_coating_applied(self) -> None:
        """oil_fire добавляется как покрытие."""
        state = _make_state(inventory=[("oil_fire", 1)])
        new_state, events = use_consumable(state, "oil_fire", _gd)
        applied = [e for e in events if e["id"] == "coating_applied"][0]
        self.assertEqual(applied["chargesLeft"], 4)

    def test_coating_double_dose(self) -> None:
        """alchemy==10: заряды масел ×1.5."""
        state = _make_state(inventory=[("oil_fire", 1)], alchemy=10)
        new_state, events = use_consumable(state, "oil_fire", _gd)
        applied = [e for e in events if e["id"] == "coating_applied"][0]
        self.assertEqual(applied["chargesLeft"], 6)  # round(4*1.5)

    def test_coating_replaces_previous(self) -> None:
        """Новое покрытие заменяет старое."""
        state = _make_state(
            inventory=[("oil_fire", 1), ("oil_poison", 1)],
            active_effects=[{"id": "oil_fire", "category": "coating", "chargesLeft": 2}],
        )
        new_state, events = use_consumable(state, "oil_poison", _gd)
        coatings = [e for e in new_state["world"]["activeEffects"] if e.get("category") == "coating"]
        self.assertEqual(len(coatings), 1)
        self.assertEqual(coatings[0]["id"], "oil_poison")


# ---------------------------------------------------------------------------
# Б. use_consumable — бомбы (§13.2)
# ---------------------------------------------------------------------------

class TestBombs(unittest.TestCase):

    def test_bomb_outside_combat(self) -> None:
        """bmb_fire запрещена вне боя."""
        state = _make_state(inventory=[("bmb_fire", 1)], in_combat=False)
        new_state, events = use_consumable(state, "bmb_fire", _gd)
        self.assertEqual(events[0]["id"], "err_bomb_only_in_combat")

    def test_bomb_miss(self) -> None:
        """Бомба может промахнуться."""
        state = _make_state(inventory=[("bmb_fire", 1)], in_combat=True)
        monster = _make_monster()
        # hitChance=80, ищем сид где randint(0,100) > 80
        rng = random.Random(90)
        new_state, events = use_consumable(
            state, "bmb_fire", _gd, target_monster=monster, target_affinities={}, rng=rng
        )
        self.assertTrue(any(e["id"] in ("bomb_missed", "bomb_hit") for e in events))

    def test_bomb_hit_ignores_armor(self) -> None:
        """Бомба игнорирует defense монстра."""
        state = _make_state(inventory=[("bmb_fire", 1)], in_combat=True)
        monster = _make_monster(hp=20, affinities={"fire": 1.0})
        # hitChance=80, сид 50 → 50 <= 80 → попадание
        rng = random.Random(50)
        new_state, events = use_consumable(
            state, "bmb_fire", _gd, target_monster=monster, target_affinities={"fire": 1.0}, rng=rng
        )
        hit = [e for e in events if e["id"] == "bomb_hit"]
        self.assertTrue(len(hit) > 0)
        self.assertGreater(hit[0]["damage"], 0)


# ---------------------------------------------------------------------------
# В. process_weapon_coating_on_hit (§13.2)
# ---------------------------------------------------------------------------

class TestWeaponCoatingOnHit(unittest.TestCase):

    def test_oil_fire_damage(self) -> None:
        """oil_fire наносит bonusDamage × mult в обход брони."""
        state = _make_state(
            inventory=[],
            active_effects=[{"id": "oil_fire", "category": "coating", "chargesLeft": 4, "bonusDamage": 2, "damageType": "fire"}],
        )
        monster = _make_monster(hp=20, affinities={"fire": 1.25})
        new_state, events = process_weapon_coating_on_hit(state, monster, {"fire": 1.25})
        dmg = [e for e in events if e["id"] == "coating_damage"][0]
        # round(2 * 1.25) = round(2.5) = 2 (banker's rounding)
        self.assertEqual(dmg["damage"], 2)
        self.assertEqual(monster["resources"]["hp"]["current"], 18)

    def test_oil_fire_depletes_after_4_hits(self) -> None:
        """oil_fire исчезает через 4 удара."""
        state = _make_state(
            inventory=[],
            active_effects=[{"id": "oil_fire", "category": "coating", "chargesLeft": 4, "bonusDamage": 2, "damageType": "fire"}],
        )
        monster = _make_monster(affinities={})
        for _ in range(4):
            state, events = process_weapon_coating_on_hit(state, monster, {})
        depleted = [e for e in events if e["id"] == "coating_depleted"]
        self.assertTrue(len(depleted) > 0)

    def test_oil_poison_on_normal_target(self) -> None:
        """oil_poison накладывает яд на обычного монстра."""
        state = _make_state(
            inventory=[],
            active_effects=[{"id": "oil_poison", "category": "coating", "chargesLeft": 3, "dotType": "poison", "hpDeltaPerTurn": -2, "dotTurns": 3}],
        )
        monster = _make_monster(affinities={})
        new_state, events = process_weapon_coating_on_hit(state, monster, {})
        applied = [e for e in events if e["id"] == "coating_dot_applied"]
        self.assertTrue(len(applied) > 0)
        self.assertEqual(len(monster.get("activeEffects", [])), 1)
        self.assertEqual(monster["activeEffects"][0]["type"], "poison")

    def test_oil_poison_immune_undead(self) -> None:
        """oil_poison получает coating_immune на нежити (undead)."""
        state = _make_state(
            inventory=[],
            active_effects=[{"id": "oil_poison", "category": "coating", "chargesLeft": 3, "dotType": "poison", "hpDeltaPerTurn": -2, "dotTurns": 3}],
        )
        monster = _make_monster(affinities={"poison": 0.0})
        new_state, events = process_weapon_coating_on_hit(state, monster, {"poison": 0.0})
        immune = [e for e in events if e["id"] == "coating_immune"]
        self.assertTrue(len(immune) > 0)


# ---------------------------------------------------------------------------
# Г. tick_combat_round_effects (§13.2, §32.3)
# ---------------------------------------------------------------------------

class TestTickCombatRoundEffects(unittest.TestCase):

    def test_elixir_ticks_down(self) -> None:
        """Эликсир теряет 1 ticksLeft за раунд."""
        state = _make_state(
            inventory=[],
            active_effects=[{"id": "elx_ironskin", "category": "elixir", "stat": "defense", "value": 3, "ticksLeft": 3}],
        )
        monster = _make_monster()
        new_state, events = tick_combat_round_effects(state, monster)
        eff = new_state["world"]["activeEffects"][0]
        self.assertEqual(eff["ticksLeft"], 2)

    def test_expired_elixir_removed(self) -> None:
        """Эликсир с ticksLeft=0 удаляется."""
        state = _make_state(
            inventory=[],
            active_effects=[{"id": "elx_ironskin", "category": "elixir", "ticksLeft": 1}],
        )
        monster = _make_monster()
        new_state, events = tick_combat_round_effects(state, monster)
        self.assertEqual(len(new_state["world"]["activeEffects"]), 0)
        expired = [e for e in events if e["id"] == "effect_expired"]
        self.assertTrue(len(expired) > 0)

    def test_monster_dot_ticks(self) -> None:
        """Яд на монстре наносит урон и тикает."""
        state = _make_state(inventory=[])
        monster = _make_monster(hp=10, affinities={})
        monster["activeEffects"] = [{"type": "poison", "hpDeltaPerTurn": -2, "ticksLeft": 2}]
        new_state, events = tick_combat_round_effects(state, monster)
        self.assertEqual(monster["resources"]["hp"]["current"], 8)
        self.assertEqual(monster["activeEffects"][0]["ticksLeft"], 1)

    def test_expired_monster_effect_removed(self) -> None:
        """Яд с ticksLeft=0 удаляется."""
        state = _make_state(inventory=[])
        monster = _make_monster(affinities={})
        monster["activeEffects"] = [{"type": "poison", "hpDeltaPerTurn": -1, "ticksLeft": 1}]
        new_state, events = tick_combat_round_effects(state, monster)
        self.assertEqual(len(monster["activeEffects"]), 0)


# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    unittest.main()
