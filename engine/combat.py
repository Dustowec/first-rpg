"""Боевой автомат: инициация, раунды, ИИ монстров, побег, награды, логова.

Чистые функции: state + action -> (new_state, events).
Без print()/input().
"""

from __future__ import annotations

import copy
import random
from typing import Any

from engine.combat_math import (
    determine_first_attacker,
    roll_monster_attack,
    roll_player_weapon_attack,
    scale_monster_stats,
)


def _prepare_monster_for_scaling(monster_data: dict) -> dict:
    """Преобразует JSON монстра в формат, ожидаемый scale_monster_stats."""
    return {
        "resources": {
            "hp": {"max": monster_data.get("hp", 10)},
            "defense": monster_data.get("def", 0),
            "accuracy": monster_data.get("acc", 50),
            "evasion": monster_data.get("eva", 0),
        },
        "damage": {
            "min": monster_data.get("dmg", {}).get("min", 1),
            "max": monster_data.get("dmg", {}).get("max", 2),
            "type": monster_data.get("dmg", {}).get("type", "physical"),
        },
    }


def _get_player_attr(player: dict, attr: str) -> int:
    """Извлекает атрибут игрока из player["attributes"] или player["resources"]["attributes"]."""
    if "attributes" in player and "agility" in player["attributes"]:
        return player["attributes"].get(attr, 1)
    return player.get("resources", {}).get("attributes", {}).get(attr, 1)
from engine.consumables import process_weapon_coating_on_hit, tick_combat_round_effects, use_consumable
from engine.constants import DEFAULT_SESSION_PATH, DEFAULT_TEMPLATE_PATH
from engine.inventory import add_item, register_armor_hit, register_weapon_hit
from engine.magic import (
    apply_on_monster_killed_perks,
    apply_on_weapon_hit_perks,
    can_use_crushing_strike,
    cast_spell,
    check_second_wind_trigger,
    clear_combat_flags,
    use_crushing_strike,
)
from engine.progression import grant_xp
from engine.storage import handle_player_death
from engine.world_time import advance_time


# ---------------------------------------------------------------------------
# A. Старт боя
# ---------------------------------------------------------------------------


def start_combat(
    state: dict,
    game_data: Any,
    is_ambush: bool = False,
    rng: random.Random | None = None,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
) -> tuple[dict, list[dict]]:
    """Инициирует бой.

    Args:
        state: Глубокая копия состояния.
        game_data: GameData.
        is_ambush: True для засады (0 AP).
        rng: Генератор случайных чисел.
        session_path: Путь сессии.
        template_path: Путь шаблона.

    Returns:
        (new_state, events).
    """
    if rng is None:
        rng = random.Random()

    state = copy.deepcopy(state)
    world = state["world"]
    player = state["player"]
    map_data = state["map"]
    current_node = _get_current_node(map_data)

    # Проверка: не в бою уже
    if world.get("inCombat"):
        return state, [{"id": "err_already_in_combat"}]

    # Проверка: есть ли монстр
    node_monster = current_node["state"].get("monster")
    if node_monster is None:
        return state, [{"id": "err_no_monster"}]

    mob_id = node_monster["mobId"]
    monster_data = game_data.get_monster(mob_id)
    if monster_data is None:
        return state, [{"id": "err_monster_not_found", "mobId": mob_id}]

    # Проверка стелса
    if not is_ambush and not node_monster.get("revealed", False):
        return state, [{"id": "err_monster_not_revealed"}]

    # Трата AP для обычного боя
    if not is_ambush:
        state, events = advance_time(state, steps=1, game_data=game_data, rng=rng, session_path=session_path, template_path=template_path)
        # Если игрок умер от голода при трате AP — возвращаем результат
        if state.get("flags", {}).get("isDead"):
            return state, events
        # Обновляем ссылки на обновлённое состояние
        world = state["world"]
        player = state["player"]
        map_data = state["map"]
        current_node = _get_current_node(map_data)
        current_node["state"]["monster"]["revealed"] = True
    else:
        # Засада: 0 AP, принудительно revealed
        current_node["state"]["monster"]["revealed"] = True

    # Масштабирование монстра
    difficulty_mult = state["meta"].get("difficultyMultiplier", 1.0)
    scaled = scale_monster_stats(_prepare_monster_for_scaling(monster_data), difficulty_mult)

    # Инициализация боя
    world["inCombat"] = True
    world["combatFlags"] = {"crushingCooldown": 0, "secondWindUsed": False}

    # Совмещение атрибутов и навыков для combat_math
    if "attributes" in player:
        if "resources" not in player:
            player["resources"] = {}
        if "attributes" not in player["resources"]:
            player["resources"]["attributes"] = player["attributes"]
        if "skills" in player and "skills" not in player["resources"]:
            player["resources"]["skills"] = player["skills"]

    # Логово: очередь врагов
    lair_queue = current_node["state"].get("lairQueue")
    queue_index = 0
    if lair_queue:
        queue_index = current_node["state"].get("lairQueueIndex", 0)
        if queue_index >= len(lair_queue):
            return state, [{"id": "err_lair_queue_empty"}]
        queue_mob_id = lair_queue[queue_index]["mobId"]
        queue_monster_data = game_data.get_monster(queue_mob_id)
        queue_scaled = scale_monster_stats(_prepare_monster_for_scaling(queue_monster_data), difficulty_mult)
        current_node["state"]["monster"] = {
            "mobId": queue_mob_id,
            "revealed": True,
            "hp": queue_scaled["hp"]["current"],
            "maxHp": queue_scaled["hp"]["max"],
        }
        scaled = queue_scaled
    else:
        current_node["state"]["monster"] = {
            "mobId": mob_id,
            "revealed": True,
            "hp": scaled["hp"]["current"],
            "maxHp": scaled["hp"]["max"],
        }

    affinities = monster_data.get("affinities", {})

    world["activeCombat"] = {
        "nodeId": map_data["currentNodeId"],
        "isAmbush": is_ambush,
        "round": 1,
        "queueIndex": queue_index,
        "monster": {
            "mobId": scaled.get("mobId", mob_id),
            "hp": scaled["hp"]["current"],
            "maxHp": scaled["hp"]["max"],
            "activeEffects": [],
        },
        "affinities": affinities,
    }

    # Определение первого хода
    first_attacker = determine_first_attacker(player, scaled, is_ambush, rng)

    events = [{"id": "combat_started", "mobId": mob_id, "isAmbush": is_ambush, "firstAttacker": first_attacker}]

    # Если монстр первый — его ход
    if first_attacker == "monster":
        state, monster_events = _execute_monster_turn(state, game_data, rng, session_path, template_path)
        events.extend(monster_events)
        if player["resources"]["hp"]["current"] <= 0:
            state, death_events = handle_player_death(state, reason="combat", session_path=session_path, template_path=template_path)
            events.extend(death_events)
            return state, events

    return state, events


