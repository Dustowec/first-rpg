"""Юнит-тесты для engine/crafting.py — ремесло, заточка, укрепление (§14, §15, §17, §22.3)."""

from __future__ import annotations

import copy
import random
import unittest

from engine.data_loader import GameData
from engine.crafting import (
    craft_recipe,
    get_available_recipes,
    reinforce_equipment,
    sharpen_weapon,
)

# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

_DATA_DIR = "data"
_gd = GameData(_DATA_DIR)


def _make_state(
    inventory: list[tuple[str, int]] | None = None,
    in_combat: bool = False,
    hp_current: int | None = None,
    mp_current: int | None = None,
    gold: int = 15,
    level: int = 1,
    alchemy: int = 0,
    crafting: int = 0,
    node_type: str = "forest_edge",
    equipped_weapon: bool = True,
    equipped_armor: bool = True,
    weapon_reinforced: bool = False,
    armor_reinforced: bool = False,
    weapon_sharpened: int = 0,
    step_of_day: int = 1,
    fed_morning: bool = True,
    fed_evening: bool = True,
    **extra_skills: int,
) -> dict:
    """Создаёт state для тестов ремесла."""
    skills: dict[str, int] = {
        "melee_heavy": 0,
        "melee_light": 0,
        "armor_mastery": 0,
        "pyromancy": 0,
        "restoration": 0,
        "hexes": 0,
        "alchemy": alchemy,
        "crafting": crafting,
        "scavenging": 0,
    }
    skills.update(extra_skills)

    equip_weapon: dict | None = None
    if equipped_weapon:
        equip_weapon = {
            "itemId": "wpn_club_simple",
            "durability": {"current": 15, "max": 15},
        }
        if weapon_sharpened > 0:
            equip_weapon["sharpenCharges"] = weapon_sharpened
        if weapon_reinforced:
            equip_weapon["reinforced"] = True
            equip_weapon["reinforceBonus"] = 1

    equip_armor: dict | None = None
    if equipped_armor:
        equip_armor = {
            "itemId": "arm_cloth_poor",
            "durability": {"current": 15, "max": 15},
        }
        if armor_reinforced:
            equip_armor["reinforced"] = True
            equip_armor["reinforceBonus"] = 1

    state: dict = {
        "player": {
            "level": level,
            "inventory": [{"itemId": iid, "count": cnt} for iid, cnt in (inventory or [])],
            "resources": {
                "hp": {"current": hp_current or 10, "max": 10},
                "mp": {"current": mp_current or 2, "max": 2},
            },
            "attributes": {
                "strength": 1, "agility": 1, "constitution": 1,
                "intelligence": 1, "wisdom": 1,
            },
            "skills": skills,
            "equipment": {"weapon": equip_weapon, "armor": equip_armor},
            "gold": gold,
        },
        "world": {
            "day": 1,
            "stepOfDay": step_of_day,
            "fedMorning": fed_morning,
            "fedEvening": fed_evening,
            "inCombat": in_combat,
            "activeEffects": [],
            "killsTotal": 0,
            "locationsVisited": 1,
        },
        "map": {
            "currentNodeId": "node_00",
            "nodes": [
                {
                    "id": "node_00",
                    "type": node_type,
                    "name": "Test Node",
                    "danger": 0,
                    "depth": 0,
                    "connections": [],
                    "state": {
                        "visited": True,
                        "spawnRolled": False,
                        "monster": None,
                    },
                }
            ],
        },
        "meta": {"difficulty": "normal"},
        "npcs": {},
        "flags": {"isDead": False, "deathReason": None},
    }
    return state


# ---------------------------------------------------------------------------
# А. Проверка станций (критерий 1)
# ---------------------------------------------------------------------------


