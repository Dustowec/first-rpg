"""Модуль прогрессии персонажа: расчёт ресурсов, XP, распределение очков, реестр вех.

Чистые функции: принимают state: dict, возвращают (new_state, events) или вычисленные значения.
Не используют print()/input(). Соблюдают капы: level 1..20, attributes 1..10, skills 0..10.
"""

from __future__ import annotations

import copy
from typing import Any

from engine.constants import (
    ATTRIBUTES,
    ATTR_MAX,
    MAX_START_ATTR_BONUS,
    SKILLS,
    SKILL_MAX,
    LEVEL_MAX,
)


# ---------------------------------------------------------------------------
# Формулы расчёта производных параметров
# ---------------------------------------------------------------------------


def calc_max_hp(level: int, constitution: int) -> int:
    """Возвращает максимальное HP.

    Формула: 10 + (level - 1) * 2 + (constitution - 1) * 2
    Граничные точки: (1, 1) -> 10, (20, 1) -> 48, (20, 10) -> 66.
    """
    return 10 + (level - 1) * 2 + (constitution - 1) * 2


def calc_max_mp(level: int, wisdom: int) -> int:
    """Возвращает максимальное MP.

    Формула: 2 + (level - 1) * 1 + (wisdom - 1) * 2
    Граничные точки: (1, 1) -> 2, (20, 1) -> 21, (20, 10) -> 39.
    """
    return 2 + (level - 1) * 1 + (wisdom - 1) * 2


def xp_to_next_level(level: int) -> int | None:
    """Возвращает XP, необходимый для перехода на следующий уровень.

    Формула: round(50 * (level ** 1.35))
    Если level >= 20: возвращает None (жёсткий кап).
    Проверка: level=1 -> 50, level=2 -> 127, level=10 -> 1119, level=19 -> 2662.
    """
    if level >= LEVEL_MAX:
        return None
    return round(50 * (level ** 1.35))


def sync_derived_resources(player: dict, restore_delta: bool = True) -> None:
    """Пересчитывает MaxHP и MaxMP, при restore_delta=True восстанавливает текущие значения.

    Увеличивает hp.current и mp.current на разницу max(0, new_max - old_max),
    затем клампит current в [0, new_max].
    """
    level = player["level"]
    constitution = player["attributes"]["constitution"]
    wisdom = player["attributes"]["wisdom"]

    old_max_hp = player["resources"]["hp"]["max"]
    old_max_mp = player["resources"]["mp"]["max"]

    new_max_hp = calc_max_hp(level, constitution)
    new_max_mp = calc_max_mp(level, wisdom)

    if restore_delta:
        hp_delta = max(0, new_max_hp - old_max_hp)
        mp_delta = max(0, new_max_mp - old_max_mp)
        player["resources"]["hp"]["current"] += hp_delta
        player["resources"]["mp"]["current"] += mp_delta

    # Clamp current в [0, new_max]
    player["resources"]["hp"]["current"] = max(0, min(player["resources"]["hp"]["current"], new_max_hp))
    player["resources"]["mp"]["current"] = max(0, min(player["resources"]["mp"]["current"], new_max_mp))

    player["resources"]["hp"]["max"] = new_max_hp
    player["resources"]["mp"]["max"] = new_max_mp


# ---------------------------------------------------------------------------
# Распределение атрибутов и навыков
# ---------------------------------------------------------------------------


def allocate_attribute(state: dict, attr_id: str, is_creation: bool = False) -> tuple[dict, list[dict]]:
    """Распределяет 1 очко атрибута.

    Args:
        state: Копия состояния игры (deepcopy делается внутри).
        attr_id: ID атрибута (strength, agility, constitution, intelligence, wisdom).
        is_creation: True при создании персонажа (ограничение +2 сверх базовой единицы).

    Returns:
        (new_state, events) — новое состояние и список событий.
    """
    state = copy.deepcopy(state)
    player = state["player"]
    events: list[dict[str, Any]] = []

    # Проверка валидности атрибута
    if attr_id not in ATTRIBUTES:
        events.append({"id": "err_invalid_attribute", "attr": attr_id})
        return state, events

    # Проверка наличия очков
    if player["unspentPoints"]["attributes"] < 1:
        events.append({"id": "err_no_attribute_points"})
        return state, events

    current_val = player["attributes"][attr_id]

    # Проверка жёсткого капа 10
    if current_val >= ATTR_MAX:
        events.append({"id": "err_attribute_max", "attr": attr_id, "max": ATTR_MAX})
        return state, events

    # Правило создания персонажа: нельзя вложить более +2 сверх базовой единицы
    if is_creation and current_val >= MAX_START_ATTR_BONUS + 1:
        events.append({"id": "err_creation_attr_cap", "attr": attr_id, "max": MAX_START_ATTR_BONUS + 1})
        return state, events

    # Распределение
    player["unspentPoints"]["attributes"] -= 1
    player["attributes"][attr_id] += 1

    # Ретроактивный пересчёт ресурсов
    sync_derived_resources(player, restore_delta=True)

    events.append({"id": "attr_increased", "attr": attr_id, "value": player["attributes"][attr_id]})
    return state, events


