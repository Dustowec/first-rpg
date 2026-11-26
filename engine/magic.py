"""Модуль магической системы: заклинания (3 школы), расчёт магии и боевые перки.

Функции принимают (state, spell_id, game_data, target_monster, ...) и возвращают
(new_state, events) без print() и input().
"""

from __future__ import annotations

import copy
import math
import random
from typing import Any

from engine.constants import SKILLS
from engine.consumables import apply_damage_to_monster
from engine.progression import (
    has_caustic_toxins,
    has_concentration,
    has_crushing_strike,
    has_elemental_breakthrough,
    has_frugality,
    has_second_wind,
    has_sturdy_barrier,
    has_soul_harvest,
    has_withering,
)


# ---------------------------------------------------------------------------
# A. Доступность и стоимость заклинаний (§11, §20, §22.2)
# ---------------------------------------------------------------------------


def get_available_spells(player: dict, game_data: Any) -> list[dict]:
    """Возвращает список заклинаний, доступных по уровню школы.

    Args:
        player: Словарь игрока.
        game_data: Объект GameData с данными о заклинаниях.

    Returns:
        Список словарей заклинаний, для которых player[skill] >= requiredSkill.level.
    """
    available = []
    for spell in game_data.spells.values():
        skill_id = spell["requiredSkill"]["id"]
        required_level = spell["requiredSkill"]["level"]
        player_skill = player["skills"].get(skill_id, 0)
        if player_skill >= required_level:
            available.append(spell)
    return available


def get_spell_mp_cost(player: dict, spell: dict) -> int:
    """Рассчитывает стоимость заклинания в MP с учётом перков.

    Args:
        player: Словарь игрока.
        spell: Словарь заклинания.

    Returns:
        Итоговая стоимость в MP (минимум 1).
    """
    cost = spell["stats"]["mpCost"]

    # Перк pyromancy 6 «Концентрация»: -1 MP для стихийных заклинаний
    if spell["school"] == "pyromancy" and has_concentration(player):
        cost = max(1, cost - 1)

    return cost


# ---------------------------------------------------------------------------
# Б. Формулы магии (§18.1, §22.2)
# ---------------------------------------------------------------------------


def calc_spell_hit_chance(player: dict, school_id: str, target_evasion: int) -> int:
    """Рассчитывает шанс попадания заклинания.

    Формула: 55 + (school_skill * 2.5) + ((intelligence - 1) * 1.5) - (target_evasion * 0.5)
    Кламп [25, 85]: int(max(25, min(85, round(raw)))).

    Args:
        player: Словарь игрока.
        school_id: ID школы магии (pyromancy, restoration, hexes).
        target_evasion: Уклонение цели.

    Returns:
        Шанс попадания в процентах (int, кламп [25, 85]).
    """
    school_skill = player["skills"].get(school_id, 0)
    intelligence = player["attributes"]["intelligence"]

    raw = 55 + (school_skill * 2.5) + ((intelligence - 1) * 1.5) - (target_evasion * 0.5)
    return int(max(25, min(85, round(raw))))


def calc_spell_power(
    player: dict,
    school_id: str,
    min_val: int,
    max_val: int,
    rng: random.Random,
) -> float:
    """Рассчитывает силу заклинания (урон/лечение).

    Формула: base * (1.0 + school_skill * 0.05) + ((intelligence - 1) * 0.75)
    Перк restoration 3 «Бережливость»: +20% для лечебных эффектов.

    Args:
        player: Словарь игрока.
        school_id: ID школы магии.
        min_val: Минимальное значение базового броска.
        max_val: Максимальное значение базового броска.
        rng: Экземпляр random.Random для генерации.

    Returns:
        Сила заклинания (float).
    """
    school_skill = player["skills"].get(school_id, 0)
    intelligence = player["attributes"]["intelligence"]

    base = rng.randint(min_val, max_val)
    power = base * (1.0 + school_skill * 0.05) + ((intelligence - 1) * 0.75)

    # Перк restoration 3 «Бережливость»: +20% для лечения
    if school_id == "restoration" and has_frugality(player):
        power *= 1.20

    return power


