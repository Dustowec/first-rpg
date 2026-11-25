"""Тесты для Блока 2.2: Инвентарь, экипировка, износ и ремонт."""

import copy
import math
import os
import sys
from pathlib import Path

import pytest

# Добавляем корень проекта в sys.path для импорта
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from engine.data_loader import GameData
from engine import inventory
from engine.models import create_default_player

# Загружаем GameData из data/
_data_dir = os.path.join(_project_root, "data")
_game_data = GameData(_data_dir)


def _make_state(**overrides):
    """Создаёт тестовое состояние с player.

    При override player поля сливаются с дефолтным игроком,
    чтобы equipment и skills не терялись.
    """
    player = create_default_player()
    state = {
        "player": player,
        "meta": {},
        "map": {
            "currentNodeId": "node_00",
            "nodes": [{"id": "node_00", "type": "village", "name": "Test", "connections": []}],
        },
        "npcs": {},
        "flags": {},
        "world": {},
    }
    for key, value in overrides.items():
        if key == "player":
            # Сливаем override с дефолтным player
            for k, v in value.items():
                player[k] = v
        elif key == "map":
            state["map"] = value
        else:
            state[key] = value
    return state


# ---------------------------------------------------------------------------
# A. Управление инвентарём
# ---------------------------------------------------------------------------


class TestAddItem:
    def test_add_stackable_item(self):
        """Стакаемый предмет (еда) увеличивается в существующем стаке."""
        state = _make_state()
        new_state, events = inventory.add_item(state, "food_berries", 5, game_data=_game_data)
        assert len(events) == 1
        assert events[0]["id"] == "item_added"
        assert events[0]["count"] == 5
        # food_berries было 2, стало 7
        berries = [e for e in new_state["player"]["inventory"] if e["itemId"] == "food_berries"]
        assert len(berries) == 1
        assert berries[0]["count"] == 7

    def test_add_durable_item_as_separate_slot(self):
        """Поношенное оружие/броня добавляется отдельным слотом."""
        state = _make_state()
        durability = {"current": 10, "max": 15}
        new_state, events = inventory.add_item(
            state, "wpn_club_simple", 1, durability=durability, game_data=_game_data
        )
        assert events[0]["id"] == "item_added"
        assert events[0]["count"] == 1
        # Ищем слот с durability
        slots = [e for e in new_state["player"]["inventory"] if e["itemId"] == "wpn_club_simple"]
        # Должен быть слот с durability
        worn = [s for s in slots if "durability" in s]
        assert len(worn) == 1
        assert worn[0]["durability"]["current"] == 10
        assert worn[0]["count"] == 1


class TestRemoveItem:
    def test_remove_existing(self):
        """Успешное удаление предмета."""
        state = _make_state()
        new_state, events = inventory.remove_item(state, "food_berries", 1)
        berries = [e for e in new_state["player"]["inventory"] if e["itemId"] == "food_berries"]
        assert len(berries) == 1
        assert berries[0]["count"] == 1  # было 2, стало 1

    def test_remove_not_enough(self):
        """Недостаточно предметов — ошибка."""
        state = _make_state()
        new_state, events = inventory.remove_item(state, "food_berries", 999)
        assert events[0]["id"] == "err_not_enough_items"
        # Состояние не изменилось
        berries = [e for e in state["player"]["inventory"] if e["itemId"] == "food_berries"]
        assert berries[0]["count"] == 2

    def test_remove_empty_slot(self):
        """При count == 0 запись удаляется."""
        state = _make_state()
        new_state, events = inventory.remove_item(state, "food_berries", 2)
        assert not any(e["itemId"] == "food_berries" for e in new_state["player"]["inventory"])

    def test_has_item(self):
        """Проверка налич��я предмета."""
        state = _make_state()
        player = state["player"]
        assert inventory.has_item(player, "food_berries", 2) is True
        assert inventory.has_item(player, "food_berries", 3) is False
        assert inventory.has_item(player, "nonexistent_item") is False


# ---------------------------------------------------------------------------
# B. Экипировка
# ---------------------------------------------------------------------------


