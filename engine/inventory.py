"""Модуль управления инвентарём, экипировкой, прочностью и ремонтом.

Все функции принимают state: dict и game_data: GameData, работают на копии
state (copy.deepcopy) и возвращают (new_state, events).
"""

from __future__ import annotations

import copy
import math
from typing import Any

from .data_loader import GameData


# ---------------------------------------------------------------------------
# A. Управление инвентарём
# ---------------------------------------------------------------------------


def add_item(
    state: dict,
    item_id: str,
    count: int = 1,
    durability: dict | None = None,
    game_data: GameData | None = None,
) -> tuple[dict, list[dict]]:
    """Добавляет предмет в инвентарь игрока.

    Если durability не передан (или равен максимуму), ищет существующий стак.
    Если передан износ/модификаторы — добавляет отдельной записью.
    """
    new_state = copy.deepcopy(state)
    player = new_state["player"]
    events: list[dict] = []

    # Если durability передан и не равен максимуму — отдельный слот
    if durability is not None and game_data is not None:
        item_def = game_data.get_item(item_id)
        max_dur = item_def["stats"]["durability"]["max"]
        if durability["current"] < max_dur:
            # Поношенный предмет — отдельный слот
            entry: dict[str, Any] = {
                "itemId": item_id,
                "count": 1,
                "durability": copy.deepcopy(durability),
            }
            player["inventory"].append(entry)
            events.append({"id": "item_added", "itemId": item_id, "count": 1})
            new_state["player"] = player
            return new_state, events

    # Стакаемый предмет — увеличиваем существующий стак
    for entry in player["inventory"]:
        if entry["itemId"] == item_id and "durability" not in entry:
            entry["count"] += count
            events.append({"id": "item_added", "itemId": item_id, "count": count})
            new_state["player"] = player
            return new_state, events

    # Новый стак
    player["inventory"].append({"itemId": item_id, "count": count})
    events.append({"id": "item_added", "itemId": item_id, "count": count})
    new_state["player"] = player
    return new_state, events


def remove_item(
    state: dict,
    item_id: str,
    count: int = 1,
    slot_index: int | None = None,
) -> tuple[dict, list[dict]]:
    """Списывает count единиц предмета из инвентаря.

    Если slot_index передан — списывает из конкретного слота.
    Иначе — по первому подходящему слоту.
    """
    new_state = copy.deepcopy(state)
    player = new_state["player"]
    events: list[dict] = []

    inventory = player["inventory"]

    if slot_index is not None:
        # Списываем из конкретного слота
        if slot_index < 0 or slot_index >= len(inventory):
            return state, [{"id": "err_not_enough_items", "itemId": item_id}]
        entry = inventory[slot_index]
        if entry["itemId"] != item_id:
            return state, [{"id": "err_not_enough_items", "itemId": item_id}]
        actual = min(entry["count"], count)
        entry["count"] -= actual
        if entry["count"] == 0:
            inventory.pop(slot_index)
        events.append({"id": "item_removed", "itemId": item_id, "count": actual})
    else:
        # Списываем по первому подходящему слоту
        remaining = count
        removed_items: list[tuple[int, int]] = []
        for i, entry in enumerate(inventory):
            if remaining <= 0:
                break
            if entry["itemId"] == item_id:
                actual = min(entry["count"], remaining)
                entry["count"] -= actual
                removed_items.append((i, actual))
                remaining -= actual

        if remaining > 0:
            # Недостаточно предметов — откат
            for i, actual in removed_items:
                inventory[i]["count"] += actual
            return state, [{"id": "err_not_enough_items", "itemId": item_id}]

        events.append({"id": "item_removed", "itemId": item_id, "count": count})

    # Удаляем пустые слоты
    player["inventory"] = [
        e for e in player["inventory"] if e["count"] > 0
    ]
    new_state["player"] = player
    return new_state, events


def has_item(player: dict, item_id: str, count: int = 1) -> bool:
    """Проверяет суммарное количество item_id в инвентаре."""
    total = 0
    for entry in player.get("inventory", []):
        if entry["itemId"] == item_id:
            total += entry["count"]
    return total >= count