def allocate_skill(state: dict, skill_id: str) -> tuple[dict, list[dict]]:
    """Распределяет 1 очко навыка.

    Args:
        state: Копия состояния игры.
        skill_id: ID навыка из SKILLS.

    Returns:
        (new_state, events) — новое состояние и список событий.
    """
    state = copy.deepcopy(state)
    player = state["player"]
    events: list[dict[str, Any]] = []

    # Проверка валидности навыка
    if skill_id not in SKILLS:
        events.append({"id": "err_invalid_skill", "skill": skill_id})
        return state, events

    # Проверка наличия очков
    if player["unspentPoints"]["skills"] < 1:
        events.append({"id": "err_no_skill_points"})
        return state, events

    current_val = player["skills"][skill_id]

    # Проверка капа
    if current_val >= SKILL_MAX:
        events.append({"id": "err_skill_max", "skill": skill_id, "max": SKILL_MAX})
        return state, events

    # Распределение
    player["unspentPoints"]["skills"] -= 1
    player["skills"][skill_id] += 1
    new_val = player["skills"][skill_id]

    # Проверка вех (перков)
    if new_val in (3, 6, 10):
        events.append({"id": "perk_unlocked", "skill": skill_id, "level": new_val})

    events.append({"id": "skill_increased", "skill": skill_id, "value": new_val})
    return state, events


# ---------------------------------------------------------------------------
# Начисление опыта и Level-Up
# ---------------------------------------------------------------------------


def grant_xp(state: dict, base_xp: int) -> tuple[dict, list[dict]]:
    """Начисляет опыт и обрабатывает Level-Up.

    Args:
        state: Копия состояния игры.
        base_xp: Базовый опыт для начисления.

    Returns:
        (new_state, events) — новое состояние и список событий.
    """
    state = copy.deepcopy(state)
    player = state["player"]
    events: list[dict[str, Any]] = []

    # Кап 20 уровня
    if player["level"] >= LEVEL_MAX:
        return state, events

    # Учитываем множитель XP
    xp_rate = state.get("meta", {}).get("xpRate", 1.0)
    gained = round(base_xp * xp_rate)

    player["xp"] += gained
    events.append({"id": "xp_gained", "amount": gained})

    # Цикл Level-Up
    while player["level"] < LEVEL_MAX:
        req = xp_to_next_level(player["level"])
        if req is None:
            break

        if player["xp"] >= req:
            player["xp"] -= req
            player["level"] += 1
            player["unspentPoints"]["attributes"] += 1
            player["unspentPoints"]["skills"] += 1

            # Пересчёт ресурсов при повышении уровня
            sync_derived_resources(player, restore_delta=True)

            events.append({"id": "level_up", "level": player["level"]})

            # Достигнут 20-й уровень — обнуляем остаток XP
            if player["level"] == LEVEL_MAX:
                player["xp"] = 0
                break
        else:
            break

    return state, events


# ---------------------------------------------------------------------------
# Реестр вех (Перков)
# ---------------------------------------------------------------------------


def has_milestone(player: dict, skill_id: str, milestone_level: int) -> bool:
    """Проверяет, достигнут ли порог навыка.

    Args:
        player: Словарь игрока.
        skill_id: ID навыка.
        milestone_level: Пороговый уровень (3, 6 или 10).

    Returns:
        True если player["skills"].get(skill_id, 0) >= milestone_level.
    """
    return player["skills"].get(skill_id, 0) >= milestone_level


# ---------------------------------------------------------------------------
# Боевые вехи (melee_heavy)
# ---------------------------------------------------------------------------


def has_stunning_blow(player: dict) -> bool:
    """melee_heavy >= 3: Ошеломляющий удар."""
    return has_milestone(player, "melee_heavy", 3)


def has_armor_sunder(player: dict) -> bool:
    """melee_heavy >= 6: Пробивание брони."""
    return has_milestone(player, "melee_heavy", 6)


def has_crushing_strike(player: dict) -> bool:
    """melee_heavy >= 10: Сокрушительный удар."""
    return has_milestone(player, "melee_heavy", 10)