class TestEquipItem:
    def test_equip_weapon(self):
        """Надевание оружия перемещает его в equipment."""
        state = _make_state()
        # Добавляем новое оружие в инвентарь
        state["player"]["inventory"].append({"itemId": "wpn_sword_fine", "count": 1})
        new_state, events = inventory.equip_item(state, len(state["player"]["inventory"]) - 1, _game_data)
        weapon = new_state["player"]["equipment"]["weapon"]
        assert weapon["itemId"] == "wpn_sword_fine"
        assert weapon["durability"]["current"] == 55
        assert weapon["durability"]["max"] == 55
        assert events[0]["id"] == "item_equipped"

    def test_equip_preserves_durability(self):
        """Надевание предмета с износом сохраняет прочность."""
        state = _make_state()
        # Снимаем текущее оружие и добавим поношенное
        inventory.unequip_item(state, "weapon")
        state["player"]["inventory"].append({
            "itemId": "wpn_sword_fine",
            "count": 1,
            "durability": {"current": 20, "max": 55},
        })
        new_state, _ = inventory.equip_item(
            state, len(state["player"]["inventory"]) - 1, _game_data
        )
        weapon = new_state["player"]["equipment"]["weapon"]
        assert weapon["durability"]["current"] == 20
        assert weapon["durability"]["max"] == 55

    def test_equip_saves_old_to_inventory(self):
        """Снятие текущего предмета при надевании нового сохраняет его в inventory."""
        state = _make_state()
        old_weapon = state["player"]["equipment"]["weapon"]
        old_item_id = old_weapon["itemId"]
        old_dur = copy.deepcopy(old_weapon["durability"])

        # Добавляем новое оружие
        state["player"]["inventory"].append({"itemId": "wpn_sword_fine", "count": 1})
        new_state, _ = inventory.equip_item(
            state, len(state["player"]["inventory"]) - 1, _game_data
        )
        # Старое оружие должно вернуться в inventory
        old_entries = [
            e for e in new_state["player"]["inventory"]
            if e["itemId"] == old_item_id
        ]
        assert len(old_entries) == 1
        assert old_entries[0]["count"] == 1
        assert old_entries[0]["durability"]["current"] == old_dur["current"]

    def test_unequip_item(self):
        """Снятие предмета из equipment в inventory."""
        state = _make_state()
        old_dur = copy.deepcopy(state["player"]["equipment"]["weapon"]["durability"])
        new_state, events = inventory.unequip_item(state, "weapon")
        assert new_state["player"]["equipment"]["weapon"] is None
        # Предмет в inventory
        entries = [e for e in new_state["player"]["inventory"] if e["itemId"] == "wpn_club_simple"]
        assert len(entries) == 1
        assert entries[0]["durability"]["current"] == old_dur["current"]


class TestEffectiveWeaponStats:
    def test_no_weapon(self):
        """Безоружный удар: min=1, max=1, type=blunt."""
        state = _make_state()
        state, _ = inventory.unequip_item(state, "weapon")
        stats = inventory.get_effective_weapon_stats(state["player"], _game_data)
        assert stats["min"] == 1
        assert stats["max"] == 1
        assert stats["type"] == "blunt"
        assert stats["isBroken"] is False
        assert stats["isDamaged"] is False

    def test_fully_damaged_weapon(self):
        """Прочность 4/15 (< 30%): урон режется на 25% (floor)."""
        state = _make_state()
        # wpn_club_simple: min=1, max=2, durability=15
        state["player"]["equipment"]["weapon"]["durability"]["current"] = 4
        stats = inventory.get_effective_weapon_stats(state["player"], _game_data)
        assert stats["isDamaged"] is True
        assert stats["isBroken"] is False
        assert stats["min"] == math.floor(1 * 0.75)  # 0
        assert stats["max"] == math.floor(2 * 0.75)  # 1

    def test_broken_weapon(self):
        """Прочность 0/15: урон = 0."""
        state = _make_state()
        state["player"]["equipment"]["weapon"]["durability"]["current"] = 0
        stats = inventory.get_effective_weapon_stats(state["player"], _game_data)
        assert stats["isBroken"] is True
        assert stats["min"] == 0
        assert stats["max"] == 0

    def test_sharpen_bonus(self):
        """sharpenCharges > 0: +1 к min и max."""
        state = _make_state()
        state["player"]["equipment"]["weapon"]["sharpenCharges"] = 5
        stats = inventory.get_effective_weapon_stats(state["player"], _game_data)
        # club_simple: min=1, max=2 + 1 sharpen = min=2, max=3
        assert stats["min"] == 2
        assert stats["max"] == 3

    def test_reinforced_bonus(self):
        """reinforced=True: +1 к min и max."""
        state = _make_state()
        state["player"]["equipment"]["weapon"]["reinforced"] = True
        stats = inventory.get_effective_weapon_stats(state["player"], _game_data)
        assert stats["min"] == 2
        assert stats["max"] == 3

    def test_broken_no_modifiers(self):
        """Сломанное оружие не получает бонусов от модификаторов."""
        state = _make_state()
        state["player"]["equipment"]["weapon"]["durability"]["current"] = 0
        state["player"]["equipment"]["weapon"]["sharpenCharges"] = 5
        state["player"]["equipment"]["weapon"]["reinforced"] = True
        stats = inventory.get_effective_weapon_stats(state["player"], _game_data)
        assert stats["min"] == 0
        assert stats["max"] == 0