class TestStations(unittest.TestCase):
    """Проверка станций: any, campfire, workbench."""

    def test_any_station_in_forest(self) -> None:
        """rec_pot_heal_minor (station=any) доступен в лесу."""
        state = _make_state(
            inventory=[("food_berries", 2), ("food_roots", 1)],
            node_type="forest_edge",
        )
        recipes = get_available_recipes(state, _gd)
        minor = [r for r in recipes if r["id"] == "rec_pot_heal_minor"][0]
        self.assertTrue(minor["stationOk"])

    def test_campfire_requires_camp_or_village(self) -> None:
        """rec_food_stew (station=campfire) не доступен в лесу."""
        state = _make_state(
            inventory=[("food_cabbage", 1), ("food_mushrooms", 1), ("food_roots", 1)],
            node_type="forest_edge",
        )
        recipes = get_available_recipes(state, _gd)
        stew = [r for r in recipes if r["id"] == "rec_food_stew"][0]
        self.assertFalse(stew["stationOk"])

    def test_campfire_available_in_camp(self) -> None:
        """rec_food_stew доступен в лагере."""
        state = _make_state(
            inventory=[("food_cabbage", 1), ("food_mushrooms", 1), ("food_roots", 1)],
            node_type="camp",
        )
        recipes = get_available_recipes(state, _gd)
        stew = [r for r in recipes if r["id"] == "rec_food_stew"][0]
        self.assertTrue(stew["stationOk"])

    def test_campfire_available_in_village(self) -> None:
        """rec_food_stew доступен в деревне."""
        state = _make_state(
            inventory=[("food_cabbage", 1), ("food_mushrooms", 1), ("food_roots", 1)],
            node_type="village",
        )
        recipes = get_available_recipes(state, _gd)
        stew = [r for r in recipes if r["id"] == "rec_food_stew"][0]
        self.assertTrue(stew["stationOk"])

    def test_workbench_only_in_village(self) -> None:
        """rec_rep_smith_kit (station=workbench) не доступен в лагере."""
        state = _make_state(
            inventory=[("junk_broken_hilt", 2), ("junk_scrap_metal", 1)],
            crafting=3,
            node_type="camp",
        )
        recipes = get_available_recipes(state, _gd)
        smith = [r for r in recipes if r["id"] == "rec_rep_smith_kit"][0]
        self.assertFalse(smith["stationOk"])

    def test_workbench_available_in_village(self) -> None:
        """rec_rep_smith_kit доступен в деревне."""
        state = _make_state(
            inventory=[("junk_broken_hilt", 2), ("junk_scrap_metal", 1)],
            crafting=3,
            node_type="village",
        )
        recipes = get_available_recipes(state, _gd)
        smith = [r for r in recipes if r["id"] == "rec_rep_smith_kit"][0]
        self.assertTrue(smith["stationOk"])

    def test_station_error_no_ap_cost(self) -> None:
        """err_station_required без списания AP и ресурсов."""
        state = _make_state(
            inventory=[("junk_broken_hilt", 2), ("junk_scrap_metal", 1)],
            crafting=3,
            node_type="camp",
        )
        initial_gold = state["player"]["gold"]
        initial_inv = copy.deepcopy(state["player"]["inventory"])
        initial_step = state["world"]["stepOfDay"]

        new_state, events = craft_recipe(state, "rec_rep_smith_kit", _gd)
        self.assertEqual(events[0]["id"], "err_station_required")
        self.assertEqual(new_state["player"]["gold"], initial_gold)
        self.assertEqual(new_state["world"]["stepOfDay"], initial_step)

    def test_in_combat_error(self) -> None:
        """Крафт в бою возвращает err_in_combat."""
        state = _make_state(
            inventory=[("food_berries", 2), ("food_roots", 1)],
            in_combat=True,
        )
        new_state, events = craft_recipe(state, "rec_pot_heal_minor", _gd)
        self.assertEqual(events[0]["id"], "err_in_combat")


# ---------------------------------------------------------------------------
# Б. Пороги навыков и ингредиенты (критерий 2)
# ---------------------------------------------------------------------------