# ---------------------------------------------------------------------------
# В. Применение заклинаний (cast_spell)
# ---------------------------------------------------------------------------

# Поддерживаемые школы
SUPPORTED_SCHOOLS = ("pyromancy", "restoration", "hexes")

# Заклинания, которые можно применять вне боя
OUT_OF_COMBAT_SPELLS = {"spl_minor_mend", "spl_purify", "spl_stone_ward"}


def _check_spell_lock(state: dict, spell: dict) -> dict | None:
    """Проверяет, доступен ли навык для заклинания."""
    skill_id = spell["requiredSkill"]["id"]
    required_level = spell["requiredSkill"]["level"]
    player_skill = state["player"]["skills"].get(skill_id, 0)

    if player_skill < required_level:
        return {"id": "err_spell_locked", "spell": spell["id"], "required": required_level}
    return None


def _check_mp_enough(state: dict, mp_cost: int) -> dict | None:
    """Проверяет, достаточно ли MP."""
    current_mp = state["player"]["resources"]["mp"]["current"]
    if current_mp < mp_cost:
        return {"id": "err_not_enough_mp", "needed": mp_cost, "available": current_mp}
    return None


def _check_combat_context(
    spell_id: str,
    in_combat: bool,
    target_monster: dict | None,
) -> dict | None:
    """Проверяет контекст применения заклинания."""
    if spell_id not in OUT_OF_COMBAT_SPELLS:
        if not in_combat or target_monster is None:
            return {"id": "err_combat_required", "spell": spell_id}
    return None


def _apply_armor_ignore_half(
    typed_damage: float,
    target_defense: int,
) -> float:
    """Применяет игнор 50% физической брони для заклинаний (§18.1)."""
    return apply_armor_absorption(typed_damage, target_defense, ignore_armor_ratio=0.5)


def _add_monster_effect(
    target_monster: dict,
    effect: dict[str, Any],
) -> None:
    """Добавляет эффект на монстра в activeEffects."""
    target_monster.setdefault("activeEffects", []).append(effect)


def _add_player_effect(state: dict, effect: dict[str, Any]) -> None:
    """Добавляет эффект игроку в world.activeEffects."""
    state["world"].setdefault("activeEffects", []).append(effect)


def _cast_fire_spell(
    state: dict,
    spell: dict,
    target_monster: dict,
    target_affinities: dict[str, float] | None,
    rng: random.Random,
) -> tuple[dict, list[dict]]:
    """Каст огненного заклинания (spl_spark, spl_fireball)."""
    damage_min = spell["stats"]["damage"]["min"]
    damage_max = spell["stats"]["damage"]["max"]
    damage_type = spell["stats"]["damage"]["type"]

    # Проверка попадания
    target_evasion = target_monster.get("evasion", 0)
    hit_chance = calc_spell_hit_chance(state["player"], "pyromancy", target_evasion)
    hit = rng.random() * 100 < hit_chance

    if not hit:
        state["player"]["resources"]["mp"]["current"] -= spell["stats"]["mpCost"]
        events = [{"id": "spell_missed", "spell": spell["id"]}]
        return state, events

    # Расчёт урона
    raw_damage = rng.randint(damage_min, damage_max)
    from engine.combat_math import apply_armor_absorption, get_damage_multiplier

    mult = get_damage_multiplier(
        damage_type,
        target_affinities or {},
        has_elemental_breakthrough(state["player"]),
    )
    typed_damage = raw_damage * mult

    # Игнор 50% брони
    final_damage = apply_armor_absorption(typed_damage, target_monster.get("defense", 0), ignore_armor_ratio=0.5)
    final_damage = round(final_damage)

    # Применяем урон (формат-агностично: плоский hp или resources — R-4)
    apply_damage_to_monster(target_monster, final_damage)

    # Накладываем burn
    events = []
    burn_duration = 2  # базово 2 хода
    burn_delta = -1  # базово -1 HP/ход

    if spell["id"] == "spl_fireball":
        burn_duration = 3
        burn_delta = -2

    # Перк pyromancy 3 «Жар пламени»: +1 ход
    if has_concentration(state["player"]):
        burn_duration += 1

    _add_monster_effect(
        target_monster,
        {
            "id": "burn",
            "type": "burn",
            "hpDeltaPerTurn": burn_delta,
            "ticksLeft": burn_duration,
        },
    )

    # Списываем ману
    state["player"]["resources"]["mp"]["current"] -= spell["stats"]["mpCost"]

    events.append(
        {
            "id": "spell_cast",
            "spell": spell["id"],
            "damage": final_damage,
            "damageType": damage_type,
        }
    )

    return state, events