class TestEffectiveArmorStats:
    def test_no_armor(self):
        """Без брони: defense=0, evasion=0."""
        state = _make_state()
        state, _ = inventory.unequip_item(state, "armor")
        stats = inventory.get_effective_armor_stats(state["player"], _game_data)
        assert stats["defense"] == 0
        assert stats["evasion"] == 0
        assert stats["isBroken"] is False

    def test_armor_mastery_3_plate_evasion(self):
        """armor_mastery >= 3: штраф уклонения лат снижается вдвое."""
        state = _make_state()
        # arm_plate_poor: defense=5, evasion=-4
        state["player"]["equipment"]["armor"]["itemId"] = "arm_plate_poor"
        state["player"]["skills"]["armor_mastery"] = 3
        stats = inventory.get_effective_armor_stats(state["player"], _game_data)
        # ceil(-4 / 2) = -2
        assert stats["evasion"] == -2

    def test_armor_mastery_6_defense_bonus(self):
        """armor_mastery >= 6: +1 к defense."""
        # Создаём player напрямую с mastery=6
        player = create_default_player()
        player["skills"]["armor_mastery"] = 6
        stats = inventory.get_effective_armor_stats(player, _game_data)
        # cloth_poor: defense=1 + 1 (mastery 6) = 2
        assert stats["defense"] == 2

    def test_reinforced_armor_bonus(self):
        """reinforced=True + crafting >= 10: +1 к defense."""
        player = create_default_player()
        player["skills"]["armor_mastery"] = 6  # +1 defense
        player["skills"]["crafting"] = 10
        player["equipment"]["armor"]["reinforced"] = True
        stats = inventory.get_effective_armor_stats(player, _game_data)
        # cloth_poor: defense=1 + 1 (mastery 6) + 1 (reinforced) = 3
        assert stats["defense"] == 3

    def test_damaged_armor(self):
        """Прочность < 30%: defense = floor(total_def * 0.75)."""
        player = create_default_player()
        player["skills"]["armor_mastery"] = 6  # +1 defense
        player["equipment"]["armor"]["durability"]["current"] = 4  # 4/15 < 30%
        stats = inventory.get_effective_armor_stats(player, _game_data)
        # base_def=1, mastery=6 -> total=2, floor(2*0.75) = 1
        assert stats["isDamaged"] is True
        assert stats["defense"] == 1

    def test_damaged_armor_no_mastery(self):
        """Повреждённая броня без mastery: defense = floor(base_def * 0.75)."""
        player = create_default_player()
        player["equipment"]["armor"]["durability"]["current"] = 4  # 4/15 < 30%
        stats = inventory.get_effective_armor_stats(player, _game_data)
        # base_def=1, floor(1*0.75) = 0
        assert stats["isDamaged"] is True
        assert stats["defense"] == 0

    def test_broken_armor(self):
        """Сломанная броня: defense=0, evasion: положительный=0, отрицательный остаётся."""
        state = _make_state()
        state["player"]["equipment"]["armor"]["durability"]["current"] = 0
        stats = inventory.get_effective_armor_stats(state["player"], _game_data)
        assert stats["isBroken"] is True
        assert stats["defense"] == 0
        # cloth_poor evasion=0 -> 0
        assert stats["evasion"] == 0

    def test_broken_armor_negative_evasion(self):
        """Сломанная латы: отрицательный evasion остаётся."""
        state = _make_state()
        state["player"]["equipment"]["armor"]["itemId"] = "arm_plate_poor"
        state["player"]["equipment"]["armor"]["durability"]["current"] = 0
        state["player"]["skills"]["armor_mastery"] = 3
        stats = inventory.get_effective_armor_stats(state["player"], _game_data)
        assert stats["isBroken"] is True
        assert stats["defense"] == 0
        # plate evasion=-4, mastery 3 -> ceil(-4/2) = -2, remains -2
        assert stats["evasion"] == -2