class TestSkillAndIngredients(unittest.TestCase):
    """Пороги навыков, ингредиенты, списание ресурсов."""

    def test_skill_too_low(self) -> None:
        """rec_pot_heal_regular требует alchemy >= 4."""
        state = _make_state(
            inventory=[("pot_heal_minor", 2), ("food_mushrooms", 1)],
            alchemy=3,
        )
        new_state, events = craft_recipe(state, "rec_pot_heal_regular", _gd)
        self.assertEqual(events[0]["id"], "err_skill_too_low")
        self.assertEqual(events[0]["skill"], "alchemy")
        self.assertEqual(events[0]["required"], 4)

    def test_missing_ingredients(self) -> None:
        """Нехватка ингредиентов → err_missing_ingredients."""
        state = _make_state(
            inventory=[("food_berries", 1), ("food_roots", 1)],  # нужно 2 berries
        )
        new_state, events = craft_recipe(state, "rec_pot_heal_minor", _gd)
        self.assertEqual(events[0]["id"], "err_missing_ingredients")

    def test_successful_craft(self) -> None:
        """Успешный крафт: списывает ингредиенты, добавляет выход, тратит 1 AP."""
        state = _make_state(
            inventory=[("food_berries", 2), ("food_roots", 1)],
            step_of_day=5,
            fed_morning=True,
            fed_evening=True,
        )
        initial_step = state["world"]["stepOfDay"]
        initial_inv = copy.deepcopy(state["player"]["inventory"])

        new_state, events = craft_recipe(state, "rec_pot_heal_minor", _gd)

        crafted = [e for e in events if e["id"] == "crafted_item"][0]
        self.assertEqual(crafted["recipeId"], "rec_pot_heal_minor")
        self.assertEqual(crafted["itemId"], "pot_heal_minor")
        self.assertEqual(crafted["count"], 1)
        self.assertFalse(crafted["savedIngredients"])

        # Ингредиенты списаны
        berries = [e for e in new_state["player"]["inventory"] if e["itemId"] == "food_berries"]
        roots = [e for e in new_state["player"]["inventory"] if e["itemId"] == "food_roots"]
        self.assertEqual(len(berries), 0)
        self.assertEqual(len(roots), 0)

        # Зелье добавлено
        pot = [e for e in new_state["player"]["inventory"] if e["itemId"] == "pot_heal_minor"]
        self.assertEqual(len(pot), 1)
        self.assertGreaterEqual(pot[0]["count"], 1)

        # AP потрачено
        self.assertEqual(new_state["world"]["stepOfDay"], initial_step + 1)


# ---------------------------------------------------------------------------
# В. Перк «Экономный алхимик» (критерий 3)
# ---------------------------------------------------------------------------


class TestFrugalAlchemist(unittest.TestCase):
    """alchemy >= 6: ~25% шанс сохранения ингредиентов."""

    def test_frugal_saves_ingredients(self) -> None:
        """alchemy==6: ingredients могут сохраняться (~25%)."""
        state = _make_state(
            inventory=[("food_berries", 2), ("food_roots", 1)],
            alchemy=6,
            step_of_day=5,
            fed_morning=True,
            fed_evening=True,
        )
        # random.Random(14).random() ≈ 0.1068 <= 0.25 → SAVED!
        new_state, events = craft_recipe(
            state, "rec_pot_heal_minor", _gd, rng=random.Random(14)
        )
        crafted = [e for e in events if e["id"] == "crafted_item"][0]
        self.assertTrue(crafted["savedIngredients"])

        # Ингредиенты сохранены
        berries = [e for e in new_state["player"]["inventory"] if e["itemId"] == "food_berries"]
        roots = [e for e in new_state["player"]["inventory"] if e["itemId"] == "food_roots"]
        self.assertEqual(len(berries), 1)
        self.assertEqual(berries[0]["count"], 2)
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["count"], 1)

    def test_frugal_does_not_save_when_below_6(self) -> None:
        """alchemy < 6: ингредиенты всегда тратятся."""
        state = _make_state(
            inventory=[("food_berries", 2), ("food_roots", 1)],
            alchemy=5,
            step_of_day=5,
            fed_morning=True,
            fed_evening=True,
        )
        new_state, events = craft_recipe(
            state, "rec_pot_heal_minor", _gd, rng=random.Random(0)
        )
        crafted = [e for e in events if e["id"] == "crafted_item"][0]
        self.assertFalse(crafted["savedIngredients"])

    def test_frugal_non_alchemy_recipe(self) -> None:
        """rec_food_stew (cooking) не использует перк экономии."""
        state = _make_state(
            inventory=[("food_cabbage", 1), ("food_mushrooms", 1), ("food_roots", 1)],
            alchemy=10,
            node_type="camp",
            step_of_day=5,
            fed_morning=True,
            fed_evening=True,
        )
        new_state, events = craft_recipe(
            state, "rec_food_stew", _gd, rng=random.Random(6)
        )
        crafted = [e for e in events if e["id"] == "crafted_item"][0]
        self.assertFalse(crafted["savedIngredients"])

    def test_frugal_statistical(self) -> None:
        """Серия из 400 крафтов: ~25% с сохранением ингредиентов."""
        save_count = 0
        total = 400
        rng = random.Random(42)

        for _ in range(total):
            state = _make_state(
                inventory=[("food_berries", 2), ("food_roots", 1)],
                alchemy=6,
                step_of_day=5,
                fed_morning=True,
                fed_evening=True,
            )
            new_state, events = craft_recipe(
                state, "rec_pot_heal_minor", _gd, rng=rng
            )
            crafted = [e for e in events if e["id"] == "crafted_item"][0]
            if crafted["savedIngredients"]:
                save_count += 1

        ratio = save_count / total
        # Ожидаем ~25% ± 5%
        self.assertGreater(ratio, 0.20)
        self.assertLess(ratio, 0.30)