# ---------------------------------------------------------------------------
# Боевые вехи (melee_light)
# ---------------------------------------------------------------------------


def has_lunge(player: dict) -> bool:
    """melee_light >= 3: Натиск."""
    return has_milestone(player, "melee_light", 3)


def has_long_reach(player: dict) -> bool:
    """melee_light >= 6: Дальний Reach."""
    return has_milestone(player, "melee_light", 6)


def has_deadly_precision(player: dict) -> bool:
    """melee_light >= 10: Смертоносная точность."""
    return has_milestone(player, "melee_light", 10)


# ---------------------------------------------------------------------------
# Вехи брони (armor_mastery)
# ---------------------------------------------------------------------------


def has_armor_comfort(player: dict) -> bool:
    """armor_mastery >= 3: Комфорт брони."""
    return has_milestone(player, "armor_mastery", 3)


def has_tempering(player: dict) -> bool:
    """armor_mastery >= 6: Закалка."""
    return has_milestone(player, "armor_mastery", 6)


def has_unbreakable(player: dict) -> bool:
    """armor_mastery >= 10: Непоколебимый."""
    return has_milestone(player, "armor_mastery", 10)


# ---------------------------------------------------------------------------
# Вехи пиромантии (pyromancy)
# ---------------------------------------------------------------------------


def has_intense_heat(player: dict) -> bool:
    """pyromancy >= 3: Интенсивный жар."""
    return has_milestone(player, "pyromancy", 3)


def has_concentration(player: dict) -> bool:
    """pyromancy >= 6: Концентрация."""
    return has_milestone(player, "pyromancy", 6)


def has_elemental_breakthrough(player: dict) -> bool:
    """pyromancy >= 10: Прорыв стихий."""
    return has_milestone(player, "pyromancy", 10)


# ---------------------------------------------------------------------------
# Вехи восстановления (restoration)
# ---------------------------------------------------------------------------


def has_frugality(player: dict) -> bool:
    """restoration >= 3: Экономия."""
    return has_milestone(player, "restoration", 3)


def has_sturdy_barrier(player: dict) -> bool:
    """restoration >= 6: Прочный барьер."""
    return has_milestone(player, "restoration", 6)


def has_second_wind(player: dict) -> bool:
    """restoration >= 10: Второй ветер."""
    return has_milestone(player, "restoration", 10)


# ---------------------------------------------------------------------------
# Вехи порчи (hexes)
# ---------------------------------------------------------------------------


def has_caustic_toxins(player: dict) -> bool:
    """hexes >= 3: Едкие токсины."""
    return has_milestone(player, "hexes", 3)


def has_withering(player: dict) -> bool:
    """hexes >= 6: Иссушение."""
    return has_milestone(player, "hexes", 6)


def has_soul_harvest(player: dict) -> bool:
    """hexes >= 10: Жатва душ."""
    return has_milestone(player, "hexes", 10)


# ---------------------------------------------------------------------------
# Вехи алхимии (alchemy)
# ---------------------------------------------------------------------------


def has_herbalist(player: dict) -> bool:
    """alchemy >= 3: Травник."""
    return has_milestone(player, "alchemy", 3)


def has_thrifty_alchemist(player: dict) -> bool:
    """alchemy >= 6: Рачительный алхимик."""
    return has_milestone(player, "alchemy", 6)


def has_double_dose(player: dict) -> bool:
    """alchemy >= 10: Двойная доза."""
    return has_milestone(player, "alchemy", 10)


# ---------------------------------------------------------------------------
# Вехи ремесла (crafting)
# ---------------------------------------------------------------------------


def has_field_sharpening(player: dict) -> bool:
    """crafting >= 3: Полевая заточка."""
    return has_milestone(player, "crafting", 3)


def has_repair_master(player: dict) -> bool:
    """crafting >= 6: Мастер ремонта."""
    return has_milestone(player, "crafting", 6)


def has_reinforcement(player: dict) -> bool:
    """crafting >= 10: Укрепление."""
    return has_milestone(player, "crafting", 10)


# ---------------------------------------------------------------------------
# Вехи выживания (scavenging)
# ---------------------------------------------------------------------------


def has_keen_eye(player: dict) -> bool:
    """scavenging >= 3: Проницательный глаз."""
    return has_milestone(player, "scavenging", 3)


def has_tight_belt(player: dict) -> bool:
    """scavenging >= 6: Крепкий пояс."""
    return has_milestone(player, "scavenging", 6)


def has_treasure_sense(player: dict) -> bool:
    """scavenging >= 10: Чувство сокровищ."""
    return has_milestone(player, "scavenging", 10)