# ---------------------------------------------------------------------------
# B. Экипировка и эффективные характеристики
# ---------------------------------------------------------------------------


def equip_item(
    state: dict,
    slot_index: int,
    game_data: GameData,
) -> tuple[dict, list[dict]]:
    """Надевает предмет из inventory в соответствующий слот equipment."""
    new_state = copy.deepcopy(state)
    player = new_state["player"]
    events: list[dict] = []
    inventory = player["inventory"]

    if slot_index < 0 or slot_index >= len(inventory):
        return state, [{"id": "err_cannot_equip"}]

    entry = inventory[slot_index]
    item_id = entry["itemId"]
    item_def = game_data.get_item(item_id)
    category = item_def.get("category")

    # Проверяем, что предмет можно экипировать
    if category not in ("weapon", "armor"):
        return state, [{"id": "err_cannot_equip"}]

    slot_key = category  # "weapon" or "armor"

    # Снимаем текущий предмет из слота (если есть)
    current_equipped = player["equipment"].get(slot_key)
    if current_equipped is not None:
        # Возвращаем в inventory как отдельный слот
        equipped_item_id = current_equipped["itemId"]
        restore_entry: dict[str, Any] = {
            "itemId": equipped_item_id,
            "count": 1,
        }
        if "durability" in current_equipped:
            restore_entry["durability"] = copy.deepcopy(current_equipped["durability"])
        if "sharpenCharges" in current_equipped:
            restore_entry["sharpenCharges"] = current_equipped["sharpenCharges"]
        if "reinforced" in current_equipped:
            restore_entry["reinforced"] = current_equipped["reinforced"]
        inventory.append(restore_entry)

    # Инициализируем durability для нового предмета, если нет
    equipped_entry: dict[str, Any] = {
        "itemId": item_id,
    }
    if "durability" in entry:
        equipped_entry["durability"] = copy.deepcopy(entry["durability"])
    else:
        # Инициализируем с max из game_data
        max_dur = item_def["stats"]["durability"]["max"]
        equipped_entry["durability"] = {"current": max_dur, "max": max_dur}

    # Копируем модификаторы из inventory-записи
    if "sharpenCharges" in entry:
        equipped_entry["sharpenCharges"] = entry["sharpenCharges"]
    if "reinforced" in entry:
        equipped_entry["reinforced"] = entry["reinforced"]

    player["equipment"][slot_key] = equipped_entry

    # Уменьшаем стак в inventory на 1
    entry["count"] -= 1
    if entry["count"] == 0:
        inventory.pop(slot_index)

    events.append({"id": "item_equipped", "itemId": item_id, "slot": slot_key})
    new_state["player"] = player
    return new_state, events


def unequip_item(
    state: dict,
    slot: str,
) -> tuple[dict, list[dict]]:
    """Снимает предмет из слота equipment в инвентарь."""
    new_state = copy.deepcopy(state)
    player = new_state["player"]
    events: list[dict] = []

    equipped = player["equipment"].get(slot)
    if equipped is None:
        return state, [{"id": "err_no_equipment", "slot": slot}]

    item_id = equipped["itemId"]
    restore_entry: dict[str, Any] = {
        "itemId": item_id,
        "count": 1,
    }
    if "durability" in equipped:
        restore_entry["durability"] = copy.deepcopy(equipped["durability"])
    if "sharpenCharges" in equipped:
        restore_entry["sharpenCharges"] = equipped["sharpenCharges"]
    if "reinforced" in equipped:
        restore_entry["reinforced"] = equipped["reinforced"]

    player["inventory"].append(restore_entry)
    player["equipment"][slot] = None

    events.append({"id": "item_unequipped", "itemId": item_id, "slot": slot})
    new_state["player"] = player
    return new_state, events


