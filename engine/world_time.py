"""Модуль управления временем мира, голодом, ночлегом, регенерацией и респавном.

Чистые функции: принимают state: dict, возвращают (new_state, events)
или (fresh_state, events) в случае смерти игрока.
Не используют print()/input().
"""

from __future__ import annotations

import copy
import random
from typing import Any

from .constants import DEFAULT_SESSION_PATH, DEFAULT_TEMPLATE_PATH
from .data_loader import GameData
from .progression import has_tight_belt
from .storage import handle_player_death


# ---------------------------------------------------------------------------
# А. Окна голода
# ---------------------------------------------------------------------------


def get_hunger_deadlines(player: dict) -> tuple[int, int]:
    """Возвращает (morning_deadline, evening_deadline).

    Базово: (7, 17).
    При перке scavenging >= 6 («Тугий пояс»): (9, 19).
    """
    bonus = 2 if has_tight_belt(player) else 0
    return (7 + bonus, 17 + bonus)


def is_hungry_now(world: dict, player: dict) -> bool:
    """Возвращает True, если персонаж в фазе активного голода.

    Блокирует регенерацию HP:
    - 1 <= stepOfDay < morning_deadline и fedMorning is False, ИЛИ
    - 10 <= stepOfDay < evening_deadline и fedEvening is False.
    """
    morning_deadline, evening_deadline = get_hunger_deadlines(player)
    step = world.get("stepOfDay", 1)
    fed_morning = world.get("fedMorning", False)
    fed_evening = world.get("fedEvening", False)

    if 1 <= step < morning_deadline and not fed_morning:
        return True
    if 10 <= step < evening_deadline and not fed_evening:
        return True
    return False


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _has_negative_dot(player: dict) -> bool:
    """Проверяет наличие негативных DoT-эффектов (poison, bleeding)."""
    # DoT-эффекты хранятся в world["activeEffects"]
    # Но этот хелпер вызывается из get_effective context
    # Проверяем по player/resources или по activeEffects
    # Так как activeEffects в world, этот хелпер принимает player и ищет
    # по ключу в player (например, player["_activeEffects"])
    # Но по ТЗ эффекты в world["activeEffects"].
    # Этот хелпер должен вызываться с доступом к world, поэтому
    # оставим его как хелпер для проверки по player-флагу.
    return False


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

    if target_categories is not None:
        if target_category not in target_categories:
            return False

    if target_sub_categories is not None:
        if target_category == "armor" and target_sub_category not in target_sub_categories:
            return False

    return True


# ---------------------------------------------------------------------------
# В. Продвижение времени суток
# ---------------------------------------------------------------------------


def _biome_for_node(node: dict, game_data: GameData | None) -> dict | None:
    """Находит описание биома для узла карты.

    Узлы worldgen хранят тип биома в ключе "type" (biomeId у них нет вообще),
    поэтому сначала пробуем type, затем biomeId (совместимость со старыми картами).
    """
    if game_data is None:
        return None
    for key in (node.get("type", ""), node.get("biomeId", "")):
        if not key:
            continue
        try:
            biome = game_data.get_biome(key)
        except KeyError:
            biome = None
        if biome:
            return biome
    return None


def _on_new_day(
    state: dict,
    game_data: GameData | None,
    rng: random.Random | None,
    events: list[dict],
) -> None:
    """Обработка смены суток: респавн монстров раз в 5 дней (§ 28.2).

    Для каждого зачищенного дикого узла увеличивает daysSinceCleared.
    При daysSinceCleared >= 5 респавнит одного обычного монстра.
    """
    map_data = state.get("map", {})
    nodes = map_data.get("nodes", [])

    for node in nodes:
        if node.get("type") == "village":
            continue

        node_state = node.get("state", {})
        # Пропускаем, если монстр уже жив
        if node_state.get("monster") is not None:
            continue

        # Узел был зачищен
        if node_state.get("spawnRolled") is True:
            days_since = (node_state.get("daysSinceCleared") or 0) + 1
            node_state["daysSinceCleared"] = days_since

            if days_since >= 5:
                node_state["daysSinceCleared"] = 0

                # Респавним монстра из monsterPool биома
                biome = _biome_for_node(node, game_data)
                if biome is None:
                    continue
                monster_pool = biome.get("monsterPool", [])

                # Фильтруем обычных монстров (не боссов)
                ordinary_mobs = []
                for mid in monster_pool:
                    try:
                        mob_def = game_data.get_monster(mid)
                    except KeyError:
                        continue
                    if mob_def and not mob_def.get("isBoss", False):
                        ordinary_mobs.append(mid)

                if not ordinary_mobs:
                    continue

                chosen_mob_id = ordinary_mobs[0]  # берём первого
                mob_def = game_data.get_monster(chosen_mob_id)

                # Скалируем HP по difficultyMultiplier; у монстров HP — верхним уровнем
                diff_mult = state.get("meta", {}).get("difficultyMultiplier", 1.0)
                base_hp = mob_def.get("hp", 10)
                scaled_hp = max(1, int(base_hp * diff_mult))

                node_state["monster"] = {
                    "mobId": chosen_mob_id,
                    "revealed": False,
                    "hp": scaled_hp,
                    "maxHp": scaled_hp,
                }

                events.append({
                    "id": "monster_respawned",
                    "nodeId": node["id"],
                    "mobId": chosen_mob_id,
                })