# ---------------------------------------------------------------------------
# B. Механика износа
# ---------------------------------------------------------------------------


class TestWear:
    def test_weapon_hit_every_3(self):
        """Каждые 3 удара оружием снимается 1 прочность."""
        state = _make_state()
        weapon = state["player"]["equipment"]["weapon"]
        initial_dur = weapon["durability"]["current"]
        # wpn_club_simple: max=15
        assert weapon["durability"]["max"] == 15

        # 2 удара — прочность не тратится
        state, _ = inventory.register_weapon_hit(state)
        assert state["player"]["equipment"]["weapon"]["durability"]["current"] == initial_dur
        state, _ = inventory.register_weapon_hit(state)
        assert state["player"]["equipment"]["weapon"]["durability"]["current"] == initial_dur

        # 3-й удар — прочность тратится
        state, _ = inventory.register_weapon_hit(state)
        assert state["player"]["equipment"]["weapon"]["durability"]["current"] == initial_dur - 1
        assert state["player"]["equipment"]["weapon"].get("hitCounter", 0) == 0

    def test_armor_hit_interval(self):
        """Броня теряет 1 прочность каждые 3 удара (без перка)."""
        state = _make_state()
        armor = state["player"]["equipment"]["armor"]
        initial_dur = armor["durability"]["current"]

        for _ in range(2):
            state, _ = inventory.register_armor_hit(state)
            assert state["player"]["equipment"]["armor"]["durability"]["current"] == initial_dur

        state, _ = inventory.register_armor_hit(state)
        assert state["player"]["equipment"]["armor"]["durability"]["current"] == initial_dur - 1

    def test_armor_mastery_6_slower_wear(self):
        """armor_mastery == 6: броня теряет прочность каждые 6 ударов."""
        state = _make_state()
        state["player"]["skills"]["armor_mastery"] = 6
        armor = state["player"]["equipment"]["armor"]
        initial_dur = armor["durability"]["current"]

        # 5 ударов — без траты
        for _ in range(5):
            state, _ = inventory.register_armor_hit(state)
            assert state["player"]["equipment"]["armor"]["durability"]["current"] == initial_dur

        # 6-й удар — тратится
        state, _ = inventory.register_armor_hit(state)
        assert state["player"]["equipment"]["armor"]["durability"]["current"] == initial_dur - 1

    def test_weapon_sharpen_worn_out(self):
        """sharpenCharges уменьшается при ударах, событие при 0."""
        state = _make_state()
        weapon = state["player"]["equipment"]["weapon"]
        weapon["sharpenCharges"] = 3

        state, _ = inventory.register_weapon_hit(state)
        assert state["player"]["equipment"]["weapon"]["sharpenCharges"] == 2

        state, _ = inventory.register_weapon_hit(state)
        assert state["player"]["equipment"]["weapon"]["sharpenCharges"] == 1

        state, events = inventory.register_weapon_hit(state)
        assert state["player"]["equipment"]["weapon"]["sharpenCharges"] == 0
        assert any(e["id"] == "weapon_sharpen_worn_out" for e in events)

    def test_equipment_damaged_event(self):
        """Событие equipment_damaged при переходе через 30% порог."""
        state = _make_state()
        weapon = state["player"]["equipment"]["weapon"]
        # wpn_club_simple: max=15, 30% = 4.5, т.е. < 5 — damaged
        # Убьём до 4
        # Сбросим durability
        weapon["durability"]["current"] = 5
        weapon["hitCounter"] = 0
        # Следующий 3-й удар переведёт в damaged (5 -> 4 < 4.5)
        state, _ = inventory.register_weapon_hit(state)  # hit 1
        state, _ = inventory.register_weapon_hit(state)  # hit 2
        state, events = inventory.register_weapon_hit(state)  # hit 3 -> durability 4
        assert any(e["id"] == "equipment_damaged" for e in events)

    def test_equipment_broken_event(self):
        """Событие equipment_broken при достижении 0 прочности."""
        state = _make_state()
        weapon = state["player"]["equipment"]["weapon"]
        weapon["durability"]["current"] = 2
        weapon["hitCounter"] = 0

        # 1-й удар: hitCounter=1, durability=2
        state, _ = inventory.register_weapon_hit(state)
        assert state["player"]["equipment"]["weapon"]["durability"]["current"] == 2
        # 2-й удар: hitCounter=2, durability=2
        state, _ = inventory.register_weapon_hit(state)
        assert state["player"]["equipment"]["weapon"]["durability"]["current"] == 2
        # 3-й удар: hitCounter=0, durability=1
        state, _ = inventory.register_weapon_hit(state)
        assert state["player"]["equipment"]["weapon"]["durability"]["current"] == 1
        # 4-6 удары: durability=0, событие broken
        state, _ = inventory.register_weapon_hit(state)  # hit 4
        assert state["player"]["equipment"]["weapon"]["durability"]["current"] == 1
        state, _ = inventory.register_weapon_hit(state)  # hit 5
        assert state["player"]["equipment"]["weapon"]["durability"]["current"] == 1
        state, events = inventory.register_weapon_hit(state)  # hit 6 -> durability=0
        assert state["player"]["equipment"]["weapon"]["durability"]["current"] == 0
        assert any(e["id"] == "equipment_broken" for e in events)


