"""Модуль торговли и взаимодействия с сервисами NPC.

Реализует правила §7.1, §16.2, §26.2, §31 и канон #2 (§35) спеки.
Все функции — чистые: принимают state: dict, возвращают (new_state, events).
Не используют print()/input()/global random.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from .constants import DEFAULT_SESSION_PATH, DEFAULT_TEMPLATE_PATH
from .data_loader import GameData
from .inventory import add_item, remove_item


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

REPUTATION_LEVELS: tuple[str, ...] = (
    "hated",
    "hostile",
    "neutral",
    "friendly",
    "honored",
)

# Все 5 деревенских NPC
VILLAGE_NPCS: tuple[str, ...] = (
    "npc_elder_miroslav",
    "npc_merchant_ganna",
    "npc_blacksmith_kolm",
    "npc_innkeeper_boris",
    "npc_herbalist_vela",
)

# NPC, которые покупают предметы (скупщики)
BUYERS: tuple[str, ...] = (
    "npc_merchant_ganna",
    "npc_blacksmith_kolm",
    "npc_herbalist_vela",
    "npc_innkeeper_boris",
    "npc_hunter_rask",
)


# ---------------------------------------------------------------------------
# A. Вспомогательные функции репутации и присутствия
# ---------------------------------------------------------------------------


def shift_reputation(state: dict, npc_id: str, delta: int) -> str:
    """Сдвигает индекс репутации NPC с клампом в [0, 4].

    Modifies state in-place.

    Args:
        state: Текущее состояние игры.
        npc_id: ID NPC.
        delta: Сдвиг (положительный = лучше, отрицательный = хуже).

    Returns:
        Новый уровень репутации (строка).
    """
    npcs = state.get("npcs", {})
    npc_data = npcs.get(npc_id, {})
    current_rep = npc_data.get("reputation", "neutral")

    try:
        current_idx = REPUTATION_LEVELS.index(current_rep)
    except ValueError:
        current_idx = 2  # default to "neutral"

    new_idx = max(0, min(len(REPUTATION_LEVELS) - 1, current_idx + delta))
    new_rep = REPUTATION_LEVELS[new_idx]

    if npc_id not in npcs:
        npcs[npc_id] = {}
    npcs[npc_id]["reputation"] = new_rep
    state["npcs"] = npcs

    return new_rep


def is_npc_present(state: dict, npc_id: str) -> bool:
    """Проверяет доступность NPC в текущей локации.

    Args:
        state: Текущее состояние игры.
        npc_id: ID NPC для проверки.

    Returns:
        True если NPC присутствует, False иначе.
    """
    map_data = state.get("map", {})
    current_node_id = map_data.get("currentNodeId")
    nodes = map_data.get("nodes", [])

    current_node = None
    for node in nodes:
        if node["id"] == current_node_id:
            current_node = node
            break

    if current_node is None:
        return False

    node_type = current_node.get("type")

    if node_type == "village":
        return npc_id in VILLAGE_NPCS

    if node_type == "camp":
        camp_npc_id = current_node.get("npcId")
        return npc_id == camp_npc_id

    # В остальных узлах NPC отсутствуют
    return False


def _get_npc_reputation(state: dict, npc_id: str) -> str:
    """Возвращает текущий уровень репутации NPC."""
    npcs = state.get("npcs", {})
    npc_data = npcs.get(npc_id, {})
    return npc_data.get("reputation", "neutral")


# ---------------------------------------------------------------------------
# B. Расчёт цен покупки и продажи
# ---------------------------------------------------------------------------


def get_buy_price(
    item_data: dict,
    npc_state: dict,
    world_flags: dict | None = None,
) -> int:
    """Рассчитывает цену покупки предмета у NPC.

    Args:
        item_data: Данные предмета (из game_data).
        npc_state: Состояние NPC (включая reputation).
        world_flags: Глобальные флаги мира (для tempDiscount10).

    Returns:
        Итоговая цена покупки (int).
    """
    economy = item_data.get("economy", {})
    base_buy = economy.get("buyPrice", 0)

    if base_buy <= 0:
        return 0

    # Модификатор репутации
    reputation = npc_state.get("reputation", "neutral")
    if reputation == "friendly":
        mult = 0.95
    elif reputation == "honored":
        mult = 0.90
    else:
        mult = 1.0

    # Временная диалоговая скидка 10%
    if world_flags and world_flags.get("tempDiscount10") is True:
        mult *= 0.90
    elif npc_state.get("tempDiscount10") is True:
        mult *= 0.90

    return max(1, round(base_buy * mult))


def get_sell_price(item_data: dict, npc_state: dict) -> int:
    """Рассчитывает цену продажи предмета NPC.

    Args:
        item_data: Данные предмета (из game_data).
        npc_state: Состояние NPC (включая reputation).

    Returns:
        Итоговая цена продажи (int).
    """
    economy = item_data.get("economy", {})
    base_sell = economy.get("sellPrice", 0)

    if base_sell <= 0:
        return 0

    # Модификатор репутации
    reputation = npc_state.get("reputation", "neutral")
    if reputation == "honored":
        mult = 1.05
    else:
        mult = 1.0

    return max(1, round(base_sell * mult))


# ---------------------------------------------------------------------------
# C. Покупка предмета у NPC
# ---------------------------------------------------------------------------


def buy_item(
    state: dict,
    npc_id: str,
    item_id: str,
    count: int,
    game_data: GameData,
) -> tuple[dict, list[dict]]:
    """Покупает предмет у NPC без траты AP.

    Args:
        state: Текущее состояние игры.
        npc_id: ID NPC-продавца.
        item_id: ID покупаемого предмета.
        count: Количество единиц.
        game_data: Загруженные данные игры.

    Returns:
        (new_state, events) — новое состояние и список событий.
    """
    new_state = copy.deepcopy(state)
    player = new_state["player"]
    world = new_state["world"]
    events: list[dict] = []

    # --- Валидация ---

    # Проверка боя
    if world.get("inCombat") is True:
        return new_state, [{"id": "err_in_combat"}]

    # Проверка количества
    if count < 1:
        return new_state, [{"id": "err_invalid_count"}]

    # Проверка присутствия NPC
    if not is_npc_present(new_state, npc_id):
        return new_state, [{"id": "err_npc_not_here"}]

    # Загрузка профиля NPC
    try:
        npc_profile = game_data.get_npc(npc_id)
    except KeyError:
        return new_state, [{"id": "err_npc_not_found"}]

    # Проверка репутации
    reputation = _get_npc_reputation(new_state, npc_id)
    if reputation in ("hated", "hostile"):
        return new_state, [{"id": "err_npc_refuses_trade", "reason": reputation}]

    # Проверка ассортимента NPC
    trade_stock = npc_profile.get("tradeStock", [])
    if item_id not in trade_stock:
        return new_state, [{"id": "err_item_not_sold_by_npc"}]

    # Проверка canBuy
    try:
        item_data = game_data.get_item(item_id)
    except KeyError:
        return new_state, [{"id": "err_item_not_found", "itemId": item_id}]

    if not item_data.get("economy", {}).get("canBuy", False):
        return new_state, [{"id": "err_item_not_sold_by_npc"}]

    # Расчёт цены
    npc_state = new_state.get("npcs", {}).get(npc_id, {})
    unit_price = get_buy_price(item_data, npc_state)
    total_cost = unit_price * count

    # Проверка золота
    if player["gold"] < total_cost:
        return new_state, [
            {
                "id": "err_not_enough_gold",
                "required": total_cost,
                "current": player["gold"],
            }
        ]

    # --- Исполнение сделки ---

    # Списываем золото
    player["gold"] -= total_cost

    # Добавляем предмет в инвентарь
    new_state, _ = add_item(new_state, item_id, count, game_data=game_data)
    player = new_state["player"]

    # Сбрасываем временную скидку, если была активна
    npcs = new_state.get("npcs", {})
    npc_data = npcs.get(npc_id, {})
    if npc_data.get("tempDiscount10") is True:
        npc_data["tempDiscount10"] = False
        npcs[npc_id] = npc_data
        new_state["npcs"] = npcs

    events.append({
        "id": "item_bought",
        "npcId": npc_id,
        "itemId": item_id,
        "count": count,
        "goldSpent": total_cost,
    })

    new_state["player"] = player
    return new_state, events


# ---------------------------------------------------------------------------
# D. Продажа предмета NPC
# ---------------------------------------------------------------------------


def sell_item(
    state: dict,
    npc_id: str,
    item_id: str,
    count: int,
    game_data: GameData,
) -> tuple[dict, list[dict]]:
    """Продаёт предмет NPC без траты AP.

    Args:
        state: Текущее состояние игры.
        npc_id: ID NPC-покупателя.
        item_id: ID продаваемого предмета.
        count: Количество единиц.
        game_data: Загруженные данные игры.

    Returns:
        (new_state, events) — новое состояние и список событий.
    """
    new_state = copy.deepcopy(state)
    player = new_state["player"]
    world = new_state["world"]
    events: list[dict] = []

    # --- Валидация ---

    # Проверка боя
    if world.get("inCombat") is True:
        return new_state, [{"id": "err_in_combat"}]

    # Проверка количества
    if count < 1:
        return new_state, [{"id": "err_invalid_count"}]

    # Проверка присутствия NPC
    if not is_npc_present(new_state, npc_id):
        return new_state, [{"id": "err_npc_not_here"}]

    # Проверка репутации
    reputation = _get_npc_reputation(new_state, npc_id)
    if reputation in ("hated", "hostile"):
        return new_state, [{"id": "err_npc_refuses_trade", "reason": reputation}]

    # Проверка, что NPC является скупщиком
    if npc_id not in BUYERS:
        return new_state, [{"id": "err_npc_not_trader"}]

    # Проверка наличия предмета в инвентаре
    if not _has_item(player, item_id, count):
        return new_state, [{"id": "err_not_enough_items", "itemId": item_id}]

    # Расчёт цены
    try:
        item_data = game_data.get_item(item_id)
    except KeyError:
        return new_state, [{"id": "err_item_not_found", "itemId": item_id}]

    npc_state = new_state.get("npcs", {}).get(npc_id, {})
    unit_price = get_sell_price(item_data, npc_state)
    total_gain = unit_price * count

    # --- Исполнение сделки ---

    # Удаляем предмет из инвентаря
    remove_item(new_state, item_id, count)
    player = new_state["player"]

    # Начисляем золото
    player["gold"] += total_gain

    events.append({
        "id": "item_sold",
        "npcId": npc_id,
        "itemId": item_id,
        "count": count,
        "goldEarned": total_gain,
    })

    new_state["player"] = player
    return new_state, events


# ---------------------------------------------------------------------------
# E. Сервисные обёртки деревни
# ---------------------------------------------------------------------------


def use_smith_repair(
    state: dict,
    slot: str,
    game_data: GameData,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
) -> tuple[dict, list[dict]]:
    """Обёртка для ремонта у кузнеца Колма.

    Args:
        state: Текущее состояние игры.
        slot: Слот экипировки ("weapon" или "armor").
        game_data: Загруженные данные игры.
        session_path: Путь к сессии.
        template_path: Путь к шаблону.

    Returns:
        (new_state, events) — новое состояние и список событий.
    """
    from .inventory import repair_at_smith

    # Проверка присутствия Колма
    if not is_npc_present(state, "npc_blacksmith_kolm"):
        return state, [{"id": "err_npc_not_here"}]

    # Проверка репутации
    reputation = _get_npc_reputation(state, "npc_blacksmith_kolm")
    if reputation == "hated":
        return state, [{"id": "err_npc_refuses_service"}]

    # Делегируем ремонт
    return repair_at_smith(state, slot, game_data)


def use_inn_rest(
    state: dict,
    game_data: GameData,
    rng: "any" | None = None,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
) -> tuple[dict, list[dict]]:
    """Обёртка для ночлега у трактирщика Бориса.

    Args:
        state: Текущее состояние игры.
        game_data: Загруженные данные игры.
        rng: Опциональный генератор случайных чисел.
        session_path: Путь к сессии.
        template_path: Путь к шаблону.

    Returns:
        (new_state, events) — новое состояние и список событий.
    """
    from .world_time import rest_at_inn

    # Проверка присутствия Бориса
    if not is_npc_present(state, "npc_innkeeper_boris"):
        return state, [{"id": "err_npc_not_here"}]

    # Проверка репутации
    reputation = _get_npc_reputation(state, "npc_innkeeper_boris")
    if reputation == "hated":
        return state, [{"id": "err_npc_refuses_service"}]

    # Делегируем ночлег
    return rest_at_inn(
        state, game_data, rng=rng,
        session_path=session_path, template_path=template_path,
    )


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _has_item(player: dict, item_id: str, count: int = 1) -> bool:
    """Проверяет наличие count единиц предмета в инвентаре игрока."""
    total = 0
    for entry in player.get("inventory", []):
        if entry["itemId"] == item_id:
            total += entry.get("count", 0)
    return total >= count
