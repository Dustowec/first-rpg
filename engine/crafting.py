"""Модуль ремесла: алхимия, кулинария, кузнечное дело, заточка, укрепление.

Реализует §14, §15, §16.2, §17 и §22.3 спеки.
Все функции — чистые: принимают state: dict, возвращают (new_state, events).
Не используют print()/input()/global random.
"""

from __future__ import annotations

import copy
import random
from typing import Any

from .constants import DEFAULT_SESSION_PATH, DEFAULT_TEMPLATE_PATH
from .data_loader import GameData
from .inventory import add_item, remove_item


# ---------------------------------------------------------------------------
# А. Доступные станции
# ---------------------------------------------------------------------------


def _get_available_stations(state: dict) -> set[str]:
    """Возвращает набор доступных рабочих станций в текущем узле.

    Правила:
      - "any" — всегда доступно вне боя.
      - "campfire" — доступно в узлах type in ("village", "camp").
      - "workbench" — доступно только в узлах type == "village".
    """
    stations: set[str] = set()

    world = state.get("world", {})
    if not world.get("inCombat", False):
        stations.add("any")

    map_data = state.get("map", {})
    current_node_id = map_data.get("currentNodeId")
    nodes = map_data.get("nodes", [])

    current_node: dict[str, Any] | None = None
    for node in nodes:
        if node["id"] == current_node_id:
            current_node = node
            break

    if current_node is None:
        return stations

    node_type = current_node.get("type", "")

    if node_type in ("village", "camp"):
        stations.add("campfire")
    if node_type == "village":
        stations.add("workbench")

    return stations


# ---------------------------------------------------------------------------
# Б. Получение списка рецептов (A)
# ---------------------------------------------------------------------------


def get_available_recipes(
    state: dict,
    game_data: GameData,
) -> list[dict]:
    """Возвращает все рецепты с вычисленными флагами доступности.

    Каждый элемент возвращаемого списка:
      - id: ID рецепта
      - stationOk: bool — станция доступна в текущей локации
      - skillOk: bool — навык игрока достаточен
      - ingredientsOk: bool — ингредиентов хватает
      - canCraft: bool — все условия выполнены и игрок вне боя
    """
    player = state.get("player", {})
    inventory = player.get("inventory", [])
    skills = player.get("skills", {})
    in_combat = state.get("world", {}).get("inCombat", False)
    available_stations = _get_available_stations(state)

    result: list[dict] = []

    for recipe_id, recipe in game_data.recipes.items():
        # --- stationOk ---
        station = recipe.get("station", "any")
        station_ok = station == "any" or station in available_stations

        # --- skillOk ---
        required_skill = recipe.get("requiredSkill", {})
        req_skill_id = required_skill.get("id", "")
        req_skill_level = required_skill.get("level", 0)
        skill_ok = skills.get(req_skill_id, 0) >= req_skill_level

        # --- ingredientsOk ---
        ingredients = recipe.get("ingredients", [])
        ingredients_ok = True
        for ing in ingredients:
            item_id = ing["itemId"]
            count_needed = ing["count"]
            total = 0
            for entry in inventory:
                if entry["itemId"] == item_id:
                    total += entry["count"]
            if total < count_needed:
                ingredients_ok = False
                break

        # --- canCraft ---
        can_craft = not in_combat and station_ok and skill_ok and ingredients_ok

        result.append({
            "id": recipe_id,
            "stationOk": station_ok,
            "skillOk": skill_ok,
            "ingredientsOk": ingredients_ok,
            "canCraft": can_craft,
        })

    return result


# ---------------------------------------------------------------------------
# В. Создание предмета по рецепту (B)
# ---------------------------------------------------------------------------


def craft_recipe(
    state: dict,
    recipe_id: str,
    game_data: GameData,
    rng: random.Random | None = None,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
) -> tuple[dict, list[dict]]:
    """Создаёт предмет по рецепту (§14, §15, §17, §22.3).

    Возвращает (new_state, events).
    """
    from .world_time import advance_time

    new_state = copy.deepcopy(state)
    player = new_state["player"]
    world = new_state["world"]
    events: list[dict] = []

    # 1.1 Вне боя
    if world.get("inCombat", False):
        return new_state, [{"id": "err_in_combat"}]

    # 1.2 Поиск рецепта
    recipe = game_data.recipes.get(recipe_id)
    if recipe is None:
        return new_state, [{"id": "err_unknown_recipe"}]

    # 1.3 Рабочее место
    station = recipe.get("station", "any")
    if station != "any" and station not in _get_available_stations(new_state):
        return new_state, [
            {"id": "err_station_required", "requiredStation": station}
        ]

    # 1.4 Навык
    required_skill = recipe.get("requiredSkill", {})
    req_skill_id = required_skill.get("id", "")
    req_skill_level = required_skill.get("level", 0)
    if player["skills"].get(req_skill_id, 0) < req_skill_level:
        return new_state, [
            {
                "id": "err_skill_too_low",
                "skill": req_skill_id,
                "required": req_skill_level,
            }
        ]

    # 1.5 Ингредиенты
    ingredients = recipe.get("ingredients", [])
    inventory = player["inventory"]
    for ing in ingredients:
        item_id = ing["itemId"]
        count_needed = ing["count"]
        total = 0
        for entry in inventory:
            if entry["itemId"] == item_id:
                total += entry["count"]
        if total < count_needed:
            return new_state, [{"id": "err_missing_ingredients"}]

    # 2. Расход ингредиентов и перк «Экономный алхимик» (§22.3)
    sub_category = recipe.get("subCategory", "")
    is_frugal = (
        sub_category == "alchemy"
        and player["skills"].get("alchemy", 0) >= 6
    )

    saved_ingredients = False
    if is_frugal and rng is not None and rng.random() <= 0.25:
        saved_ingredients = True
    else:
        # Списываем ингредиенты через remove_item
        for ing in ingredients:
            new_state, _ = remove_item(new_state, ing["itemId"], ing["count"])
        player = new_state["player"]

    # 3. Выдача результата
    output = recipe.get("output", {})
    out_item_id = output.get("itemId", "")
    out_count = output.get("count", 1)
    new_state, _ = add_item(new_state, out_item_id, out_count, game_data=game_data)

    # 4. Трата 1 AP
    new_state, time_events = advance_time(
        new_state,
        steps=1,
        game_data=game_data,
        rng=rng,
        session_path=session_path,
        template_path=template_path,
    )
    events.extend(time_events)

    # Проверка на смерть от голода/DoT
    if new_state.get("flags", {}).get("isDead", False):
        return new_state, events

    events.append({
        "id": "crafted_item",
        "recipeId": recipe_id,
        "itemId": out_item_id,
        "count": out_count,
        "savedIngredients": saved_ingredients,
    })

    return new_state, events