def _cast_ice_spell(
    state: dict,
    spell: dict,
    target_monster: dict,
    target_affinities: dict[str, float] | None,
    rng: random.Random,
) -> tuple[dict, list[dict]]:
    """Каст ледяного заклинания (spl_frost_shard)."""
    damage_min = spell["stats"]["damage"]["min"]
    damage_max = spell["stats"]["damage"]["max"]
    damage_type = spell["stats"]["damage"]["type"]

    # Проверка попадания
    target_evasion = target_monster.get("evasion", 0)
    hit_chance = calc_spell_hit_chance(state["player"], "pyromancy", target_evasion)
    hit = rng.random() * 100 < hit_chance

    if not hit:
        state["player"]["resources"]["mp"]["current"] -= spell["stats"]["mpCost"]
        events = [{"id": "spell_missed", "spell": spell["id"]}]
        return state, events

    # Расчёт урона
    raw_damage = rng.randint(damage_min, damage_max)
    from engine.combat_math import apply_armor_absorption, get_damage_multiplier

    mult = get_damage_multiplier(
        damage_type,
        target_affinities or {},
        has_elemental_breakthrough(state["player"]),
    )
    typed_damage = raw_damage * mult

    final_damage = apply_armor_absorption(typed_damage, target_monster.get("defense", 0), ignore_armor_ratio=0.5)
    final_damage = round(final_damage)

    # Урон (формат-агностично — R-4)
    apply_damage_to_monster(target_monster, final_damage)

    # Дебафф evasionDelta: -10 на 3 хода
    _add_monster_effect(
        target_monster,
        {
            "id": "spl_frost_shard",
            "evasionDelta": -10,
            "ticksLeft": 3,
        },
    )

    state["player"]["resources"]["mp"]["current"] -= spell["stats"]["mpCost"]

    events = [
        {
            "id": "spell_cast",
            "spell": spell["id"],
            "damage": final_damage,
            "damageType": damage_type,
        }
    ]

    return state, events


def _cast_healing_spell(
    state: dict,
    spell: dict,
    rng: random.Random,
) -> tuple[dict, list[dict]]:
    """Каст лечебного заклинания (spl_minor_mend)."""
    heal_min = spell["stats"]["heal"]["min"]
    heal_max = spell["stats"]["heal"]["max"]

    heal_amount = round(calc_spell_power(state["player"], "restoration", heal_min, heal_max, rng))

    # Лечение без проверки попадания (100% на себя)
    state["player"]["resources"]["hp"]["current"] = min(
        state["player"]["resources"]["hp"]["max"],
        state["player"]["resources"]["hp"]["current"] + heal_amount,
    )

    state["player"]["resources"]["mp"]["current"] -= spell["stats"]["mpCost"]

    events = [
        {
            "id": "spell_cast",
            "spell": spell["id"],
            "healed": heal_amount,
        }
    ]

    return state, events