# ---------------------------------------------------------------------------
# Г. Ремонт у кузнеца
# ---------------------------------------------------------------------------


class TestSmithRepair:
    def test_whole_item_cost_zero(self):
        """Для целого предмета стоимость ремонта = 0."""
        state = _make_state()
        cost = inventory.calc_smith_repair_cost(state["player"], "weapon", _game_data)
        assert cost == 0

    def test_whole_item_repair_denied(self):
        """Ремонт целого предмета запрещён."""
        state = _make_state()
        new_state, events = inventory.repair_at_smith(state, "weapon", _game_data)
        assert events[0]["id"] == "err_already_repaired"

    def test_destroyed_sword_cost(self):
        """wpn_sword_fine (buyPrice=120, 0/55) стоит 30 золота."""
        state = _make_state()
        # Надеваем wpn_sword_fine
        state["player"]["inventory"].append({"itemId": "wpn_sword_fine", "count": 1})
        state, _ = inventory.equip_item(state, len(state["player"]["inventory"]) - 1, _game_data)
        state["player"]["equipment"]["weapon"]["durability"]["current"] = 0
        cost = inventory.calc_smith_repair_cost(state["player"], "weapon", _game_data)
        # raw_cost = 120 * 0.25 * (1.0 - 0/55) = 120 * 0.25 * 1.0 = 30.0
        assert cost == 30

    def test_destroyed_sword_with_crafting_6(self):
        """wpn_sword_fine при crafting==6 стоит 21 золото (30 * 0.70 = 21)."""
        state = _make_state()
        # Надеваем wpn_sword_fine
        state["player"]["inventory"].append({"itemId": "wpn_sword_fine", "count": 1})
        state, _ = inventory.equip_item(state, len(state["player"]["inventory"]) - 1, _game_data)
        state["player"]["equipment"]["weapon"]["durability"]["current"] = 0
        state["player"]["skills"]["crafting"] = 6
        cost = inventory.calc_smith_repair_cost(state["player"], "weapon", _game_data)
        assert cost == 21

    def test_partial_repair_cost(self):
        """Частичный ремонт: cost = buyPrice * 0.25 * (1 - cur/max)."""
        state = _make_state()
        # wpn_club_simple: buyPrice=3, max=15
        state["player"]["equipment"]["weapon"]["durability"]["current"] = 10
        cost = inventory.calc_smith_repair_cost(state["player"], "weapon", _game_data)
        # raw_cost = 3 * 0.25 * (1 - 10/15) = 3 * 0.25 * 0.333... = 0.25
        assert cost == 0

    def test_repair_at_smith_deducts_gold(self):
        """Ремонт у кузнеца списывает золото и восстанавливает прочность."""
        state = _make_state(player={"gold": 100})
        # Надеваем wpn_sword_fine
        state["player"]["inventory"].append({"itemId": "wpn_sword_fine", "count": 1})
        state, _ = inventory.equip_item(state, len(state["player"]["inventory"]) - 1, _game_data)
        state["player"]["equipment"]["weapon"]["durability"]["current"] = 0
        state["map"]["nodes"] = [
            {"id": "node_00", "type": "village", "name": "Test", "connections": []}
        ]

        new_state, events = inventory.repair_at_smith(state, "weapon", _game_data)
        assert events[0]["id"] == "smith_repaired"
        assert events[0]["cost"] == 30
        assert new_state["player"]["gold"] == 70
        assert new_state["player"]["equipment"]["weapon"]["durability"]["current"] == 55
        assert "hitCounter" not in new_state["player"]["equipment"]["weapon"]

    def test_repair_not_enough_gold(self):
        """Недостаточно золота — ошибка."""
        state = _make_state(player={"gold": 10})
        # Надеваем wpn_sword_fine
        state["player"]["inventory"].append({"itemId": "wpn_sword_fine", "count": 1})
        state, _ = inventory.equip_item(state, len(state["player"]["inventory"]) - 1, _game_data)
        state["player"]["equipment"]["weapon"]["durability"]["current"] = 0
        new_state, events = inventory.repair_at_smith(state, "weapon", _game_data)
        assert events[0]["id"] == "err_not_enough_gold"
        assert events[0]["required"] == 30

    def test_repair_not_in_village(self):
        """Ремонт вне деревни запрещён."""
        state = _make_state()
        state["player"]["equipment"]["weapon"]["durability"]["current"] = 0
        state["map"]["nodes"] = [
            {"id": "node_00", "type": "biome", "name": "Forest", "connections": []}
        ]
        new_state, events = inventory.repair_at_smith(state, "weapon", _game_data)
        assert events[0]["id"] == "err_not_in_village"