# ---------------------------------------------------------------------------
# Г. Бесплатная полевая заточка оружия (C)
# ---------------------------------------------------------------------------


def sharpen_weapon(
    state: dict,
    game_data: GameData,
) -> tuple[dict, list[dict]]:
    """Полевая заточка оружия (§22.3: crafting >= 3, бесплатно).

    Возвращает (new_state, events).
    """
    new_state = copy.deepcopy(state)
    player = new_state["player"]
    world = new_state["world"]
    events: list[dict] = []

    # 1. Вне боя
    if world.get("inCombat", False):
        return new_state, [{"id": "err_in_combat"}]

    # 2. Навык crafting >= 3
    if player["skills"].get("crafting", 0) < 3:
        return new_state, [
            {
                "id": "err_skill_too_low",
                "skill": "crafting",
                "required": 3,
            }
        ]

    # 3. Экипированное оружие
    equipped = player["equipment"].get("weapon")
    if equipped is None:
        return new_state, [{"id": "err_no_valid_weapon"}]

    # Проверяем, что не сломано
    dur = equipped.get("durability")
    if dur is None or dur.get("current", 0) <= 0:
        return new_state, [{"id": "err_no_valid_weapon"}]

    # 4. Не заточено ли уже на максимум
    if equipped.get("sharpenCharges", 0) >= 10:
        return new_state, [{"id": "err_already_sharpened"}]

    # 5. Устанавливаем sharpenCharges = 10
    equipped["sharpenCharges"] = 10
    player["equipment"]["weapon"] = equipped

    events.append({
        "id": "weapon_sharpened",
        "itemId": equipped["itemId"],
        "charges": 10,
    })

    return new_state, events


# ---------------------------------------------------------------------------
# Д. Укрепление снаряжения на верстаке (D)
# ---------------------------------------------------------------------------


def reinforce_equipment(
    state: dict,
    slot: str,
    game_data: GameData,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
) -> tuple[dict, list[dict]]:
    """Укрепление снаряжения на верстаке (§22.3: crafting == 10).

    Возвращает (new_state, events).
    """
    from .world_time import advance_time

    new_state = copy.deepcopy(state)
    player = new_state["player"]
    world = new_state["world"]
    events: list[dict] = []

    # 1. Вне боя
    if world.get("inCombat", False):
        return new_state, [{"id": "err_in_combat"}]

    # 2. Наличие верстака
    if "workbench" not in _get_available_stations(new_state):
        return new_state, [
            {"id": "err_station_required", "requiredStation": "workbench"}
        ]

    # 3. Навык crafting >= 10
    if player["skills"].get("crafting", 0) < 10:
        return new_state, [
            {
                "id": "err_skill_too_low",
                "skill": "crafting",
                "required": 10,
            }
        ]

    # 4. Корректность слота и наличие предмета
    if slot not in ("weapon", "armor"):
        return new_state, [{"id": "err_empty_slot"}]

    item_inst = player["equipment"].get(slot)
    if item_inst is None:
        return new_state, [{"id": "err_empty_slot"}]

    # 5. Не укреплён ли уже
    if item_inst.get("reinforced", False):
        return new_state, [{"id": "err_already_reinforced"}]

    # 6. Применяем бонус
    item_inst["reinforced"] = True
    item_inst["reinforceBonus"] = 1
    player["equipment"][slot] = item_inst

    # 7. Трата 1 AP
    new_state["player"] = player
    new_state, time_events = advance_time(
        new_state,
        steps=1,
        game_data=game_data,
        session_path=session_path,
        template_path=template_path,
    )
    events.extend(time_events)

    # Проверка на смерть от голода/DoT
    if new_state.get("flags", {}).get("isDead", False):
        return new_state, events

    events.append({
        "id": "equipment_reinforced",
        "slot": slot,
        "itemId": item_inst["itemId"],
    })

    return new_state, events
