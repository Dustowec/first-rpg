"""Математическое ядро боя: инициатива, меткость, урон, криты, броня, скейлинг."""

from __future__ import annotations

import math
import random
from typing import Any


# ---------------------------------------------------------------------------
# A. Масштабирование монстра под сложность (§3)
# ---------------------------------------------------------------------------

def scale_monster_stats(
    monster_data: dict[str, Any],
    difficulty_multiplier: float = 1.0,
) -> dict[str, Any]:
    """Возвращает рабочий статблок монстра, масштабируя HP и урон."""
    base_hp = monster_data["resources"]["hp"]["max"]
    dmg = monster_data.get("damage", {})
    base_min = dmg.get("min", 0)
    base_max = dmg.get("max", 0)

    scaled_hp = max(1, round(base_hp * difficulty_multiplier))
    scaled_min = max(1, round(base_min * difficulty_multiplier)) if base_min > 0 else 0
    scaled_max = max(scaled_min, round(base_max * difficulty_multiplier))

    return {
        "maxHp": scaled_hp,
        "hp": {"current": scaled_hp, "max": scaled_hp},
        "min": scaled_min,
        "max": scaled_max,
        "defense": monster_data["resources"]["defense"],
        "accuracy": monster_data["resources"].get("accuracy", 50),
        "evasion": monster_data["resources"].get("evasion", 0),
        "damageType": dmg.get("type", "physical"),
    }


# ---------------------------------------------------------------------------
# B. Инициатива в первом раунде (§2.4, §22.1, §27.2)
# ---------------------------------------------------------------------------

def _has_long_reach(player: dict[str, Any]) -> bool:
    return player.get("skills", {}).get("melee_light", 0) >= 6


def _has_lunge(player: dict[str, Any]) -> bool:
    return player.get("skills", {}).get("melee_light", 0) >= 3


def _has_deadly_precision(player: dict[str, Any]) -> bool:
    return player.get("skills", {}).get("melee_light", 0) >= 10


def _has_armor_mastery_10(player: dict[str, Any]) -> bool:
    return player.get("skills", {}).get("armor_mastery", 0) >= 10


def _has_break_armor(player: dict[str, Any]) -> bool:
    return player.get("skills", {}).get("melee_heavy", 0) >= 6


def _has_elemental_breakthrough(player: dict[str, Any]) -> bool:
    return player.get("skills", {}).get("pyromancy", 0) >= 10


def determine_first_attacker(
    player: dict[str, Any],
    monster_stats: dict[str, Any],
    is_ambush: bool,
    rng: random.Random | None = None,
) -> str:
    """Возвращает 'monster' или 'player' — кто бьёт первым."""
    if rng is None:
        rng = random.Random()

    if is_ambush:
        return "monster"

    if _has_long_reach(player):
        return "player"

    agility = player["resources"]["attributes"]["agility"]
    monster_evasion = monster_stats.get("evasion", 0)

    monster_first_chance = _clamp(
        50 + (monster_evasion * 2) - ((agility - 1) * 2), 20, 80
    )

    return "monster" if rng.randint(0, 100) <= monster_first_chance else "player"