# ---------------------------------------------------------------------------
# Г. Полевой ремонт
# ---------------------------------------------------------------------------


class TestFieldRepair:
    def test_patch_kit_compatible_armor(self):
        """rep_patch_kit чинит кожаную броню на +10."""
        state = _make_state()
        # arm_leather_poor: max=20, ставим durability=5
        state["player"]["equipment"]["armor"]["itemId"] = "arm_leather_poor"
        state["player"]["equipment"]["armor"]["durability"]["current"] = 5
        # Добавляем ремнабор
        state["player"]["inventory"].append({"itemId": "rep_patch_kit", "count": 1})

        new_state, events = inventory.repair_with_kit(
            state, "rep_patch_kit", "armor", _game_data
        )
        assert events[0]["id"] == "field_repaired"
        assert events[0]["restored"] == 10
        assert new_state["player"]["equipment"]["armor"]["durability"]["current"] == 15
        # Ремнабор списан
        assert not any(
            e["itemId"] == "rep_patch_kit" for e in new_state["player"]["inventory"]
        )

    def test_patch_kit_with_crafting_6(self):
        """rep_patch_kit при crafting==6 восстанавливает в 2 раза больше."""
        state = _make_state()
        state["player"]["equipment"]["armor"]["itemId"] = "arm_leather_poor"
        state["player"]["equipment"]["armor"]["durability"] = {"current": 5, "max": 20}
        state["player"]["skills"]["crafting"] = 6
        state["player"]["inventory"].append({"itemId": "rep_patch_kit", "count": 1})

        new_state, events = inventory.repair_with_kit(
            state, "rep_patch_kit", "armor", _game_data
        )
        # restore=10*2=20, actual=min(20-5, 20)=15
        assert events[0]["restored"] == 15
        assert new_state["player"]["equipment"]["armor"]["durability"]["current"] == 20

    def test_patch_kit_incompatible_plate(self):
        """rep_patch_kit выдаёт ошибку на латы (plate)."""
        state = _make_state()
        state["player"]["equipment"]["armor"]["itemId"] = "arm_plate_poor"
        state["player"]["equipment"]["armor"]["durability"]["current"] = 10
        state["player"]["inventory"].append({"itemId": "rep_patch_kit", "count": 1})

        new_state, events = inventory.repair_with_kit(
            state, "rep_patch_kit", "armor", _game_data
        )
        assert events[0]["id"] == "err_incompatible_repair_kit"
        # Прочность не изменилась
        assert state["player"]["equipment"]["armor"]["durability"]["current"] == 10

    def test_repair_kit_not_found(self):
        """Нет ремнабора в инвентаре — ошибка."""
        state = _make_state()
        new_state, events = inventory.repair_with_kit(
            state, "rep_patch_kit", "armor", _game_data
        )
        assert events[0]["id"] == "err_no_repair_kit"

    def test_repair_no_equipment(self):
        """Нет экипированного предмета — ошибка."""
        state = _make_state()
        state, _ = inventory.unequip_item(state, "armor")
        state["player"]["inventory"].append({"itemId": "rep_patch_kit", "count": 1})
        new_state, events = inventory.repair_with_kit(
            state, "rep_patch_kit", "armor", _game_data
        )
        assert events[0]["id"] == "err_no_equipment"

    def test_already_repaired(self):
        """Полная прочность — ремонт невозможен."""
        state = _make_state()
        state["player"]["equipment"]["armor"]["durability"]["current"] = 20  # max
        state["player"]["inventory"].append({"itemId": "rep_patch_kit", "count": 1})
        new_state, events = inventory.repair_with_kit(
            state, "rep_patch_kit", "armor", _game_data
        )
        assert events[0]["id"] == "err_already_repaired"

    def test_smith_kit_universal(self):
        """rep_smith_kit чинит любую броню и оружие."""
        state = _make_state()
        state["player"]["equipment"]["armor"]["itemId"] = "arm_plate_poor"
        state["player"]["equipment"]["armor"]["durability"] = {"current": 10, "max": 25}
        state["player"]["inventory"].append({"itemId": "rep_smith_kit", "count": 1})

        new_state, events = inventory.repair_with_kit(
            state, "rep_smith_kit", "armor", _game_data
        )
        assert events[0]["id"] == "field_repaired"
        assert events[0]["restored"] == 15

    def test_whetstone_weapon_only(self):
        """rep_whetstone чинит только оружие."""
        state = _make_state()
        state["player"]["equipment"]["armor"]["durability"]["current"] = 10  # < max
        state["player"]["inventory"].append({"itemId": "rep_whetstone", "count": 1})
        # Пытаемся чинить броню
        new_state, events = inventory.repair_with_kit(
            state, "rep_whetstone", "armor", _game_data
        )
        assert events[0]["id"] == "err_incompatible_repair_kit"

    def test_field_repair_capped_at_max(self):
        """Полевой ремонт не превышает max durability."""
        state = _make_state()
        state["player"]["equipment"]["armor"]["itemId"] = "arm_leather_poor"
        state["player"]["equipment"]["armor"]["durability"] = {"current": 18, "max": 20}
        state["player"]["inventory"].append({"itemId": "rep_patch_kit", "count": 1})

        new_state, events = inventory.repair_with_kit(
            state, "rep_patch_kit", "armor", _game_data
        )
        # restore=10, но max=20, current=18 -> actual_restored=2
        assert events[0]["restored"] == 2
        assert new_state["player"]["equipment"]["armor"]["durability"]["current"] == 20