# ---------------------------------------------------------------------------
# Г. Полевая заточка (критерий 4)
# ---------------------------------------------------------------------------


class TestSharpenWeapon(unittest.TestCase):
    """crafting >= 3: полевая заточка оружия."""

    def test_skill_too_low(self) -> None:
        """crafting == 2: заточка недоступна."""
        state = _make_state(crafting=2)
        new_state, events = sharpen_weapon(state, _gd)
        self.assertEqual(events[0]["id"], "err_skill_too_low")

    def test_no_weapon(self) -> None:
        """Нет экипированного оружия."""
        state = _make_state(crafting=5, equipped_weapon=False)
        new_state, events = sharpen_weapon(state, _gd)
        self.assertEqual(events[0]["id"], "err_no_valid_weapon")

    def test_already_sharpened(self) -> None:
        """sharpenCharges >= 10: уже заточено."""
        state = _make_state(crafting=5, weapon_sharpened=10)
        new_state, events = sharpen_weapon(state, _gd)
        self.assertEqual(events[0]["id"], "err_already_sharpened")

    def test_sharpen_success(self) -> None:
        """Успешная заточка: sharpenCharges = 10."""
        state = _make_state(crafting=5)
        new_state, events = sharpen_weapon(state, _gd)

        sharpened = [e for e in events if e["id"] == "weapon_sharpened"][0]
        self.assertEqual(sharpened["charges"], 10)

        weapon = new_state["player"]["equipment"]["weapon"]
        self.assertEqual(weapon.get("sharpenCharges"), 10)

    def test_sharpen_in_combat(self) -> None:
        """Заточка в бою недоступна."""
        state = _make_state(crafting=5, in_combat=True)
        new_state, events = sharpen_weapon(state, _gd)
        self.assertEqual(events[0]["id"], "err_in_combat")


# ---------------------------------------------------------------------------
# Д. Укрепление на верстаке (критерий 5)
# ---------------------------------------------------------------------------