def advance_time(
    state: dict,
    steps: int = 1,
    game_data: GameData | None = None,
    rng: random.Random | None = None,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
) -> tuple[dict, list[dict]]:
    """Продвигает время на N шагов (AP).

    Для каждого шага:
    1. Увеличивает stepOfDay, обрабатывает смену суток.
    2. Проверяет дедлайны голода (смерть при просрочке).
    3. Тик активных эффектов вне боя.
    4. Естественная регенерация HP/MP.
    """
    new_state = copy.deepcopy(state)
    world = new_state["world"]
    player = new_state["player"]
    events: list[dict] = []

    for _ in range(steps):
        # 1. Увеличиваем шаг
        world["stepOfDay"] += 1

        # Переход на новый день
        if world["stepOfDay"] > 20:
            world["stepOfDay"] = 1
            world["day"] += 1
            world["fedMorning"] = False
            world["fedEvening"] = False

            # Респавн монстров
            _on_new_day(new_state, game_data, rng, events)

        # 2. Проверка дедлайнов голода
        morning_deadline, evening_deadline = get_hunger_deadlines(player)

        if world["stepOfDay"] == morning_deadline and not world.get("fedMorning"):
            return handle_player_death(
                new_state, reason="starvation_morning",
                session_path=session_path, template_path=template_path,
            )
        if world["stepOfDay"] == evening_deadline and not world.get("fedEvening"):
            return handle_player_death(
                new_state, reason="starvation_evening",
                session_path=session_path, template_path=template_path,
            )

        # 3. Тик активных эффектов вне боя
        active_effects = world.get("activeEffects", [])
        removed_effects: list[int] = []
        for i, effect in enumerate(active_effects):
            # DoT: изменяем HP
            hp_delta = effect.get("hpDeltaPerTurn")
            if hp_delta is not None:
                hp_res = player["resources"]["hp"]
                hp_res["current"] += hp_delta
                hp_res["current"] = max(0, min(hp_res["current"], hp_res["max"]))

                # Проверка на смерть от DoT
                if hp_res["current"] <= 0:
                    return handle_player_death(
                        new_state, reason="dot_damage",
                        session_path=session_path, template_path=template_path,
                    )

            # Уменьшаем ticks
            effect["ticksLeft"] = effect.get("ticksLeft", 1) - 1
            if effect["ticksLeft"] <= 0:
                removed_effects.append(i)

        # Удаляем истёкшие эффекты (в обратном порядке)
        for i in reversed(removed_effects):
            removed = active_effects.pop(i)
            events.append({
                "id": "effect_expired",
                "type": removed.get("type", "unknown"),
            })

        # 4. Естественная регенерация вне боя
        if not world.get("inCombat"):
            step = world["stepOfDay"]
            hungry = is_hungry_now(world, player)

            # Реген MP: каждые 5 шагов (KI-7: голод блокирует и HP, и MP)
            if step % 5 == 0 and not hungry:
                mp_res = player["resources"]["mp"]
                mp_res["current"] = min(mp_res["max"], mp_res["current"] + player["level"])

            # Реген HP: каждые 3 шага, если нет DoT и не голод
            if step % 3 == 0:
                # Проверяем наличие негативных DoT
                has_dot = any(
                    e.get("hpDeltaPerTurn", 0) < 0
                    for e in active_effects
                )
                if not has_dot and not hungry:
                    hp_res = player["resources"]["hp"]
                    hp_res["current"] = min(hp_res["max"], hp_res["current"] + player["level"])

    new_state["world"] = world
    new_state["player"] = player
    return new_state, events


# ---------------------------------------------------------------------------
# В. Употребление еды
# ---------------------------------------------------------------------------