def _cast_buff_spell(
    state: dict,
    spell: dict,
    rng: random.Random,
) -> tuple[dict, list[dict]]:
    """Каст бафф-заклинания (spl_stone_ward)."""
    buff_stat = spell["stats"]["buffEffect"]["stat"]
    buff_value = spell["stats"]["buffEffect"]["value"]
    base_duration = spell["stats"]["buffEffect"]["durationCombatTurns"]

    # Перк restoration 6 «Стойкий барьер»: +2 хода
    duration = base_duration + (2 if has_sturdy_barrier(state["player"]) else 0)

    _add_player_effect(
        state,
        {
            "id": "spl_stone_ward",
            "category": "buff",
            "stat": buff_stat,
            "value": buff_value,
            "ticksLeft": duration,
        },
    )

    state["player"]["resources"]["mp"]["current"] -= spell["stats"]["mpCost"]

    events = [
        {
            "id": "spell_cast",
            "spell": spell["id"],
            "buff": buff_stat,
            "value": buff_value,
            "duration": duration,
        }
    ]

    return state, events


def _cast_cure_spell(
    state: dict,
    spell: dict,
    rng: random.Random,
) -> tuple[dict, list[dict]]:
    """Каст очищения (spl_purify)."""
    # Снимаем poison и bleeding
    effects = state["world"].get("activeEffects", [])
    removed = []
    remaining = []
    for eff in effects:
        if eff.get("id") in ("poison", "bleeding", "burn"):
            removed.append(eff.get("id", "unknown"))
        else:
            remaining.append(eff)
    state["world"]["activeEffects"] = remaining

    # Лечение
    heal_min = 6
    heal_max = 8
    heal_amount = round(calc_spell_power(state["player"], "restoration", heal_min, heal_max, rng))

    state["player"]["resources"]["hp"]["current"] = min(
        state["player"]["resources"]["hp"]["max"],
        state["player"]["resources"]["hp"]["current"] + heal_amount,
    )

    state["player"]["resources"]["mp"]["current"] -= spell["stats"]["mpCost"]

    events = [
        {
            "id": "spell_cast",
            "spell": spell["id"],
            "healed": heal_amount,
            "removedDebuffs": removed,
        }
    ]

    return state, events


def _cast_debuff_spell(
    state: dict,
    spell: dict,
    target_monster: dict,
    rng: random.Random,
) -> tuple[dict, list[dict]]:
    """Каст проклятия (spl_weakness)."""
    target_evasion = target_monster.get("evasion", 0)
    hit_chance = calc_spell_hit_chance(state["player"], "hexes", target_evasion)
    hit = rng.random() * 100 < hit_chance

    if not hit:
        state["player"]["resources"]["mp"]["current"] -= spell["stats"]["mpCost"]
        events = [{"id": "spell_missed", "spell": spell["id"]}]
        return state, events

    # Базовое проклятие: damageDelta: -2, accuracyDelta: -10, ticksLeft: 4
    debuff: dict[str, Any] = {
        "id": "spl_weakness",
        "isCurse": True,
        "damageDelta": -2,
        "accuracyDelta": -10,
        "ticksLeft": 4,
    }

    # Перк hexes 6 «Иссушение»: + defenseDelta: -2
    if has_withering(state["player"]):
        debuff["defenseDelta"] = -2

    _add_monster_effect(target_monster, debuff)

    state["player"]["resources"]["mp"]["current"] -= spell["stats"]["mpCost"]

    events = [
        {
            "id": "spell_cast",
            "spell": spell["id"],
            "debuff": debuff,
        }
    ]

    return state, events