# ---------------------------------------------------------------------------
# Б. Ход игрока
# ---------------------------------------------------------------------------


def combat_step(
    state: dict,
    command: dict,
    game_data: Any,
    rng: random.Random | None = None,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
) -> tuple[dict, list[dict]]:
    """Выполняет ход игрока.

    Args:
        state: Состояние.
        command: {"type": "attack"|"crushing_strike"|"cast"|"use_item"|"flee", ...}.
        game_data: GameData.
        rng: RNG.
        session_path: Путь сессии.
        template_path: Путь шаблона.

    Returns:
        (new_state, events).
    """
    if rng is None:
        rng = random.Random()

    state = copy.deepcopy(state)
    world = state["world"]
    player = state["player"]
    active_combat = world.get("activeCombat")

    if not active_combat:
        return state, [{"id": "err_not_in_combat"}]

    combat_mob = active_combat["monster"]
    affinities = active_combat.get("affinities", {})

    command_type = command.get("type")

    # ------------------------------------------------------------------
    # Flee
    # ------------------------------------------------------------------
    if command_type == "flee":
        return _handle_flee(state, game_data, rng, session_path, template_path)

    # ------------------------------------------------------------------
    # Attack / Crushing Strike
    # ------------------------------------------------------------------
    if command_type in ("attack", "crushing_strike"):
        damage_multiplier_bonus = 1.0
        min_hit_override = None

        if command_type == "crushing_strike":
            if not can_use_crushing_strike(state):
                return state, [{"id": "err_skill_on_cooldown", "skill": "crushing_strike"}]
            state, _ = use_crushing_strike(state)
            damage_multiplier_bonus = 1.5
            min_hit_override = 70

        return _handle_player_attack(
            state, affinities, damage_multiplier_bonus, min_hit_override, game_data, rng, session_path, template_path
        )

    # ------------------------------------------------------------------
    # Cast spell
    # ------------------------------------------------------------------
    if command_type == "cast":
        spell_id = command.get("spellId")
        if not spell_id:
            return state, [{"id": "err_no_spell_id"}]

        state, events = cast_spell(
            state,
            spell_id,
            game_data,
            target_monster=combat_mob,
            target_affinities=affinities,
            rng=rng,
        )

        # Ошибка — не тратим ход
        if any(e["id"].startswith("err_") for e in events):
            return state, events

        # Проверка смерти монстра
        if combat_mob["hp"] <= 0:
            return _on_monster_defeated(state, game_data, rng, session_path, template_path)

        # Ход монстра
        return _execute_monster_turn(state, game_data, rng, session_path, template_path)

    # ------------------------------------------------------------------
    # Use item
    # ------------------------------------------------------------------
    if command_type == "use_item":
        item_id = command.get("itemId")
        if not item_id:
            return state, [{"id": "err_no_item_id"}]

        state, events = use_consumable(
            state,
            item_id,
            game_data,
            target_monster=combat_mob,
            target_affinities=affinities,
            rng=rng,
        )

        # Ошибка — не тратим ход
        if any(e["id"].startswith("err_") for e in events):
            return state, events

        # Проверка смерти монстра
        if combat_mob["hp"] <= 0:
            return _on_monster_defeated(state, game_data, rng, session_path, template_path)

        # Ход монстра
        return _execute_monster_turn(state, game_data, rng, session_path, template_path)

    return state, [{"id": "err_unknown_command", "type": command_type}]