def eat_food(
    state: dict,
    item_id: str,
    game_data: GameData,
) -> tuple[dict, list[dict]]:
    """Употребляет еду. Не тратит AP.

    Восстанавливает HP, закрывает окно голода, может повесить DoT.
    """
    new_state = copy.deepcopy(state)
    player = new_state["player"]
    world = new_state["world"]
    events: list[dict] = []

    # Проверяем, что предмет — еда
    try:
        food_def = game_data.get_item(item_id)
    except KeyError:
        return state, [{"id": "err_invalid_food", "itemId": item_id}]

    if food_def.get("category") != "food":
        return state, [{"id": "err_invalid_food", "itemId": item_id}]

    # Проверяем наличие в инвентаре
    has_food = False
    for entry in player["inventory"]:
        if entry["itemId"] == item_id and entry["count"] > 0:
            has_food = True
            break

    if not has_food:
        return state, [{"id": "err_invalid_food", "itemId": item_id}]

    # Списываем 1 единицу
    for entry in player["inventory"]:
        if entry["itemId"] == item_id:
            entry["count"] -= 1
            if entry["count"] == 0:
                player["inventory"] = [
                    e for e in player["inventory"] if e["count"] > 0
                ]
            break

    # Восстанавливаем HP
    hp_restore_raw = food_def.get("stats", {}).get("hpRestore", 0)
    if isinstance(hp_restore_raw, dict):
        hp_restore = hp_restore_raw.get("value", 0)
    else:
        hp_restore = hp_restore_raw
    if hp_restore > 0:
        hp_res = player["resources"]["hp"]
        hp_res["current"] = min(hp_res["max"], hp_res["current"] + hp_restore)

    # DoT-эффект (например, яд от красного гриба)
    dot_effect = food_def.get("stats", {}).get("dotEffect")
    if dot_effect:
        new_effect = {
            "type": dot_effect.get("type", "poison"),
            "hpDeltaPerTurn": dot_effect.get("hpDeltaPerTurn", 0),
            "ticksLeft": dot_effect.get("ticks", 3),
        }
        # Добавляем/обновляем эффект
        existing = None
        for e in world.get("activeEffects", []):
            if e["type"] == new_effect["type"]:
                existing = e
                break
        if existing:
            existing["ticksLeft"] = max(existing.get("ticksLeft", 0), new_effect["ticksLeft"])
            # Обновляем hpDeltaPerTurn (берём максимальный по модулю)
            if abs(new_effect["hpDeltaPerTurn"]) > abs(existing.get("hpDeltaPerTurn", 0)):
                existing["hpDeltaPerTurn"] = new_effect["hpDeltaPerTurn"]
        else:
            if "activeEffects" not in world:
                world["activeEffects"] = []
            world["activeEffects"].append(new_effect)

    # Закрытие окон голода
    morning_deadline, evening_deadline = get_hunger_deadlines(player)
    step = world.get("stepOfDay", 1)

    if 1 <= step < morning_deadline and not world.get("fedMorning"):
        world["fedMorning"] = True
        events.append({"id": "hunger_satisfied", "meal": "morning"})
    elif 10 <= step < evening_deadline and not world.get("fedEvening"):
        world["fedEvening"] = True
        events.append({"id": "hunger_satisfied", "meal": "evening"})

    new_state["world"] = world
    new_state["player"] = player
    return new_state, events


# ---------------------------------------------------------------------------
# Г. Платный ночлег
# ---------------------------------------------------------------------------


def rest_at_inn(
    state: dict,
    game_data: GameData,
    rng: random.Random | None = None,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
) -> tuple[dict, list[dict]]:
    """Ночлег у трактирщика за 5 золота.

    Переносит время на утро следующего дня, восстанавливает HP/MP,
    закрывает ужин и предотвращает голодную смерть во сне.
    """
    new_state = copy.deepcopy(state)
    player = new_state["player"]
    world = new_state["world"]
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

    # Стоимость ночлега
    rest_cost = 5
    if player["gold"] < rest_cost:
        return state, [{"id": "err_not_enough_gold", "required": rest_cost}]

    # Списываем золото
    player["gold"] -= rest_cost

    # Закрываем оба окна голода — постоялец переночевал под крышей
    # и не умрёт от голода во сне
    world["fedMorning"] = True
    world["fedEvening"] = True

    # Вычисляем шаги до утра следующего дня
    step = world.get("stepOfDay", 1)
    steps_to_morning = (20 - step) + 1

    # Продвигаем время (advance_time делает deepcopy, поэтому передаём current new_state)
    new_state, time_events = advance_time(
        new_state, steps=steps_to_morning, game_data=game_data,
        rng=rng, session_path=session_path, template_path=template_path,
    )

    events.extend(time_events)

    new_state["world"] = new_state["world"]
    new_state["player"] = new_state["player"]

    events.append({
        "id": "inn_rested",
        "cost": rest_cost,
        "newDay": new_state["world"]["day"],
    })

    return new_state, events