def _cast_dot_spell(
    state: dict,
    spell: dict,
    target_monster: dict,
    target_affinities: dict[str, float] | None,
    rng: random.Random,
) -> tuple[dict, list[dict]]:
    """Каст ядовитого заклинания (spl_venom_touch)."""
    damage_min = spell["stats"]["dotEffect"]["type"]  # placeholder
    # Получаем мин/макс из dotEffect
    dot_effect = spell["stats"]["dotEffect"]
    dot_type = dot_effect["type"]

    # Проверка иммунитета
    affinities = target_affinities or {}
    if affinities.get(dot_type, 1.0) == 0.0:
        # Полный иммунитет — заклинание не проходит
        state["player"]["resources"]["mp"]["current"] -= spell["stats"]["mpCost"]
        events = [{"id": "spell_immune", "spell": spell["id"], "target": dot_type}]
        return state, events

    # Урон 2..3 типом poison
    raw_damage = rng.randint(2, 3)
    from engine.combat_math import apply_armor_absorption, get_damage_multiplier

    mult = get_damage_multiplier(dot_type, affinities, False)
    typed_damage = raw_damage * mult

    final_damage = apply_armor_absorption(typed_damage, target_monster.get("defense", 0), ignore_armor_ratio=0.5)
    final_damage = round(final_damage)

    # Урон ядом (формат-агностично — R-4)
    apply_damage_to_monster(target_monster, final_damage)

    # Накладываем poison
    dot_hp_delta = -2
    if has_caustic_toxins(state["player"]):
        dot_hp_delta = -3  # перк hexes 3 «Едкие токсины»

    _add_monster_effect(
        target_monster,
        {
            "id": "spl_venom_touch",
            "type": "poison",
            "hpDeltaPerTurn": dot_hp_delta,
            "ticksLeft": 3,
        },
    )

    state["player"]["resources"]["mp"]["current"] -= spell["stats"]["mpCost"]

    events = [
        {
            "id": "spell_cast",
            "spell": spell["id"],
            "damage": final_damage,
            "damageType": dot_type,
        }
    ]

    return state, events


def _cast_drain_spell(
    state: dict,
    spell: dict,
    target_monster: dict,
    target_affinities: dict[str, float] | None,
    rng: random.Random,
) -> tuple[dict, list[dict]]:
    """Каст похищения жизни (spl_life_drain)."""
    damage_min = spell["stats"]["damage"]["min"]
    damage_max = spell["stats"]["damage"]["max"]
    damage_type = spell["stats"]["damage"]["type"]

    # Проверка попадания
    target_evasion = target_monster.get("evasion", 0)
    hit_chance = calc_spell_hit_chance(state["player"], "hexes", target_evasion)
    hit = rng.random() * 100 < hit_chance

    if not hit:
        state["player"]["resources"]["mp"]["current"] -= spell["stats"]["mpCost"]
        events = [{"id": "spell_missed", "spell": spell["id"]}]
        return state, events

    # Расчёт урона
    raw_damage = rng.randint(damage_min, damage_max)
    from engine.combat_math import apply_armor_absorption, get_damage_multiplier

    mult = get_damage_multiplier(
        damage_type,
        target_affinities or {},
        has_elemental_breakthrough(state["player"]),
    )
    typed_damage = raw_damage * mult

    final_damage = apply_armor_absorption(typed_damage, target_monster.get("defense", 0), ignore_armor_ratio=0.5)
    final_damage = round(final_damage)

    # Урон вампиризмом (формат-агностично — R-4)
    apply_damage_to_monster(target_monster, final_damage)

    # Вампиризм: 50% от урона
    heal_amount = math.floor(final_damage * 0.5)
    state["player"]["resources"]["hp"]["current"] = min(
        state["player"]["resources"]["hp"]["max"],
        state["player"]["resources"]["hp"]["current"] + heal_amount,
    )

    state["player"]["resources"]["mp"]["current"] -= spell["stats"]["mpCost"]

    events = [
        {
            "id": "spell_cast",
            "spell": spell["id"],
            "damage": final_damage,
            "damageType": damage_type,
            "healed": heal_amount,
        }
    ]

    return state, events