# ---------------------------------------------------------------------------
# В. Ход монстра
# ---------------------------------------------------------------------------


def _execute_monster_turn(
    state: dict,
    game_data: Any,
    rng: random.Random | None = None,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
) -> tuple[dict, list[dict]]:
    """Ход монстра: реген, атака, onHitDot, second_wind."""
    if rng is None:
        rng = random.Random()

    state = copy.deepcopy(state)
    world = state["world"]
    player = state["player"]
    active_combat = world["activeCombat"]
    combat_mob = active_combat["monster"]
    round_num = active_combat["round"]

    # Получаем данные монстра для specialTraits
    mob_id = combat_mob["mobId"]
    monster_data = game_data.get_monster(mob_id)
    special_traits = monster_data.get("specialTraits", {}) if monster_data else {}

    # Регенерация
    if "regenHp" in special_traits:
        regen_hp = special_traits["regenHp"]
        regen_interval = special_traits.get("regenIntervalRounds", 1)
        if round_num % regen_interval == 0:
            max_hp = combat_mob["maxHp"]
            combat_mob["hp"] = min(max_hp, combat_mob["hp"] + regen_hp)

    # Атака монстра
    player_evasion = 0  # будет рассчитана в roll_monster_attack
    monster_debuffs = combat_mob.get("activeEffects", [])
    ignore_armor_ratio = special_traits.get("ignoreArmorRatio", 0.0)

    result = roll_monster_attack(
        {
            "min": monster_data["dmg"]["min"] if monster_data else 3,
            "max": monster_data["dmg"]["max"] if monster_data else 6,
            "accuracy": monster_data["acc"] if monster_data else 50,
            "damageType": monster_data["dmg"]["type"] if monster_data else "physical",
        },
        player,
        game_data,
        rng,
        active_effects=world.get("activeEffects"),
        monster_debuffs=monster_debuffs,
        ignore_armor_ratio=ignore_armor_ratio,
    )

    events = []

    if result["hit"]:
        # Урон игроку
        player["resources"]["hp"]["current"] = max(0, player["resources"]["hp"]["current"] - result["damage"])

        # Износ брони
        state, armor_events = register_armor_hit(state)
        events.extend(armor_events)

        # On-hit DOT (например, отравляющий укус паука)
        if "onHitDot" in special_traits:
            on_hit_dot = special_traits["onHitDot"]
            chance = on_hit_dot.get("chance", 0.25)
            if rng.random() <= chance:
                dot = on_hit_dot
                world.setdefault("activeEffects", []).append({
                    "id": "onHitDot",
                    "type": dot.get("type", "poison"),
                    "hpDeltaPerTurn": dot.get("hpDeltaPerTurn", -1),
                    "ticksLeft": dot.get("ticks", 3),
                })
                events.append({"id": "monster_onhit_dot", "dotType": dot.get("type", "poison")})

        # Проверка second wind
        wind_events = check_second_wind_trigger(state)
        events.extend(wind_events)

    # Проверка смерти игрока
    if player["resources"]["hp"]["current"] <= 0:
        state, death_events = handle_player_death(state, reason="combat", session_path=session_path, template_path=template_path)
        events.extend(death_events)
        return state, events

    return state, events


# ---------------------------------------------------------------------------
# Г. Завершение раунда
# ---------------------------------------------------------------------------