# ---------------------------------------------------------------------------
# В. Шансы попадания и уклонения (§2.1, §2.1.1, §13.2, §22.1)
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def get_effective_armor_stats(armor_data: dict[str, Any], player: dict[str, Any]) -> dict[str, int]:
    """Возвращает stats эффективной брони с учётом перка armor_mastery 3."""
    defense = armor_data.get("defense", 0)
    evasion = armor_data.get("evasion", 0)
    weight_penalty = armor_data.get("weightPenalty", 0)

    # armor_mastery >= 3 режет штраф лат вдвое
    if player.get("skills", {}).get("armor_mastery", 0) >= 3:
        weight_penalty = max(0, weight_penalty // 2)

    return {
        "defense": defense,
        "evasion": max(0, evasion - weight_penalty),
    }


def calc_player_evasion(
    player: dict[str, Any],
    game_data: Any,
    active_effects: list[dict] | None = None,
) -> int:
    """Рассчитывает суммарное уклонение игрока."""
    # Получаем эффективную броню
    equipment = player.get("equipment", {})
    armor_item_id = equipment.get("armor", {}).get("itemId")
    if armor_item_id:
        armor_data = game_data.get_item(armor_item_id)
        eff_armor = get_effective_armor_stats(armor_data, player)
        armor_eva = eff_armor.get("evasion", 0)
    else:
        armor_eva = 0

    agility = player["resources"]["attributes"]["agility"]
    agility_eva = math.floor((agility - 1) * 1.5)

    # perk_eva: +5 если melee_light >= 6
    perk_eva = 5 if _has_long_reach(player) else 0

    # Модификаторы от активных эффектов
    effects_eva = 0
    if active_effects:
        for effect in active_effects:
            effects_eva += effect.get("evasionModifier", 0)

    return armor_eva + agility_eva + perk_eva + effects_eva


def calc_player_hit_chance(
    player: dict[str, Any],
    weapon_stats: dict[str, Any],
    target_evasion: int,
    active_effects: list[dict] | None = None,
    min_cap_override: int | None = None,
) -> int:
    """Рассчитывает шанс попадания игрока (§2.1)."""
    weapon_skill = player["resources"]["skills"].get(
        weapon_stats.get("skill", "melee_heavy"), 0
    )
    agility = player["resources"]["attributes"]["agility"]

    raw_hit = 50 + (weapon_skill * 3) + ((agility - 1) * 2) - target_evasion

    # Бонусы от эффектов
    effects_bonus = 0
    has_accuracy_elixir = False
    if active_effects:
        for effect in active_effects:
            effects_bonus += effect.get("hitChanceModifier", 0)
            if effect.get("id") == "elx_accuracy":
                has_accuracy_elixir = True

    raw_hit += effects_bonus

    # Нижний порог
    min_cap = min_cap_override if min_cap_override is not None else 15

    # Верхний порог
    max_cap = 85 if has_accuracy_elixir else 80

    return int(_clamp(round(raw_hit), min_cap, max_cap))


def calc_monster_hit_chance(
    monster_accuracy: int,
    player_evasion: int,
    monster_debuffs: list[dict] | None = None,
) -> int:
    """Рассчитывает шанс попадания монстра."""
    debuff_acc = 0
    if monster_debuffs:
        for debuff in monster_debuffs:
            debuff_acc += debuff.get("accuracyModifier", 0)

    return int(_clamp(monster_accuracy + debuff_acc - player_evasion, 15, 80))


# ---------------------------------------------------------------------------
# Г. Урон, криты, резисты и поглощение бронёй (§2.2, §2.4, §5.1, §22.1–22.2)
# ---------------------------------------------------------------------------

def get_damage_multiplier(
    damage_type: str,
    target_affinities: dict[str, float],
    has_elemental_breakthrough: bool = False,
) -> float:
    """Возвращает множитель урона с учётом резистов и прорыва (§22.2)."""
    mult = target_affinities.get(damage_type, 1.0)

    if has_elemental_breakthrough:
        if 0.0 < mult < 1.0:
            mult = 1.0
        if mult > 1.0:
            mult = 1.5

    return mult


def apply_armor_absorption(
    typed_damage: float,
    target_defense: int,
    ignore_armor_ratio: float = 0.0,
) -> float:
    """Гиперболическое поглощение бронёй: dmg * 10 / (10 + def) (§2.2)."""
    effective_def = max(0.0, target_defense * (1.0 - ignore_armor_ratio))
    return typed_damage * (10.0 / (10.0 + effective_def))


def _get_primary_stat(player: dict[str, Any], weapon_skill_name: str) -> str:
    """melee_heavy -> strength, melee_light -> agility."""
    if weapon_skill_name == "melee_heavy":
        return "strength"
    return "agility"


def _get_berserk_bonus(active_effects: list[dict] | None) -> int:
    bonus = 0
    if active_effects:
        for effect in active_effects:
            if effect.get("id") == "elx_berserk":
                bonus += effect.get("strengthBonus", 0)
    return bonus


def roll_player_weapon_attack(
    player: dict[str, Any],
    weapon_stats: dict[str, Any],
    target_stats: dict[str, Any],
    target_affinities: dict[str, float],
    rng: random.Random | None = None,
    active_effects: list[dict] | None = None,
    monster_debuffs: list[dict] | None = None,
    damage_multiplier_bonus: float = 1.0,
    min_hit_override: int | None = None,
) -> dict[str, Any]:
    """Полный цикл атаки игрока: попадание, урон, крит, броня (§2.2, §2.4, §22.1)."""
    if rng is None:
        rng = random.Random()

    # Hit chance
    target_evasion = target_stats.get("evasion", 0)
    hit_chance = calc_player_hit_chance(
        player, weapon_stats, target_evasion, active_effects, min_hit_override
    )

    # Проверка попадания
    roll = rng.randint(0, 100)
    if roll > hit_chance:
        return {
            "hit": False,
            "hitChance": hit_chance,
            "damage": 0,
            "isCrit": False,
            "damageType": weapon_stats.get("type", "physical"),
        }

    # Сырой урон
    base_roll = rng.randint(weapon_stats["min"], weapon_stats["max"])
    skill_name = weapon_stats.get("skill", "melee_heavy")
    stat_key = _get_primary_stat(player, skill_name)
    primary_stat = player["resources"]["attributes"][stat_key] + _get_berserk_bonus(active_effects)
    weapon_skill_val = player["resources"]["skills"].get(skill_name, 0)

    raw_damage = (
        base_roll * (1.0 + weapon_skill_val * 0.05)
        + (primary_stat - 1) * 0.5
    ) * damage_multiplier_bonus

    # Модификатор уязвимости
    res_mult = get_damage_multiplier(
        weapon_stats.get("type", "physical"),
        target_affinities,
        has_elemental_breakthrough=_has_elemental_breakthrough(player),
    )
    typed_damage = raw_damage * res_mult

    # Поглощение бронёй
    ignore_armor_ratio = 0.25 if _has_break_armor(player) else 0.0
    effective_target_def = target_stats.get("defense", 0)

    # Дебаффы на защите монстра
    if monster_debuffs:
        for debuff in monster_debuffs:
            effective_target_def += debuff.get("defenseModifier", 0)

    absorbed_damage = apply_armor_absorption(typed_damage, effective_target_def, ignore_armor_ratio)

    # Крит
    crit_chance = 5 + (5 if _has_lunge(player) else 0)
    crit_mult = 2.0 if _has_deadly_precision(player) else 1.5
    is_crit = rng.randint(1, 100) <= crit_chance

    final_damage = absorbed_damage * crit_mult if is_crit else absorbed_damage

    # Округление
    if res_mult == 0.0 or base_roll == 0:
        int_damage = 0
    else:
        int_damage = max(1, round(final_damage))

    return {
        "hit": True,
        "hitChance": hit_chance,
        "damage": int_damage,
        "isCrit": is_crit,
        "damageType": weapon_stats.get("type", "physical"),
        "resMultiplier": res_mult,
    }


def roll_monster_attack(
    monster_stats: dict[str, Any],
    player: dict[str, Any],
    game_data: Any,
    rng: random.Random | None = None,
    active_effects: list[dict] | None = None,
    monster_debuffs: list[dict] | None = None,
    ignore_armor_ratio: float = 0.0,
) -> dict[str, Any]:
    """Полный цикл атаки монстра (§2.2, §22.1)."""
    if rng is None:
        rng = random.Random()

    player_evasion = calc_player_evasion(player, game_data, active_effects)
    mob_hit_chance = calc_monster_hit_chance(
        monster_stats.get("accuracy", 50),
        player_evasion,
        monster_debuffs,
    )

    # Проверка попадания
    if rng.randint(0, 100) > mob_hit_chance:
        return {
            "hit": False,
            "hitChance": mob_hit_chance,
            "damage": 0,
            "damageType": monster_stats.get("damageType", "physical"),
        }

    # Бросок урона монстра
    raw = rng.randint(monster_stats["min"], monster_stats["max"])

    # Дебаффы на уроне монстра
    if monster_debuffs:
        for debuff in monster_debuffs:
            raw += debuff.get("damageModifier", 0)
    raw = max(1, raw)

    # Защита игрока
    equipment = player.get("equipment", {})
    armor_item_id = equipment.get("armor", {}).get("itemId")
    player_def = 0
    if armor_item_id:
        armor_data = game_data.get_item(armor_item_id)
        eff_armor = get_effective_armor_stats(armor_data, player)
        player_def = eff_armor.get("defense", 0)

    # Бонусы от эффектов
    if active_effects:
        for effect in active_effects:
            player_def += effect.get("defenseBonus", 0)

    # Поглощение бронёй
    final = apply_armor_absorption(raw, player_def, ignore_armor_ratio)

    # armor_mastery 10: cap на 35% от MaxHP
    if _has_armor_mastery_10(player):
        max_hp = player["resources"]["hp"]["max"]
        cap = max(1, math.floor(max_hp * 0.35))
        final = min(final, cap)

    int_damage = max(1, round(final))

    return {
        "hit": True,
        "hitChance": mob_hit_chance,
        "damage": int_damage,
        "damageType": monster_stats.get("damageType", "physical"),
    }
