"""Применение алхимических расходников: зелья, эликсиры, масла, бомбы (§12, §13, §22.3)."""

from __future__ import annotations

import copy
import random
from typing import Any

from .data_loader import GameData
from .inventory import remove_item, has_item


# ---------------------------------------------------------------------------
# А. Перки алхимии (§22.3)
# ---------------------------------------------------------------------------

def has_herbalist(player: dict[str, Any]) -> bool:
    """alchemy >= 3 — зелья лечения/маны +25% (§22.3)."""
    return player.get("skills", {}).get("alchemy", 0) >= 3


def has_double_dose(player: dict[str, Any]) -> bool:
    """alchemy >= 10 — длительность эликсиров и заряды масел ×1.5 (§22.3)."""
    return player.get("skills", {}).get("alchemy", 0) >= 10


def has_elemental_breakthrough(player: dict[str, Any]) -> bool:
    """pyromancy >= 10 — стихийный прорыв (§22.2)."""
    return player.get("skills", {}).get("pyromancy", 0) >= 10


# ---------------------------------------------------------------------------
# Б. Применение расходника use_consumable (§13.1, §13.2)
# ---------------------------------------------------------------------------

def use_consumable(
    state: dict[str, Any],
    item_id: str,
    game_data: GameData,
    target_monster: dict[str, Any] | None = None,
    target_affinities: dict[str, float] | None = None,
    rng: random.Random | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Использует расходник из инвентаря игрока.

    Возвращает (new_state, events).
    """
    if rng is None:
        rng = random.Random()

    new_state = copy.deepcopy(state)
    player = new_state["player"]
    world = new_state["world"]
    events: list[dict[str, Any]] = []

    # 1. Проверка наличия в инвентаре
    if not has_item(player, item_id, 1):
        return state, [{"id": "err_invalid_consumable", "itemId": item_id}]

    item_def = game_data.get_item(item_id)
    sub_category = item_def.get("subCategory", "")

    # 2. Бомбы только в бою
    if sub_category == "bomb":
        if not world.get("inCombat") or target_monster is None:
            return state, [{"id": "err_bomb_only_in_combat"}]

    # 3. Списываем 1 единицу
    new_state, rm_events = remove_item(new_state, item_id, 1)
    events.extend(rm_events)
    player = new_state["player"]
    # world нужно переприсвоить после remove_item (deepcopy создал новый world)
    world = new_state["world"]

    # 4. Обработка по subCategory
    if sub_category == "potion":
        events.extend(_apply_potion(player, item_def, world))
    elif sub_category == "elixir":
        events.extend(_apply_elixir(world, item_def, player))
    elif sub_category == "coating":
        events.extend(_apply_coating(world, item_def, player))
    elif sub_category == "bomb":
        events.extend(_apply_bomb(player, item_def, target_monster, target_affinities or {}, rng))

    new_state["player"] = player
    return new_state, events


def _apply_potion(
    player: dict[str, Any],
    item_def: dict[str, Any],
    world: dict[str, Any],
) -> list[dict[str, Any]]:
    """Зелья: лечение, мана, очищение (§13.1)."""
    events: list[dict[str, Any]] = []
    stats = item_def.get("stats", {})
    resources = player.get("resources", {})

    # Лечение HP
    hp_restore = stats.get("hpRestore")
    if hp_restore is not None:
        base = hp_restore["value"]
        if has_herbalist(player):
            base = round(base * 1.25)
        resources_hp = resources.get("hp", {})
        max_hp = resources_hp.get("max", 10)
        current_hp = resources_hp.get("current", 0)
        actual = min(max_hp - current_hp, base)
        resources_hp["current"] = min(max_hp, current_hp + actual)
        events.append({"id": "potion_healed", "amount": actual})

    # Лечение MP
    mp_restore = stats.get("mpRestore")
    if mp_restore is not None:
        base = mp_restore["value"]
        if has_herbalist(player):
            base = round(base * 1.25)
        resources_mp = resources.get("mp", {})
        max_mp = resources_mp.get("max", 2)
        current_mp = resources_mp.get("current", 0)
        actual = min(max_mp - current_mp, base)
        resources_mp["current"] = min(max_mp, current_mp + actual)
        events.append({"id": "potion_mana_restored", "amount": actual})

    # Очищение — удаляем эффекты из world["activeEffects"]
    cure_effects = stats.get("cureEffects")
    if cure_effects is not None:
        active = world.get("activeEffects", [])
        removed_types: list[str] = []
        new_active: list[dict[str, Any]] = []
        for eff in active:
            eff_type = eff.get("type", "")
            if eff_type in cure_effects:
                removed_types.append(eff_type)
            else:
                new_active.append(eff)
        world["activeEffects"] = new_active
        if removed_types:
            events.append({"id": "potion_cured", "cured": removed_types})

    return events


def _apply_elixir(
    world: dict[str, Any],
    item_def: dict[str, Any],
    player: dict[str, Any],
) -> list[dict[str, Any]]:
    """Эликсиры: бафф статов, стакинг — макс 1 эликсир (§13.2)."""
    stats = item_def.get("stats", {})
    buff = stats.get("buffEffect", {})

    base_duration = buff.get("durationCombatTurns", 5)
    ticks = base_duration
    if has_double_dose(player):
        ticks = round(base_duration * 1.5)

    effect: dict[str, Any] = {
        "id": item_def["id"],
        "category": "elixir",
        "stat": buff.get("stat", "defense"),
        "value": buff.get("value", 0),
        "ticksLeft": ticks,
    }
    if "maxHitCapOverride" in buff:
        effect["maxHitCapOverride"] = buff["maxHitCapOverride"]
    if "evasionPenalty" in buff:
        effect["evasionPenalty"] = buff["evasionPenalty"]

    # Правило стакинга: макс 1 эликсир
    active = world.get("activeEffects", [])
    world["activeEffects"] = [e for e in active if e.get("category") != "elixir"]
    world["activeEffects"].append(effect)

    return [{"id": "elixir_applied", "itemId": item_def["id"], "ticksLeft": ticks}]


def _apply_coating(
    world: dict[str, Any],
    item_def: dict[str, Any],
    player: dict[str, Any],
) -> list[dict[str, Any]]:
    """Масла/яды: покрытие оружия, стакинг — макс 1 покрытие (§13.2)."""
    stats = item_def.get("stats", {})
    coat = stats.get("coatingEffect", {})

    base_charges = coat.get("charges", 3)
    charges = base_charges
    if has_double_dose(player):
        charges = round(base_charges * 1.5)

    effect: dict[str, Any] = {
        "id": item_def["id"],
        "category": "coating",
        "chargesLeft": charges,
    }
    if "bonusDamage" in coat:
        effect["bonusDamage"] = coat["bonusDamage"]
        effect["damageType"] = coat["damageType"]
    if "dotType" in coat:
        effect["dotType"] = coat["dotType"]
        effect["hpDeltaPerTurn"] = coat["hpDeltaPerTurn"]
        effect["dotTurns"] = coat["dotTurns"]

    # Правило стакинга: макс 1 покрытие
    active = world.get("activeEffects", [])
    world["activeEffects"] = [e for e in active if e.get("category") != "coating"]
    world["activeEffects"].append(effect)

    return [{"id": "coating_applied", "itemId": item_def["id"], "chargesLeft": charges}]


def _apply_bomb(
    player: dict[str, Any],
    item_def: dict[str, Any],
    target_monster: dict[str, Any],
    target_affinities: dict[str, float],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Бомбы: меткий урон, игнор брони (§13.2)."""
    from .combat_math import get_damage_multiplier

    stats = item_def.get("stats", {})
    dmg_stats = stats.get("damage", {})
    hit_chance = dmg_stats.get("hitChance", 80)
    events: list[dict[str, Any]] = []

    # Проверка попадания
    if rng.randint(0, 100) > hit_chance:
        events.append({"id": "bomb_missed", "itemId": item_def["id"]})
        return events

    # Бросок урона
    raw = rng.randint(dmg_stats["min"], dmg_stats["max"])

    # Множитель уязвимости (броня игнорируется)
    mult = get_damage_multiplier(
        dmg_stats["type"],
        target_affinities,
        has_elemental_breakthrough=has_elemental_breakthrough(player),
    )
    final_dmg = max(0, round(raw * mult))

    # Урон монстру
    monster_hp = target_monster["resources"]["hp"]["current"]
    target_monster["resources"]["hp"]["current"] = max(0, monster_hp - final_dmg)

    events.append({
        "id": "bomb_hit",
        "itemId": item_def["id"],
        "damage": final_dmg,
        "damageType": dmg_stats["type"],
    })
    return events


# ---------------------------------------------------------------------------
# В. Срабатывание покрытия при ударе (§13.2)
# ---------------------------------------------------------------------------

def process_weapon_coating_on_hit(
    state: dict[str, Any],
    target_monster: dict[str, Any],
    target_affinities: dict[str, float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Вызывается после успешного попадания оружием игрока (§13.2)."""
    new_state = copy.deepcopy(state)
    world = new_state["world"]
    events: list[dict[str, Any]] = []

    # Ищем активное покрытие
    coating = None
    coating_index = -1
    for i, eff in enumerate(world.get("activeEffects", [])):
        if eff.get("category") == "coating":
            coating = eff
            coating_index = i
            break

    if coating is None:
        return new_state, []

    from .combat_math import get_damage_multiplier

    # oil_fire — бонусный стихийный урон
    if "bonusDamage" in coating:
        bonus_dmg = coating.get("bonusDamage", 0)
        dmg_type = coating.get("damageType", "fire")
        mult = get_damage_multiplier(
            dmg_type,
            target_affinities,
            has_elemental_breakthrough=has_elemental_breakthrough(new_state["player"]),
        )
        extra_dmg = max(0, round(bonus_dmg * mult))

        monster_hp = target_monster["resources"]["hp"]["current"]
        target_monster["resources"]["hp"]["current"] = max(0, monster_hp - extra_dmg)

        events.append({
            "id": "coating_damage",
            "itemId": coating["id"],
            "damage": extra_dmg,
            "damageType": dmg_type,
        })

    # oil_poison — наложение DoT
    if "dotType" in coating:
        dot_type = coating.get("dotType", "poison")
        immunity = target_affinities.get(dot_type, 1.0)
        if immunity == 0.0:
            events.append({"id": "coating_immune", "damageType": dot_type})
        else:
            # Вешаем/обновляем эффект отравления на монстре
            monster_effects = target_monster.setdefault("activeEffects", [])
            found = False
            for eff in monster_effects:
                if eff.get("type") == "poison":
                    eff["hpDeltaPerTurn"] = coating.get("hpDeltaPerTurn", -2)
                    eff["ticksLeft"] = coating.get("dotTurns", 3)
                    found = True
                    break
            if not found:
                monster_effects.append({
                    "type": "poison",
                    "hpDeltaPerTurn": coating.get("hpDeltaPerTurn", -2),
                    "ticksLeft": coating.get("dotTurns", 3),
                })
            events.append({"id": "coating_dot_applied", "damageType": dot_type})

    # Расход заряда
    coating["chargesLeft"] -= 1
    if coating["chargesLeft"] <= 0:
        world["activeEffects"].pop(coating_index)
        events.append({"id": "coating_depleted", "itemId": coating["id"]})

    return new_state, events


# ---------------------------------------------------------------------------
# Г. Тик боевых эффектов за 1 раунд (§13.2, §32.3)
# ---------------------------------------------------------------------------

def tick_combat_round_effects(
    state: dict[str, Any],
    target_monster: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Тикает все эффекты в конце каждого боевого раунда (§13.2, §32.3)."""
    new_state = copy.deepcopy(state)
    world = new_state["world"]
    events: list[dict[str, Any]] = []

    # 1. Тикаем эффекты игрока (activeEffects)
    active_effects = world.get("activeEffects", [])
    new_active: list[dict[str, Any]] = []
    for eff in active_effects:
        eff["ticksLeft"] = eff.get("ticksLeft", 0) - 1
        if eff["ticksLeft"] <= 0:
            events.append({"id": "effect_expired", "itemId": eff.get("id", "")})
        else:
            # Применяем DoT от эффектов игрока (например, яд от паука)
            if eff.get("hpDeltaPerTurn") is not None:
                resources = new_state["player"]["resources"]
                resources["hp"]["current"] = max(
                    0,
                    resources["hp"]["current"] + eff["hpDeltaPerTurn"],
                )
            new_active.append(eff)

    world["activeEffects"] = new_active

    # 2. Тикаем эффекты монстра
    monster_effects = target_monster.get("activeEffects", [])
    new_monster_effects: list[dict[str, Any]] = []
    for eff in monster_effects:
        eff["ticksLeft"] = eff.get("ticksLeft", 0) - 1
        if eff["ticksLeft"] <= 0:
            events.append({"id": "monster_effect_expired", "type": eff.get("type", "")})
        else:
            # Наносим урон монстру от DoT
            hp_delta = eff.get("hpDeltaPerTurn", 0)
            if hp_delta is not None:
                monster_hp = target_monster["resources"]["hp"]["current"]
                target_monster["resources"]["hp"]["current"] = max(
                    0,
                    monster_hp + hp_delta,
                )
            new_monster_effects.append(eff)

    target_monster["activeEffects"] = new_monster_effects

    return new_state, events