def _end_round(state: dict, combat_mob: dict) -> dict:
    """Завершение раунда: тики эффектов, кулдауны, проверка смерти от DoT."""
    state = copy.deepcopy(state)
    world = state["world"]
    active_combat = world["activeCombat"]

    # Тики эффектов
    state, _ = tick_combat_round_effects(state, combat_mob)

    # Уменьшение кулдауна crushing
    combat_flags = world.get("combatFlags", {})
    combat_flags["crushingCooldown"] = max(0, combat_flags.get("crushingCooldown", 0) - 1)

    # Проверка смерти монстра от DoT
    if combat_mob["hp"] <= 0:
        # Победa обработается в следующем шаге
        return state

    # Проверка смерти игрока от DoT
    player = state["player"]
    if player["resources"]["hp"]["current"] <= 0:
        # Смерть обработается вызывающей стороной
        pass

    # Увеличение раунда
    active_combat["round"] += 1

    return state


# ---------------------------------------------------------------------------
# Д. Победа и награды
# ---------------------------------------------------------------------------


def _on_monster_defeated(
    state: dict,
    game_data: Any,
    rng: random.Random | None = None,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
) -> tuple[dict, list[dict]]:
    """Обработка победы: перки, награды, логово, очистка."""
    if rng is None:
        rng = random.Random()

    state = copy.deepcopy(state)
    world = state["world"]
    player = state["player"]
    map_data = state["map"]
    active_combat = world["activeCombat"]
    combat_mob = active_combat["monster"]
    current_node = _get_current_node(map_data)

    events = []

    # Перк «Жатва душ»
    perk_events = apply_on_monster_killed_perks(state, combat_mob)
    events.extend(perk_events)

    # Увеличение killsTotal
    world["killsTotal"] += 1

    # Получаем данные монстра для наград
    mob_id = combat_mob["mobId"]
    monster_data = game_data.get_monster(mob_id)

    if monster_data:
        rewards = monster_data.get("rewards", monster_data)

        # XP
        xp_amount = rewards.get("xp", 0)
        state, xp_events = grant_xp(state, xp_amount)
        events.extend(xp_events)
        # Обновляем ссылки после deepcopy в grant_xp
        world = state["world"]
        player = state["player"]
        map_data = state["map"]
        active_combat = world["activeCombat"]
        combat_mob = active_combat["monster"]
        current_node = _get_current_node(map_data)

        # Золото
        gold_range = rewards.get("gold", {})
        gold_min = gold_range.get("min", 0)
        gold_max = gold_range.get("max", 0)
        gold_gain = rng.randint(gold_min, gold_max)
        state["player"]["gold"] += gold_gain
        events.append({"id": "gold_gained", "amount": gold_gain})

        # Лут
        loot_table = rewards.get("lootTable", [])
        for entry in loot_table:
            if rng.random() <= entry.get("chance", 0):
                item_id = entry["itemId"]
                count = rng.randint(entry.get("min", 1), entry.get("max", 1))
                state, loot_events = add_item(state, item_id, count, game_data=game_data)
                events.extend(loot_events)
                # Обновляем ссылки после deepcopy в add_item
                world = state["world"]
                player = state["player"]
                map_data = state["map"]
                active_combat = world["activeCombat"]
                combat_mob = active_combat["monster"]
                current_node = _get_current_node(map_data)

    # Логово: переход к следующему врагу
    lair_queue = current_node["state"].get("lairQueue")
    queue_index = active_combat.get("queueIndex", 0)

    if lair_queue and queue_index + 1 < len(lair_queue):
        # Следующий враг в логове
        next_queue_index = queue_index + 1
        next_mob_id = lair_queue[next_queue_index]["mobId"]
        next_monster_data = game_data.get_monster(next_mob_id)
        difficulty_mult = state["meta"].get("difficultyMultiplier", 1.0)
        next_scaled = scale_monster_stats(_prepare_monster_for_scaling(next_monster_data), difficulty_mult)

        current_node["state"]["monster"] = {
            "mobId": next_mob_id,
            "revealed": True,
            "hp": next_scaled["hp"]["current"],
            "maxHp": next_scaled["hp"]["max"],
        }
        current_node["state"]["lairQueueIndex"] = next_queue_index

        affinities = next_monster_data.get("affinities", {})
        active_combat["monster"] = {
            "mobId": next_mob_id,
            "hp": next_scaled["hp"]["current"],
            "maxHp": next_scaled["hp"]["max"],
            "activeEffects": [],
        }
        active_combat["affinities"] = affinities
        active_combat["round"] = 1
        active_combat["queueIndex"] = next_queue_index

        events.append({"id": "lair_next_monster", "mobId": next_mob_id})
    else:
        # Все враги победлены
        if lair_queue:
            current_node["state"]["lairQueueIndex"] = len(lair_queue)
        current_node["state"]["monster"] = None
        current_node["state"]["daysSinceCleared"] = 0
        world["inCombat"] = False
        world["activeCombat"] = None
        world["combatFlags"] = {}
        events.append({"id": "combat_victory"})

    return state, events