def get_effective_weapon_stats(
    player: dict,
    game_data: GameData,
) -> dict:
    """Возвращает эффективные статы оружия с учётом износа и модификаторов."""
    equipped = player["equipment"].get("weapon")

    # Безоружный удар
    if equipped is None:
        return {
            "min": 1,
            "max": 1,
            "type": "blunt",
            "skill": "melee_heavy",
            "isBroken": False,
            "isDamaged": False,
        }

    item_id = equipped["itemId"]
    item_def = game_data.get_item(item_id)
    dur = equipped.get("durability")

    if dur is None:
        max_dur = item_def["stats"]["durability"]["max"]
        current_dur = max_dur
    else:
        current_dur = dur["current"]
        max_dur = dur["max"]

    base_min = item_def["stats"]["damage"]["min"]
    base_max = item_def["stats"]["damage"]["max"]
    dmg_type = item_def["stats"]["damage"]["type"]

    is_broken = False
    is_damaged = False

    if current_dur <= 0:
        # Сломан
        is_broken = True
        min_dmg = 0
        max_dmg = 0
    elif current_dur < max_dur * 0.30:
        # Повреждён (-25%)
        is_damaged = True
        min_dmg = math.floor(base_min * 0.75)
        max_dmg = math.floor(base_max * 0.75)
    else:
        min_dmg = base_min
        max_dmg = base_max

    # Модификаторы (только если не сломан)
    if current_dur > 0:
        sharpen_charges = equipped.get("sharpenCharges", 0)
        if sharpen_charges > 0:
            min_dmg += 1
            max_dmg += 1
        reinforced = equipped.get("reinforced", False)
        if reinforced:
            min_dmg += 1
            max_dmg += 1

    return {
        "min": min_dmg,
        "max": max_dmg,
        "type": dmg_type,
        "skill": item_def["stats"]["skill"]["id"],
        "isBroken": is_broken,
        "isDamaged": is_damaged,
    }


def get_effective_armor_stats(
    player: dict,
    game_data: GameData,
) -> dict:
    """Возвращает эффективные статы брони с учётом износа и перков."""
    equipped = player["equipment"].get("armor")

    if equipped is None:
        return {"defense": 0, "evasion": 0, "isBroken": False, "isDamaged": False}

    item_id = equipped["itemId"]
    item_def = game_data.get_item(item_id)
    dur = equipped.get("durability")

    if dur is None:
        max_dur = item_def["stats"]["durability"]["max"]
        current_dur = max_dur
    else:
        current_dur = dur["current"]
        max_dur = dur["max"]

    base_def = item_def["stats"]["defense"]["value"]
    base_eva = item_def["stats"]["evasion"]["value"]
    sub_category = item_def.get("subCategory", "")

    # Перк armor_mastery 3: штраф уклонения лат снижается вдвое
    skills = player.get("skills", {})
    armor_mastery = skills.get("armor_mastery", 0)
    if sub_category == "plate" and base_eva < 0 and armor_mastery >= 3:
        base_eva = math.ceil(base_eva / 2)

    # Перк armor_mastery 6: +1 к defense любой надетой брони
    if armor_mastery >= 6:
        base_def += 1

    # Перк crafting 10: +1 к defense если reinforced
    crafting = skills.get("crafting", 0)
    reinforced = equipped.get("reinforced", False)
    if reinforced and crafting >= 10:
        base_def += 1

    is_broken = False
    is_damaged = False

    if current_dur <= 0:
        # Сломана: defense = 0, evasion: положительный = 0, отрицательный остаётся
        is_broken = True
        defense = 0
        evasion = base_eva if base_eva < 0 else 0
    elif current_dur < max_dur * 0.30:
        # Повреждена: defense = floor(total_def * 0.75)
        is_damaged = True
        defense = math.floor(base_def * 0.75)
        evasion = base_eva
    else:
        defense = base_def
        evasion = base_eva

    return {
        "defense": defense,
        "evasion": evasion,
        "isBroken": is_broken,
        "isDamaged": is_damaged,
    }


# ---------------------------------------------------------------------------
# B. Механика износа
# ---------------------------------------------------------------------------