def cast_spell(
    state: dict,
    spell_id: str,
    game_data: Any,
    target_monster: dict | None = None,
    target_affinities: dict[str, float] | None = None,
    rng: random.Random | None = None,
) -> tuple[dict, list[dict]]:
    """Применяет заклинание.

    Args:
        state: Глубокая копия состояния игры.
        spell_id: ID заклинания.
        game_data: Объект GameData.
        target_monster: Цель (монстр) для атакующих заклинаний.
        target_affinities: Аффинности цели для расчёта урона.
        rng: Генератор случайных чисел.

    Returns:
        (new_state, events) — новое состояние и список событий.
    """
    if rng is None:
        rng = random.Random()

    state = copy.deepcopy(state)
    spell = game_data.get_spell(spell_id)

    if spell is None:
        return state, [{"id": "err_spell_not_found", "spell": spell_id}]

    # Проверка доступа к навыку
    lock_err = _check_spell_lock(state, spell)
    if lock_err:
        return state, [lock_err]

    # Расчёт стоимости MP
    mp_cost = get_spell_mp_cost(state["player"], spell)

    # Проверка MP
    mp_err = _check_mp_enough(state, mp_cost)
    if mp_err:
        return state, [mp_err]

    # Проверка контекста (бой/не бой)
    in_combat = state["world"].get("inCombat", False)
    context_err = _check_combat_context(spell_id, in_combat, target_monster)
    if context_err:
        return state, [context_err]

    # Поддержка schools
    school = spell["school"]
    sub_category = spell["subCategory"]

    # ------------------------------------------------------------------
    # Pyromancy
    # ------------------------------------------------------------------
    if school == "pyromancy":
        if sub_category == "damage":
            if spell["id"] == "spl_spark":
                state, events = _cast_fire_spell(state, spell, target_monster, target_affinities, rng)
            elif spell["id"] == "spl_frost_shard":
                state, events = _cast_ice_spell(state, spell, target_monster, target_affinities, rng)
            elif spell["id"] == "spl_fireball":
                state, events = _cast_fire_spell(state, spell, target_monster, target_affinities, rng)
            else:
                return state, [{"id": "err_unknown_spell", "spell": spell_id}]

    # ------------------------------------------------------------------
    # Restoration
    # ------------------------------------------------------------------
    elif school == "restoration":
        if sub_category == "healing":
            state, events = _cast_healing_spell(state, spell, rng)
        elif sub_category == "buff":
            state, events = _cast_buff_spell(state, spell, rng)
        elif sub_category == "cure":
            state, events = _cast_cure_spell(state, spell, rng)
        else:
            return state, [{"id": "err_unknown_spell", "spell": spell_id}]

    # ------------------------------------------------------------------
    # Hexes
    # ------------------------------------------------------------------
    elif school == "hexes":
        if sub_category == "debuff":
            state, events = _cast_debuff_spell(state, spell, target_monster, rng)
        elif sub_category == "damage_dot":
            state, events = _cast_dot_spell(state, spell, target_monster, target_affinities, rng)
        elif sub_category == "drain":
            state, events = _cast_drain_spell(state, spell, target_monster, target_affinities, rng)
        else:
            return state, [{"id": "err_unknown_spell", "spell": spell_id}]

    else:
        return state, [{"id": "err_unknown_school", "school": school}]

    return state, events


# ---------------------------------------------------------------------------
# Г. Боевые перки и триггеры (§22.1–22.2)
# ---------------------------------------------------------------------------


def apply_on_weapon_hit_perks(
    state: dict,
    target_monster: dict,
    rng: random.Random,
) -> list[dict]:
    """Веха melee_heavy 3 «Оглушающий удар»: 20% шанс наложить дебафф.

    Args:
        state: Состояние игры.
        target_monster: Цель удара.
        rng: Генератор случайных чисел.

    Returns:
        Список событий.
    """
    player = state["player"]

    if not has_milestone(player, "melee_heavy", 3):
        return []

    if rng.random() <= 0.20:
        _add_monster_effect(
            target_monster,
            {
                "id": "perk_stunning_blow",
                "accuracyDelta": -10,
                "ticksLeft": 2,
            },
        )
        return [{"id": "perk_stunning_blow_triggered"}]

    return []