# ---------------------------------------------------------------------------
# Побег
# ---------------------------------------------------------------------------


def _handle_flee(
    state: dict,
    game_data: Any,
    rng: random.Random,
    session_path: str,
    template_path: str,
) -> tuple[dict, list[dict]]:
    """Обработка отступления."""
    state = copy.deepcopy(state)
    world = state["world"]
    active_combat = world["activeCombat"]
    combat_mob = active_combat["monster"]
    current_node = _get_current_node(state["map"])

    flee_roll = rng.randint(0, 100)

    if flee_roll <= 50:
        # Успех: сохраняем HP монстра
        current_node["state"]["monster"]["hp"] = combat_mob["hp"]
        current_node["state"]["monster"]["revealed"] = True

        world["inCombat"] = False
        world["activeCombat"] = None
        world["combatFlags"] = {}

        return state, [{"id": "combat_fled_success"}]
    else:
        # Провал: ход монстра
        state, monster_events = _execute_monster_turn(state, game_data, rng, session_path, template_path)
        # Добавляем событие провала побега
        monster_events.insert(0, {"id": "combat_fled_failed"})
        return state, monster_events


# ---------------------------------------------------------------------------
# Атака игрока
# ---------------------------------------------------------------------------


def _handle_player_attack(
    state: dict,
    affinities: dict,
    damage_multiplier_bonus: float,
    min_hit_override: int | None,
    game_data: Any,
    rng: random.Random,
    session_path: str,
    template_path: str,
) -> tuple[dict, list[dict]]:
    """Обработка атаки игрока."""
    state = copy.deepcopy(state)
    player = state["player"]
    world = state["world"]
    active_combat = world["activeCombat"]
    combat_mob = active_combat["monster"]

    # Получаем оружие
    equipment = player.get("equipment", {})
    weapon_item = equipment.get("weapon")
    if not weapon_item:
        return state, [{"id": "err_no_weapon"}]

    weapon_item_data = game_data.get_item(weapon_item["itemId"])
    if not weapon_item_data:
        return state, [{"id": "err_weapon_not_found"}]

    # Извлекаем damage из stats.damage
    weapon_stats = weapon_item_data.get("stats", {}).get("damage", {})
    if not weapon_stats:
        return state, [{"id": "err_weapon_no_damage"}]

    # Атака
    result = roll_player_weapon_attack(
        player,
        weapon_stats,
        {"defense": 0, "evasion": combat_mob.get("evasion", 0)},
        affinities,
        rng,
        active_effects=world.get("activeEffects"),
        monster_debuffs=combat_mob.get("activeEffects", []),
        damage_multiplier_bonus=damage_multiplier_bonus,
        min_hit_override=min_hit_override,
    )

    events = []

    if result["hit"]:
        # Урон монстру
        combat_mob["hp"] = max(0, combat_mob["hp"] - result["damage"])

        # Износ оружия
        state, weapon_events = register_weapon_hit(state)
        events.extend(weapon_events)

        # Срабатывание покрытия оружия
        state, coating_events = process_weapon_coating_on_hit(state, combat_mob, affinities)
        events.extend(coating_events)

        # Перки (оглушающий удар)
        perk_events = apply_on_weapon_hit_perks(state, combat_mob, rng)
        events.extend(perk_events)

        events.append({
            "id": "attack_hit",
            "damage": result["damage"],
            "damageType": result.get("damageType", "physical"),
            "isCrit": result.get("isCrit", False),
        })
    else:
        events.append({"id": "attack_miss"})

    # Проверка смерти монстра
    if combat_mob["hp"] <= 0:
        return _on_monster_defeated(state, game_data, rng, session_path, template_path)

    # Ход монстра
    state, monster_events = _execute_monster_turn(state, game_data, rng, session_path, template_path)
    events.extend(monster_events)
    return state, events


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------


def _get_current_node(map_data: dict) -> dict:
    """Получает текущий узел карты."""
    current_id = map_data.get("currentNodeId", "")
    for node in map_data.get("nodes", []):
        if node["id"] == current_id:
            return node
    return {}