def register_weapon_hit(
    state: dict,
) -> tuple[dict, list[dict]]:
    """Вызывается при каждом успешном ударе оружием игрока."""
    new_state = copy.deepcopy(state)
    player = new_state["player"]
    events: list[dict] = []

    equipped = player["equipment"].get("weapon")
    if equipped is None:
        return new_state, events

    dur = equipped.get("durability")
    if dur is None:
        return new_state, events

    max_dur = dur["max"]
    current_dur = dur["current"]

    # Проверяем sharpenCharges
    sharpen_charges = equipped.get("sharpenCharges", 0)
    if sharpen_charges > 0:
        equipped["sharpenCharges"] = sharpen_charges - 1
        if sharpen_charges == 1:
            events.append({"id": "weapon_sharpen_worn_out"})

    # Увеличиваем hitCounter
    hit_counter = equipped.get("hitCounter", 0) + 1
    equipped["hitCounter"] = hit_counter

    # Каждые 3 удара — теряем 1 прочность
    if hit_counter >= 3:
        equipped["hitCounter"] = 0
        dur["current"] = max(0, current_dur - 1)

        # Проверка на damage/broken
        if dur["current"] <= 0:
            events.append({"id": "equipment_broken", "slot": "weapon"})
        elif dur["current"] < max_dur * 0.30:
            events.append({"id": "equipment_damaged", "slot": "weapon"})

    player["equipment"]["weapon"] = equipped
    new_state["player"] = player
    return new_state, events


def register_armor_hit(
    state: dict,
) -> tuple[dict, list[dict]]:
    """Вызывается при каждом полученном игроком ударе."""
    new_state = copy.deepcopy(state)
    player = new_state["player"]
    events: list[dict] = []

    equipped = player.get("equipment", {}).get("armor")
    if equipped is None:
        return new_state, events

    dur = equipped.get("durability")
    if dur is None:
        return new_state, events

    max_dur = dur["max"]
    current_dur = dur["current"]

    # Увеличиваем hitCounter
    hit_counter = equipped.get("hitCounter", 0) + 1
    equipped["hitCounter"] = hit_counter

    # Перк armor_mastery 6: прочность тратится в 2 раза медленнее (каждые 6 ударов)
    skills = player.get("skills", {})
    armor_mastery = skills.get("armor_mastery", 0)
    interval = 6 if armor_mastery >= 6 else 3

    if hit_counter >= interval:
        equipped["hitCounter"] = 0
        dur["current"] = max(0, current_dur - 1)

        if dur["current"] <= 0:
            events.append({"id": "equipment_broken", "slot": "armor"})
        elif dur["current"] < max_dur * 0.30:
            events.append({"id": "equipment_damaged", "slot": "armor"})

    player["equipment"]["armor"] = equipped
    new_state["player"] = player
    return new_state, events


# ---------------------------------------------------------------------------
# Г. Ремонт
# ---------------------------------------------------------------------------


def calc_smith_repair_cost(
    player: dict,
    slot: str,
    game_data: GameData,
) -> int:
    """Рассчитывает стоимость ремонта у кузнеца."""
    equipped = player["equipment"].get(slot)
    if equipped is None:
        return 0

    dur = equipped.get("durability")
    if dur is None:
        return 0

    current = dur["current"]
    max_dur = dur["max"]

    if current >= max_dur:
        return 0

    item_def = game_data.get_item(equipped["itemId"])
    buy_price = item_def["economy"]["buyPrice"]

    raw_cost = buy_price * 0.25 * (1.0 - current / max_dur)

    # Перк crafting 6: -30% стоимости
    crafting = player.get("skills", {}).get("crafting", 0)
    if crafting >= 6:
        raw_cost *= 0.70

    return round(raw_cost)