def check_second_wind_trigger(state: dict) -> list[dict]:
    """Веха restoration 10 «Второе дыхание»: авто-бафф при HP < 20%.

    Срабатывает 1 раз за бой.

    Args:
        state: Состояние игры.

    Returns:
        Список событий (пусто, если не сработало).
    """
    player = state["player"]

    if not has_second_wind(player):
        return []

    hp_current = player["resources"]["hp"]["current"]
    hp_max = player["resources"]["hp"]["max"]

    if hp_current <= 0 or hp_current >= hp_max * 0.20:
        return []

    combat_flags = state["world"].setdefault("combatFlags", {})
    if combat_flags.get("secondWindUsed"):
        return []

    # Срабатывание
    combat_flags["secondWindUsed"] = True

    # Бафф защиты
    base_duration = 3
    duration = base_duration + (2 if has_sturdy_barrier(player) else 0)

    _add_player_effect(
        state,
        {
            "id": "perk_second_wind",
            "category": "buff",
            "stat": "defense",
            "value": 5,
            "ticksLeft": duration,
        },
    )

    return [{"id": "perk_second_wind_triggered"}]


def apply_on_monster_killed_perks(
    state: dict,
    target_monster: dict,
) -> list[dict]:
    """Веха hexes 10 «Жатва душ»: восстановление при добивании проклятого монстра.

    Args:
        state: Состояние игры.
        target_monster: Убитый монстр.

    Returns:
        Список событий.
    """
    player = state["player"]

    if not has_soul_harvest(player):
        return []

    # Проверка, было ли проклятие на монстре
    has_curse = any(
        eff.get("isCurse") for eff in target_monster.get("activeEffects", [])
    )

    if not has_curse:
        return []

    # Восстановление +3 HP и +3 MP
    player["resources"]["hp"]["current"] = min(
        player["resources"]["hp"]["max"],
        player["resources"]["hp"]["current"] + 3,
    )
    player["resources"]["mp"]["current"] = min(
        player["resources"]["mp"]["max"],
        player["resources"]["mp"]["current"] + 3,
    )

    return [
        {
            "id": "perk_soul_harvest_triggered",
            "hpRestored": 3,
            "mpRestored": 3,
        }
    ]


def can_use_crushing_strike(state: dict) -> bool:
    """Проверяет доступность «Сокрушения» (melee_heavy 10).

    Args:
        state: Состояние игры.

    Returns:
        True если можно использовать.
    """
    player = state["player"]

    if not has_crushing_strike(player):
        return False

    combat_flags = state["world"].get("combatFlags", {})
    cooldown = combat_flags.get("crushingCooldown", 0)

    return cooldown == 0


def use_crushing_strike(state: dict) -> tuple[dict, list[dict]]:
    """Устанавливает кулдаун «Сокрушения» на 4 хода.

    Args:
        state: Состояние игры.

    Returns:
        (new_state, events).
    """
    state = copy.deepcopy(state)
    state["world"].setdefault("combatFlags", {})["crushingCooldown"] = 4

    return state, [{"id": "perk_crushing_strike_ready"}]


# ---------------------------------------------------------------------------
# Вспомогательная функция для проверки вех (локальная копия)
# ---------------------------------------------------------------------------


def has_milestone(player: dict, skill_id: str, milestone_level: int) -> bool:
    """Проверяет, достигнут ли порог навыка."""
    return player["skills"].get(skill_id, 0) >= milestone_level


def clear_combat_flags(state: dict) -> dict:
    """Очищает combatFlags при завершении боя.

    Args:
        state: Состояние игры.

    Returns:
        Обновлённое состояние.
    """
    state = copy.deepcopy(state)
    if "combatFlags" in state["world"]:
        del state["world"]["combatFlags"]
    return state