class TestReinforceEquipment(unittest.TestCase):
    """crafting == 10: укрепление на верстаке."""

    def test_not_in_village(self) -> None:
        """Укрепление вне деревни: err_station_required."""
        state = _make_state(crafting=10, node_type="camp")
        new_state, events = reinforce_equipment(state, "weapon", _gd)
        self.assertEqual(events[0]["id"], "err_station_required")

    def test_skill_too_low(self) -> None:
        """crafting < 10: err_skill_too_low."""
        state = _make_state(crafting=9, node_type="village")
        new_state, events = reinforce_equipment(state, "weapon", _gd)
        self.assertEqual(events[0]["id"], "err_skill_too_low")

    def test_empty_slot(self) -> None:
        """Пустой слот: err_empty_slot."""
        state = _make_state(crafting=10, node_type="village", equipped_weapon=False)
        new_state, events = reinforce_equipment(state, "weapon", _gd)
        self.assertEqual(events[0]["id"], "err_empty_slot")

    def test_already_reinforced(self) -> None:
        """Уже укреплённый предмет: err_already_reinforced."""
        state = _make_state(
            crafting=10, node_type="village", weapon_reinforced=True
        )
        new_state, events = reinforce_equipment(state, "weapon", _gd)
        self.assertEqual(events[0]["id"], "err_already_reinforced")

    def test_reinforce_weapon(self) -> None:
        """Укрепление оружия: reinforced=True, reinforceBonus=1."""
        state = _make_state(
            crafting=10, node_type="village", step_of_day=5,
            fed_morning=True, fed_evening=True,
        )
        new_state, events = reinforce_equipment(state, "weapon", _gd)

        reinforced = [e for e in events if e["id"] == "equipment_reinforced"][0]
        self.assertEqual(reinforced["slot"], "weapon")

        weapon = new_state["player"]["equipment"]["weapon"]
        self.assertTrue(weapon.get("reinforced"))
        self.assertEqual(weapon.get("reinforceBonus"), 1)

    def test_reinforce_armor(self) -> None:
        """Укрепление брони: reinforced=True, reinforceBonus=1."""
        state = _make_state(
            crafting=10, node_type="village", step_of_day=5,
            fed_morning=True, fed_evening=True,
        )
        new_state, events = reinforce_equipment(state, "armor", _gd)

        reinforced = [e for e in events if e["id"] == "equipment_reinforced"][0]
        self.assertEqual(reinforced["slot"], "armor")

        armor = new_state["player"]["equipment"]["armor"]
        self.assertTrue(armor.get("reinforced"))
        self.assertEqual(armor.get("reinforceBonus"), 1)

    def test_reinforce_ap_cost(self) -> None:
        """Укрепление тратит 1 AP."""
        state = _make_state(
            crafting=10, node_type="village", step_of_day=5,
            fed_morning=True, fed_evening=True,
        )
        initial_step = state["world"]["stepOfDay"]
        new_state, events = reinforce_equipment(state, "weapon", _gd)
        self.assertEqual(new_state["world"]["stepOfDay"], initial_step + 1)

    def test_reinforce_in_combat(self) -> None:
        """Укрепление в бою недоступно."""
        state = _make_state(crafting=10, node_type="village", in_combat=True)
        new_state, events = reinforce_equipment(state, "weapon", _gd)
        self.assertEqual(events[0]["id"], "err_in_combat")

    def test_reinforce_twice_rejected(self) -> None:
        """Повторное укрепление того же предмета отклоняется."""
        state = _make_state(
            crafting=10, node_type="village",
            weapon_reinforced=True, step_of_day=5,
            fed_morning=True, fed_evening=True,
        )
        new_state, events = reinforce_equipment(state, "weapon", _gd)
        self.assertEqual(events[0]["id"], "err_already_reinforced")


# ---------------------------------------------------------------------------
# Е. get_available_recipes — canCraft
# ---------------------------------------------------------------------------


class TestCanCraftFlag(unittest.TestCase):
    """Проверка флага canCraft: все условия + вне боя."""

    def test_canCraft_all_ok(self) -> None:
        """Все условия выполнены → canCraft=True."""
        state = _make_state(
            inventory=[("food_berries", 2), ("food_roots", 1)],
            alchemy=0,
            node_type="forest_edge",
        )
        recipes = get_available_recipes(state, _gd)
        minor = [r for r in recipes if r["id"] == "rec_pot_heal_minor"][0]
        self.assertTrue(minor["canCraft"])

    def test_canCraft_in_combat(self) -> None:
        """В бою canCraft=False даже при всех ресурсах."""
        state = _make_state(
            inventory=[("food_berries", 2), ("food_roots", 1)],
            alchemy=0,
            node_type="forest_edge",
            in_combat=True,
        )
        recipes = get_available_recipes(state, _gd)
        minor = [r for r in recipes if r["id"] == "rec_pot_heal_minor"][0]
        self.assertFalse(minor["canCraft"])
        # Но stationOk и ingredientsOk должны быть True
        self.assertTrue(minor["stationOk"])
        self.assertTrue(minor["ingredientsOk"])


# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    unittest.main()