def repair_at_smith(
    state: dict,
    slot: str,
    game_data: GameData,
) -> tuple[dict, list[dict]]:
    """Ремонт предмета у кузнеца (в деревне)."""
    new_state = copy.deepcopy(state)
    player = new_state["player"]
    events: list[dict] = []

    # Проверяем, что игрок в деревне
    map_data = new_state.get("map", {})
    current_node_id = map_data.get("currentNodeId")
    nodes = map_data.get("nodes", [])
    current_node = None
    for node in nodes:
        if node["id"] == current_node_id:
            current_node = node
            break

    if current_node is None or current_node.get("type") != "village":
        return state, [{"id": "err_not_in_village"}]

    equipped = player["equipment"].get(slot)
    if equipped is None:
        return state, [{"id": "err_no_equipment", "slot": slot}]

    dur = equipped.get("durability")
    if dur is None or dur["current"] >= dur["max"]:
        return state, [{"id": "err_already_repaired"}]

    cost = calc_smith_repair_cost(player, slot, game_data)
    if cost == 0:
        return state, [{"id": "err_already_repaired"}]

    if player["gold"] < cost:
        return state, [{"id": "err_not_enough_gold", "required": cost}]

    # Списываем золото, чиним
    player["gold"] -= cost
    dur["current"] = dur["max"]
    equipped.pop("hitCounter", None)

    events.append({"id": "smith_repaired", "slot": slot, "cost": cost})
    new_state["player"] = player
    return new_state, events


def _check_kit_compatibility(
    kit: dict,
    target_item_id: str,
    game_data: GameData,
) -> bool:
    """Проверяет совместимость ремнабора с целевым предметом."""
    kit_stats = kit.get("stats", {})
    target_categories = kit_stats.get("targetCategories")
    target_sub_categories = kit_stats.get("targetSubCategories")

    target_def = game_data.get_item(target_item_id)
    target_category = target_def.get("category")
    target_sub_category = target_def.get("subCategory", "")

    # Если targetCategories не указан — чиним всё (для совместимости)
    if target_categories is not None:
        if target_category not in target_categories:
            return False

    # Если targetSubCategories указан — проверяем подкатегорию
    if target_sub_categories is not None:
        # targetSubCategories применяется к броне (armor subCategory)
        if target_category == "armor" and target_sub_category not in target_sub_categories:
            return False

    return True


def repair_with_kit(
    state: dict,
    kit_item_id: str,
    target_slot: str,
    game_data: GameData,
) -> tuple[dict, list[dict]]:
    """Полевой ремонт ремнабором."""
    new_state = copy.deepcopy(state)
    player = new_state["player"]
    events: list[dict] = []

    # Проверяем наличие ремнабора в inventory
    kit_entry = None
    kit_slot_index = None
    for i, entry in enumerate(player["inventory"]):
        if entry["itemId"] == kit_item_id:
            kit_entry = entry
            kit_slot_index = i
            break

    if kit_entry is None:
        return state, [{"id": "err_no_repair_kit"}]

    kit_def = game_data.get_item(kit_item_id)

    # Проверяем, что предмет надет в целевой слот
    equipped = player["equipment"].get(target_slot)
    if equipped is None:
        return state, [{"id": "err_no_equipment", "slot": target_slot}]

    target_item_id = equipped["itemId"]
    dur = equipped.get("durability")
    if dur is None or dur["current"] >= dur["max"]:
        return state, [{"id": "err_already_repaired"}]

    # Проверяем совместимость
    if not _check_kit_compatibility(kit_def, target_item_id, game_data):
        return state, [{"id": "err_incompatible_repair_kit"}]

    # Объём восстановления
    restore = kit_def["stats"]["durabilityRestore"]

    # Перк crafting 6: восстанавливает в 2 раза больше
    crafting = player.get("skills", {}).get("crafting", 0)
    if crafting >= 6:
        restore *= 2

    max_dur = dur["max"]
    current = dur["current"]
    actual_restored = min(max_dur - current, restore)

    # Списываем ремнабор
    kit_entry["count"] -= 1
    if kit_entry["count"] == 0:
        player["inventory"].pop(kit_slot_index)

    # Восстанавливаем прочность
    dur["current"] = min(max_dur, current + actual_restored)

    events.append({
        "id": "field_repaired",
        "slot": target_slot,
        "restored": actual_restored,
        "apCost": 1,
    })
    new_state["player"] = player
    return new_state, events
