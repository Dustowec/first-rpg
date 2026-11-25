"""Блок 5.3: тонкий презентационный слой CLI (§§ 33.1–33.2, § 34.1).

Никакой игровой логики: экран — чистая функция от state, ввод — цифра + Enter,
любая команда уходит в engine.controller.dispatch_command.
Скрытые числа (hidden: true и статы монстров) не выводятся никогда.
"""

from __future__ import annotations

import random
from collections import deque
from typing import Any, Callable

from engine import crafting, magic
from engine.constants import DEFAULT_SESSION_PATH, DEFAULT_TEMPLATE_PATH
from engine.controller import dispatch_command
from engine.data_loader import GameData
from engine.trade import VILLAGE_NPCS, get_buy_price, get_sell_price
from engine.world_time import get_hunger_deadlines

BAR_WIDTH = 10
JOURNAL_LIMIT = 6


# ---------------------------------------------------------------------------
# A. Утилиты вывода
# ---------------------------------------------------------------------------

def t(game_data: GameData, key: str, default: str = "", **kwargs: Any) -> str:
    """Строка из strings_ru.json с подстановкой; default — если ключа нет."""
    text = game_data.strings.get(key, default)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def hp_bar(current: int, maximum: int, width: int = BAR_WIDTH) -> str:
    """Полоса здоровья [HP ######----] — без чисел (§ 33.2)."""
    maximum = max(1, int(maximum))
    filled = int(round(max(0, min(current, maximum)) / maximum * width))
    filled = max(0, min(width, filled))
    return "[HP " + "#" * filled + "-" * (width - filled) + "]"


def is_hidden(block: Any) -> bool:
    """True, если блок статов помечен hidden: true."""
    return isinstance(block, dict) and block.get("hidden") is True


def item_name(game_data: GameData, item_id: str) -> str:
    try:
        return game_data.get_item(item_id).get("name", {}).get("ru", item_id)
    except KeyError:
        return item_id


def monster_name(game_data: GameData, mob_id: str) -> str:
    try:
        return game_data.get_monster(mob_id).get("name", {}).get("ru", mob_id)
    except KeyError:
        return mob_id


def npc_name(game_data: GameData, npc_id: str) -> str:
    return game_data.npcs.get(npc_id, {}).get("name", {}).get("ru", npc_id)


def current_node(state: dict) -> dict | None:
    map_data = state.get("map", {})
    for node in map_data.get("nodes", []):
        if node.get("id") == map_data.get("currentNodeId"):
            return node
    return None


def node_by_id(state: dict, node_id: str) -> dict | None:
    for node in state.get("map", {}).get("nodes", []):
        if node.get("id") == node_id:
            return node
    return None


def danger_word(game_data: GameData, danger: int) -> str:
    key = {0: "danger_safe", 1: "danger_low", 2: "danger_medium"}.get(danger, "danger_high")
    default = {0: "безопасно", 1: "низкая", 2: "средняя"}.get(danger, "высокая")
    return t(game_data, key, default)


def hunger_status(state: dict) -> str:
    """Окно голода для статус-строки (7/17 или 9/19 при перке «Тугий пояс»)."""
    player = state.get("player", {})
    world = state.get("world", {})
    morning, evening = get_hunger_deadlines(player)
    step = world.get("stepOfDay", 1)
    if not world.get("fedMorning") and step < morning:
        return f"завтрак: поесть до шага {morning}!"
    if step >= 10 and not world.get("fedEvening") and step < evening:
        return f"ужин: поесть до шага {evening}!"
    return "сыт"


def render_status_line(state: dict, game_data: GameData) -> str:
    """Неизменная первая строка любого экрана (§ 33.1)."""
    player = state.get("player", {})
    world = state.get("world", {})
    hp = player.get("resources", {}).get("hp", {})
    mp = player.get("resources", {}).get("mp", {})
    return (
        f"ДЕНЬ {world.get('day', 1)} · ШАГ {world.get('stepOfDay', 1)}/20 · "
        f"HP {hp.get('current', 0)}/{hp.get('max', 0)} · "
        f"MP {mp.get('current', 0)}/{mp.get('max', 0)} · "
        f"ЗОЛОТО {player.get('gold', 0)} · [{hunger_status(state)}]"
    )


# ---------------------------------------------------------------------------
# Б. Журнал событий
# ---------------------------------------------------------------------------

def event_text(event: dict, game_data: GameData) -> str:
    """Переводит событие ядра в строку журнала."""
    eid = event.get("id", "")
    if eid == "npc_spoke":
        return f"{npc_name(game_data, event.get('npcId', ''))}: {event.get('npcReply', '')}"
    if eid == "scavenge_found":
        return t(game_data, "search_found", "Найдено: {item}", item=item_name(game_data, event.get("itemId", "")))
    if eid == "scavenge_nothing":
        return t(game_data, "search_empty", "Ничего не найдено.")
    if eid == "moved_to_node":
        name = event.get("name") or event.get("nodeName") or event.get("nodeId", "")
        return t(game_data, "journal_moved", "Переход: {name}", name=name)
    if eid == "look_found_monster":
        return t(game_data, "journal_monster_seen", "Замечен {enemy}!", enemy=monster_name(game_data, event.get("mobId", "")))
    if eid == "look_clear":
        return t(game_data, "journal_look_clear", "Вокруг тихо.")
    if eid == "ambush_triggered":
        return t(game_data, "journal_ambush", "Засада! {enemy} нападает!", enemy=monster_name(game_data, event.get("mobId", "")))
    if eid == "attack_hit":
        return t(game_data, "battle_attack_hit", "Вы попали по {enemy}: {damage} урона.",
                 enemy=monster_name(game_data, event.get("mobId", "")), damage=event.get("damage", 0))
    if eid == "attack_miss":
        return t(game_data, "battle_attack_miss", "Вы промахнулись.")
    if eid == "combat_victory":
        return t(game_data, "journal_victory", "Победа! Локация зачищена.")
    if eid == "lair_next_monster":
        return t(game_data, "journal_lair_next", "Из логова выходит {enemy}!", enemy=monster_name(game_data, event.get("mobId", "")))
    if eid == "xp_gained":
        return t(game_data, "status_xp_gained", "Получено {amount} опыта.", amount=event.get("amount", 0))
    if eid == "gold_gained":
        return t(game_data, "journal_gold", "Получено {amount} золота.", amount=event.get("amount", 0))
    if eid == "level_up":
        return t(game_data, "status_level_up", "Новый уровень: {level}!", level=event.get("level", 0))
    if eid == "item_added":
        return t(game_data, "journal_item_added", "Получено: {item} ({count})",
                 item=item_name(game_data, event.get("itemId", "")), count=event.get("count", 1))
    if eid == "item_removed":
        return t(game_data, "journal_item_removed", "Потрачено: {item} ({count})",
                 item=item_name(game_data, event.get("itemId", "")), count=event.get("count", 1))
    if eid == "item_bought":
        return t(game_data, "trade_success", "Сделка совершена!")
    if eid == "item_sold":
        return t(game_data, "journal_sold", "Продано: {item} за {gold} зол.",
                 item=item_name(game_data, event.get("itemId", "")), gold=event.get("goldEarned", 0))
    if eid == "barter_completed":
        offer = event.get("offer", {})
        return t(game_data, "journal_barter", "Обмен: {take} -> {give}",
                 take=item_name(game_data, offer.get("takeItemId", "")), give=item_name(game_data, offer.get("giveItemId", "")))
    if eid == "dialogue_barter_offered":
        offer = event.get("offer", {})
        return t(game_data, "journal_barter_offer", "Предложен обмен: {give} за {take} ({gold} зол.)",
                 give=item_name(game_data, offer.get("giveItemId", "")),
                 take=item_name(game_data, offer.get("takeItemId", "")), gold=offer.get("goldDelta", 0))
    if eid == "dialogue_discount_granted":
        return t(game_data, "journal_discount", "Скидка {percent}% на следующую покупку!", percent=event.get("discountPercent", 10))
    if eid == "dialogue_hint_given":
        return t(game_data, "journal_hint", "Новая подсказка: {target}", target=event.get("targetId", ""))
    if eid == "dialogue_reputation_changed":
        return t(game_data, "journal_reputation", "Отношение {npc}: {reputation}",
                 npc=npc_name(game_data, event.get("npcId", "")), reputation=event.get("reputation", ""))
    if eid == "dialogue_action_ignored":
        return t(game_data, "journal_action_ignored", "NPC не может этого сделать.")
    if eid == "hunger_satisfied":
        return t(game_data, "journal_fed", "Вы поели.")
    if eid == "inn_rested":
        return t(game_data, "journal_rested", "Вы переночевали в харчевне.")
    if eid == "crafted_item":
        return t(game_data, "journal_crafted", "Создано: {item}", item=item_name(game_data, event.get("itemId", "")))
    if eid == "smith_repaired":
        return t(game_data, "repair_done", "Отремонтировано на {amount}.", amount=event.get("amount", 0))
    if eid == "weapon_sharpened":
        return t(game_data, "journal_sharpened", "Оружие заточено.")
    if eid == "region_changed":
        return t(game_data, "journal_region", "Дальние тропы: регион {region}", region=event.get("region", 0))
    if eid == "player_died":
        return t(game_data, "journal_death", "Вы погибли...")
    if eid == "session_reset_permadeath":
        return t(game_data, "journal_permadeath", "Сессия сброшена. Новая игра.")
    if eid == "llm_fallback_used":
        return t(game_data, "journal_llm_fallback", "NPC отвечает заготовленной репликой.")
    if eid == "waited_one_step":
        return t(game_data, "journal_waited", "Прошёл один шаг времени.")
    if eid.startswith("err_"):
        return t(game_data, eid, t(game_data, "system_invalid_input", "Действие невозможно."))
    return t(game_data, eid, eid)


def render_journal(events: list[dict], game_data: GameData, limit: int = JOURNAL_LIMIT) -> list[str]:
    if not events:
        return []
    return ["Журнал: " + " · ".join(event_text(e, game_data) for e in list(events)[-limit:])]


def render_menu(menu: list[dict]) -> list[str]:
    """Строки меню вида [1] Текст."""
    return ["  ".join(f"[{item['key']}] {item['label']}" for item in menu)]


# ---------------------------------------------------------------------------
# В. Меню (номер -> команда ядра)
# ---------------------------------------------------------------------------

def build_explore_menu(state: dict, game_data: GameData) -> list[dict]:
    node = current_node(state) or {}
    monster = node.get("state", {}).get("monster")
    menu = [
        {"key": "1", "label": "Осмотреться (1 AP)", "command": {"type": "look"}},
        {"key": "2", "label": "Поиск (1 AP)", "command": {"type": "search"}},
    ]
    if monster and monster.get("revealed"):
        menu.append({"key": "3", "label": "В бой (1 AP)", "command": {"type": "start_combat"}})
    menu += [
        {"key": "4", "label": "Инвентарь/Еда", "screen": "inventory"},
        {"key": "5", "label": "Персонаж", "screen": "character"},
        {"key": "6", "label": "Карта", "screen": "map"},
        {"key": "7", "label": "Крафт/Заточка", "screen": "craft"},
    ]
    if node.get("type") in ("village", "camp"):
        menu.append({"key": "8", "label": "NPC/Сервисы", "screen": "village"})
    elif node.get("type") == "lair" and not monster:
        menu.append({"key": "8", "label": "Дальние тропы", "command": {"type": "travel_next_region"}})
    menu += [
        {"key": "9", "label": "Ждать (1 AP)", "command": {"type": "wait"}},
        {"key": "0", "label": "Выходы/Меню", "screen": "exits"},
    ]
    return menu


def build_exits_menu(state: dict, game_data: GameData) -> list[dict]:
    node = current_node(state) or {}
    menu = []
    for index, node_id in enumerate(node.get("connections", [])[:9], start=1):
        target = node_by_id(state, node_id) or {}
        menu.append({"key": str(index), "label": f"{target.get('name', node_id)} (1 AP)",
                     "command": {"type": "move", "targetNodeId": node_id}})
    menu += [{"key": "9", "label": "Выход из игры", "action": "quit"},
             {"key": "0", "label": "Назад", "action": "back"}]
    return menu


def build_combat_menu(state: dict, game_data: GameData) -> list[dict]:
    menu = [
        {"key": "1", "label": "Ударить", "command": {"type": "combat_attack"}},
        {"key": "2", "label": "Заклинание", "screen": "spells"},
        {"key": "3", "label": "Расходник", "screen": "consumables"},
        {"key": "4", "label": "Отступить (шанс 50%)", "command": {"type": "combat_retreat"}},
    ]
    if magic.can_use_crushing_strike(state):
        menu.append({"key": "5", "label": "Сокрушение", "command": {"type": "combat_attack", "useCrushingStrike": True}})
    return menu


def build_spells_menu(state: dict, game_data: GameData) -> list[dict]:
    menu = []
    player = state.get("player", {})
    for index, spell in enumerate(magic.get_available_spells(player, game_data)[:9], start=1):
        cost = magic.get_spell_mp_cost(player, spell)
        menu.append({"key": str(index), "label": f"{spell.get('name', {}).get('ru', spell.get('id'))} ({cost} MP)",
                     "command": {"type": "combat_spell", "spellId": spell.get("id")}})
    menu.append({"key": "0", "label": "Назад", "action": "back"})
    return menu


def build_consumables_menu(state: dict, game_data: GameData) -> list[dict]:
    menu = []
    index = 1
    for entry in state.get("player", {}).get("inventory", []):
        try:
            item_def = game_data.get_item(entry.get("itemId", ""))
        except KeyError:
            continue
        if item_def.get("category") != "consumable" or index > 9:
            continue
        menu.append({"key": str(index), "label": f"{item_def.get('name', {}).get('ru', entry['itemId'])} ({entry.get('count', 1)})",
                     "command": {"type": "combat_item", "itemId": entry["itemId"]}})
        index += 1
    menu.append({"key": "0", "label": "Назад", "action": "back"})
    return menu


def build_inventory_menu(state: dict, game_data: GameData) -> list[dict]:
    menu = []
    index = 1
    for entry in state.get("player", {}).get("inventory", []):
        if index > 8:
            break
        item_id = entry.get("itemId", "")
        try:
            item_def = game_data.get_item(item_id)
        except KeyError:
            continue
        category = item_def.get("category")
        label = f"{item_def.get('name', {}).get('ru', item_id)} ({entry.get('count', 1)})"
        if category == "food":
            command = {"type": "eat", "itemId": item_id}
            label += " — съесть"
        elif category == "consumable":
            command = {"type": "use_item", "itemId": item_id}
            label += " — выпить"
        elif category in ("weapon", "armor"):
            command = {"type": "equip", "itemId": item_id}
            label += " — надеть"
        elif category == "repair_kit":
            command = {"type": "use_item", "itemId": item_id, "slot": "weapon"}
            label += " — ремонт"
        else:
            command = {"type": "noop"}
        menu.append({"key": str(index), "label": label, "command": command})
        index += 1
    menu += [{"key": "9", "label": "Снять оружие", "command": {"type": "unequip", "slot": "weapon"}},
             {"key": "0", "label": "Назад", "action": "back"}]
    return menu


def build_character_menu(state: dict, game_data: GameData) -> list[dict]:
    player = state.get("player", {})
    menu = []
    if player.get("unspentPoints", {}).get("attributes", 0) > 0:
        for index, attr in enumerate(player.get("attributes", {}), start=1):
            menu.append({"key": str(index), "label": f"+1 {t(game_data, 'attr_' + attr, attr)}",
                         "command": {"type": "allocate_attribute", "attribute": attr}})
    elif player.get("unspentPoints", {}).get("skills", 0) > 0:
        for index, skill in enumerate(list(player.get("skills", {}))[:9], start=1):
            menu.append({"key": str(index), "label": f"+1 {t(game_data, 'skill_' + skill, skill)}",
                         "command": {"type": "allocate_skill", "skill": skill}})
    menu.append({"key": "0", "label": "Назад", "action": "back"})
    return menu


def build_creation_menu(state: dict, game_data: GameData) -> list[dict]:
    player = state.get("player", {})
    menu = []
    if player.get("unspentPoints", {}).get("attributes", 0) > 0:
        for index, attr in enumerate(player.get("attributes", {}), start=1):
            # лимит создания: не более +2 сверх базовой единицы (§ 9.1)
            if player["attributes"][attr] >= 3:
                continue
            menu.append({"key": str(index), "label": f"+1 {t(game_data, 'attr_' + attr, attr)}",
                         "command": {"type": "allocate_attribute", "attribute": attr, "isCreation": True}})
    menu.append({"key": "0", "label": "Пропустить" if menu else "Начать игру", "action": "skip_creation"})
    return menu


def build_craft_menu(state: dict, game_data: GameData) -> list[dict]:
    menu = []
    for index, recipe in enumerate(crafting.get_available_recipes(state, game_data)[:8], start=1):
        menu.append({"key": str(index), "label": f"{recipe.get('name', {}).get('ru', recipe.get('id'))} (1 AP)",
                     "command": {"type": "craft", "recipeId": recipe.get("id")}})
    menu += [{"key": "9", "label": "Полевая заточка (1 AP)", "command": {"type": "field_sharpen"}},
             {"key": "0", "label": "Назад", "action": "back"}]
    return menu


def build_village_menu(state: dict, game_data: GameData) -> list[dict]:
    node = current_node(state) or {}
    present = [node.get("npcId")] if node.get("type") == "camp" and node.get("npcId") else (
        list(VILLAGE_NPCS) if node.get("type") == "village" else [])
    menu = []
    for index, npc_id in enumerate(present[:6], start=1):
        menu.append({"key": str(index), "label": npc_name(game_data, npc_id), "screen": "dialogue", "npcId": npc_id})
    key = len(menu) + 1
    if node.get("type") == "village":
        menu += [
            {"key": str(key), "label": "Ночлег (5 зол.)", "command": {"type": "inn_rest"}},
            {"key": str(key + 1), "label": "Ремонт оружия у кузнеца", "command": {"type": "smith_repair", "slot": "weapon"}},
            {"key": str(key + 2), "label": "Ремонт брони у кузнеца", "command": {"type": "smith_repair", "slot": "armor"}},
        ]
    menu.append({"key": "0", "label": "Назад", "action": "back"})
    return menu


def build_dialogue_menu(state: dict, npc_id: str, game_data: GameData) -> list[dict]:
    entry = state.get("npcs", {}).get(npc_id, {})
    menu = []
    for index, reply in enumerate(entry.get("lastSuggestedReplies", [])[:3], start=1):
        menu.append({"key": str(index), "label": reply,
                     "command": {"type": "talk_npc", "npcId": npc_id, "playerInput": reply}})
    menu.append({"key": "4", "label": "Ввести свою фразу", "action": "custom_phrase", "npcId": npc_id})
    if entry.get("pendingBarter"):
        menu.append({"key": "5", "label": "Принять обмен", "command": {"type": "accept_barter", "npcId": npc_id}})
    if "open_trade" in game_data.npcs.get(npc_id, {}).get("actionWhitelist", []):
        menu += [{"key": "6", "label": "Купить", "screen": "trade_buy", "npcId": npc_id},
                 {"key": "7", "label": "Продать", "screen": "trade_sell", "npcId": npc_id}]
    menu.append({"key": "0", "label": "Закончить разговор", "action": "end_dialogue", "npcId": npc_id})
    return menu


def build_trade_menu(state: dict, npc_id: str, game_data: GameData, mode: str = "buy") -> list[dict]:
    menu = []
    npc_state = state.get("npcs", {}).get(npc_id, {})
    if mode == "buy":
        for index, item_id in enumerate(game_data.npcs.get(npc_id, {}).get("tradeStock", [])[:9], start=1):
            try:
                item_def = game_data.get_item(item_id)
            except KeyError:
                continue
            menu.append({"key": str(index),
                         "label": f"{item_def.get('name', {}).get('ru', item_id)} — {get_buy_price(item_def, npc_state)} зол.",
                         "command": {"type": "buy_item", "npcId": npc_id, "itemId": item_id, "count": 1}})
    else:
        index = 1
        for entry in state.get("player", {}).get("inventory", []):
            if index > 9:
                break
            try:
                item_def = game_data.get_item(entry.get("itemId", ""))
            except KeyError:
                continue
            price = get_sell_price(item_def, npc_state)
            if price <= 0:
                continue
            menu.append({"key": str(index),
                         "label": f"{item_def.get('name', {}).get('ru', entry['itemId'])} — {price} зол.",
                         "command": {"type": "sell_item", "npcId": npc_id, "itemId": entry["itemId"], "count": 1}})
            index += 1
    menu.append({"key": "0", "label": "Назад", "action": "back"})
    return menu


# ---------------------------------------------------------------------------
# Г. Экраны (чистые функции от state)
# ---------------------------------------------------------------------------

def render_combat_body(state: dict, game_data: GameData) -> str:
    """Тело боевого экрана: только имена и полосы, никаких скрытых чисел."""
    combat_state = state.get("world", {}).get("activeCombat") or {}
    mob = combat_state.get("monster", {})
    hp = state.get("player", {}).get("resources", {}).get("hp", {})
    weapon = state.get("player", {}).get("equipment", {}).get("weapon", {})
    durability = weapon.get("durability", {})
    return "\n".join([
        f"БОЙ · {monster_name(game_data, mob.get('mobId', ''))} {hp_bar(mob.get('hp', 0), mob.get('maxHp', 1))}"
        f" · вы {hp_bar(hp.get('current', 0), hp.get('max', 1))} · раунд {combat_state.get('round', 1)}",
        f"Оружие: {item_name(game_data, weapon.get('itemId', ''))} "
        f"(прочность {durability.get('current', 0)}/{durability.get('max', 0)})",
    ])


def render_combat_screen(state: dict, game_data: GameData, journal: list[dict] | None = None) -> str:
    lines = [render_status_line(state, game_data), render_combat_body(state, game_data)]
    lines += render_journal(journal or [], game_data)
    lines += render_menu(build_combat_menu(state, game_data))
    return "\n".join(lines)


def render_explore_screen(state: dict, game_data: GameData, journal: list[dict] | None = None) -> str:
    node = current_node(state) or {}
    lines = [
        render_status_line(state, game_data),
        f"{node.get('name', '?')} — опасность: {danger_word(game_data, node.get('danger', 0))} "
        f"(выходов: {len(node.get('connections', []))})",
    ]
    monster = node.get("state", {}).get("monster")
    if monster and monster.get("revealed"):
        lines.append(f"Здесь: {monster_name(game_data, monster.get('mobId', ''))} "
                     f"{hp_bar(monster.get('hp', 0), monster.get('maxHp', 1))}")
    lines += render_journal(journal or [], game_data)
    lines += render_menu(build_explore_menu(state, game_data))
    return "\n".join(lines)


def render_exits_screen(state: dict, game_data: GameData) -> str:
    node = current_node(state) or {}
    return "\n".join([render_status_line(state, game_data),
                      f"Выходы из «{node.get('name', '?')}»:"] + render_menu(build_exits_menu(state, game_data)))


def render_inventory_screen(state: dict, game_data: GameData) -> str:
    lines = [render_status_line(state, game_data), t(game_data, "screen_inventory", "--- ИНВЕНТАРЬ ---")]
    if not state.get("player", {}).get("inventory"):
        lines.append(t(game_data, "inventory_empty", "Инвентарь пуст."))
    return "\n".join(lines + render_menu(build_inventory_menu(state, game_data)))


def render_character_screen(state: dict, game_data: GameData) -> str:
    player = state.get("player", {})
    lines = [
        render_status_line(state, game_data),
        t(game_data, "screen_character", "--- ПЕРСОНАЖ ---"),
        f"Уровень {player.get('level', 1)} · опыт {player.get('xp', 0)}",
        "Характеристики: " + ", ".join(f"{t(game_data, 'attr_' + a, a)} {v}" for a, v in player.get("attributes", {}).items()),
        "Навыки: " + ", ".join(f"{t(game_data, 'skill_' + s, s)} {v}" for s, v in player.get("skills", {}).items()),
        f"Нераспределено: характеристики {player.get('unspentPoints', {}).get('attributes', 0)}, "
        f"навыки {player.get('unspentPoints', {}).get('skills', 0)}",
    ]
    return "\n".join(lines + render_menu(build_character_menu(state, game_data)))


def render_map_screen(state: dict, game_data: GameData) -> str:
    map_data = state.get("map", {})
    hints = set(state.get("flags", {}).get("revealedHints", []))
    bestiary = state.get("flags", {}).get("bestiaryUnlocked", [])
    lines = [render_status_line(state, game_data),
             t(game_data, "screen_map", "--- КАРТА ---") + f" (регион {state.get('meta', {}).get('region', 1)})"]
    for node in map_data.get("nodes", []):
        if node.get("state", {}).get("visited"):
            mark = "*" if node.get("id") == map_data.get("currentNodeId") else " "
            lines.append(f"{mark} {node.get('name')} — {danger_word(game_data, node.get('danger', 0))}")
        elif node.get("id") in hints:
            lines.append(f"? {node.get('name')} — метка от NPC")
    if bestiary:
        lines.append("Бестиарий: " + ", ".join(monster_name(game_data, b.get("mobId", "")) for b in bestiary if isinstance(b, dict)))
    return "\n".join(lines + render_menu([{"key": "0", "label": "Назад", "action": "back"}]))


def render_craft_screen(state: dict, game_data: GameData) -> str:
    return "\n".join([render_status_line(state, game_data),
                      t(game_data, "screen_craft", "--- КРАФТ ---")] + render_menu(build_craft_menu(state, game_data)))


def render_village_screen(state: dict, game_data: GameData) -> str:
    return "\n".join([render_status_line(state, game_data),
                      t(game_data, "screen_village", "--- NPC И СЕРВИСЫ ---")] + render_menu(build_village_menu(state, game_data)))


def render_dialogue_screen(state: dict, npc_id: str, game_data: GameData) -> str:
    entry = state.get("npcs", {}).get(npc_id, {})
    lines = [render_status_line(state, game_data),
             f"{npc_name(game_data, npc_id)} · настроение: {entry.get('mood', 'neutral')}"]
    if entry.get("lastReply"):
        lines.append(f"«{entry['lastReply']}»")
    offer = entry.get("pendingBarter")
    if offer:
        lines.append(f"Предложение: {item_name(game_data, offer.get('giveItemId', ''))} "
                     f"за {item_name(game_data, offer.get('takeItemId', ''))} (золото {offer.get('goldDelta', 0):+d})")
    return "\n".join(lines + render_menu(build_dialogue_menu(state, npc_id, game_data)))


def render_trade_screen(state: dict, npc_id: str, game_data: GameData, mode: str = "buy") -> str:
    return "\n".join([render_status_line(state, game_data),
                      f"{npc_name(game_data, npc_id)} · " + ("покупка" if mode == "buy" else "продажа")]
                     + render_menu(build_trade_menu(state, npc_id, game_data, mode)))


def render_creation_screen(state: dict, game_data: GameData, journal: list[dict] | None = None) -> str:
    player = state.get("player", {})
    left = player.get("unspentPoints", {}).get("attributes", 0)
    lines = [render_status_line(state, game_data),
             t(game_data, "screen_creation", "Распределите 3 стартовых очка (не более +2 в характеристику):"),
             f"Осталось очков: {left}",
             "Текущие: " + ", ".join(f"{t(game_data, 'attr_' + a, a)} {v}" for a, v in player.get("attributes", {}).items())]
    lines += render_journal(journal or [], game_data)
    return "\n".join(lines + render_menu(build_creation_menu(state, game_data)))


def render_death_screen(state: dict, game_data: GameData) -> str:
    return "\n".join([t(game_data, "system_death_message", "Вы погибли."),
                      t(game_data, "journal_permadeath", "Сессия сброшена. Новая игра.")])


SCREENS = {
    "explore": render_explore_screen, "combat": render_combat_screen, "exits": render_exits_screen,
    "inventory": render_inventory_screen, "character": render_character_screen, "map": render_map_screen,
    "craft": render_craft_screen, "village": render_village_screen, "creation": render_creation_screen,
}


def menu_for_screen(screen: str, state: dict, game_data: GameData, npc_id: str | None = None) -> list[dict]:
    """Меню активного экрана (единая точка для тестов и цикла ввода)."""
    builders = {
        "combat": build_combat_menu, "exits": build_exits_menu, "inventory": build_inventory_menu,
        "character": build_character_menu, "craft": build_craft_menu, "village": build_village_menu,
        "creation": build_creation_menu, "spells": build_spells_menu, "consumables": build_consumables_menu,
    }
    if screen in builders:
        return builders[screen](state, game_data)
    if screen == "dialogue":
        return build_dialogue_menu(state, npc_id or "", game_data)
    if screen in ("trade_buy", "trade_sell"):
        return build_trade_menu(state, npc_id or "", game_data, "buy" if screen == "trade_buy" else "sell")
    if screen == "map":
        return [{"key": "0", "label": "Назад", "action": "back"}]
    return build_explore_menu(state, game_data)


def render_screen(screen: str, state: dict, game_data: GameData,
                  journal: list[dict] | None = None, npc_id: str | None = None) -> str:
    """Рендер любого экрана по имени."""
    if screen == "dialogue":
        return render_dialogue_screen(state, npc_id or "", game_data)
    if screen in ("trade_buy", "trade_sell"):
        return render_trade_screen(state, npc_id or "", game_data, "buy" if screen == "trade_buy" else "sell")
    if screen in ("spells", "consumables"):
        return "\n".join([render_status_line(state, game_data)] + render_menu(menu_for_screen(screen, state, game_data, npc_id)))
    renderer = SCREENS.get(screen, render_explore_screen)
    if renderer in (render_explore_screen, render_combat_screen):
        return renderer(state, game_data, journal)
    return renderer(state, game_data)


# ---------------------------------------------------------------------------
# Д. Главный цикл ввода (одна цифра + Enter)
# ---------------------------------------------------------------------------

def run_cli(
    state: dict,
    game_data: GameData,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
    rng: random.Random | None = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    llm_transport_fn: Callable | None = None,
) -> dict:
    """Цикл CLI. Возвращает финальное state (для тестов и повторного запуска)."""
    journal: deque = deque(maxlen=JOURNAL_LIMIT)
    stack: list[tuple[str, str | None]] = []
    if (state.get("player", {}).get("unspentPoints", {}).get("attributes", 0) == 3
            and state.get("world", {}).get("day") == 1):
        screen, npc_id = "creation", None
    else:
        screen, npc_id = ("combat" if state.get("world", {}).get("inCombat") else "explore"), None

    while True:
        output_fn(render_screen(screen, state, game_data, list(journal), npc_id))
        try:
            raw = input_fn("> ").strip()
        except (EOFError, KeyboardInterrupt, StopIteration):
            break
        choice = next((item for item in menu_for_screen(screen, state, game_data, npc_id) if item["key"] == raw), None)
        if choice is None:
            output_fn(t(game_data, "system_invalid_input", "Введите номер действия."))
            continue

        action = choice.get("action")
        if action == "quit":
            output_fn(t(game_data, "game_quit", "Выход из игры. До свидания!"))
            break
        if action == "back":
            screen, npc_id = stack.pop() if stack else (
                "combat" if state.get("world", {}).get("inCombat") else "explore", None)
            continue
        if action == "skip_creation":
            screen, npc_id = "explore", None
            continue
        if action == "end_dialogue":
            state, events = dispatch_command(state, {"type": "close_dialogue", "npcId": npc_id}, game_data,
                                             rng, session_path, template_path, llm_transport_fn)
            journal.extend(events)
            screen, npc_id = stack.pop() if stack else ("explore", None)
            continue
        if action == "custom_phrase":
            try:
                phrase = input_fn("Ваша фраза: ").strip()
            except (EOFError, KeyboardInterrupt, StopIteration):
                break
            command = {"type": "talk_npc", "npcId": npc_id, "playerInput": phrase}
        elif choice.get("screen"):
            next_screen, next_npc = choice["screen"], choice.get("npcId", npc_id)
            if next_screen == "dialogue":
                state, events = dispatch_command(state, {"type": "open_dialogue", "npcId": next_npc}, game_data,
                                                 rng, session_path, template_path, llm_transport_fn)
                journal.extend(events)
                for event in events:
                    if event.get("id") == "npc_spoke":
                        entry = state.setdefault("npcs", {}).setdefault(next_npc, {})
                        entry["lastSuggestedReplies"] = event.get("suggestedReplies", [])
                        entry["lastReply"] = event.get("npcReply", "")
            stack.append((screen, npc_id))
            screen, npc_id = next_screen, next_npc
            continue
        else:
            command = choice.get("command") or {"type": "noop"}

        if command.get("type") == "noop":
            continue

        state, events = dispatch_command(state, command, game_data, rng, session_path, template_path, llm_transport_fn)
        journal.extend(events)

        # --- Очки кончились — стартовый экран закрывается сам ---
        if screen == "creation" and state.get("player", {}).get("unspentPoints", {}).get("attributes", 0) == 0:
            stack.clear()
            screen, npc_id = "explore", None
            continue

        for event in events:
            if event.get("id") == "npc_spoke" and npc_id:
                entry = state.setdefault("npcs", {}).setdefault(npc_id, {})
                entry["lastSuggestedReplies"] = event.get("suggestedReplies", [])
                entry["lastReply"] = event.get("npcReply", "")

        if any(e.get("id") == "player_died" for e in events):
            output_fn(render_death_screen(state, game_data))
            stack.clear()
            screen, npc_id = "explore", None
            continue

        if command.get("type") == "move" and not any(str(e.get("id", "")).startswith("err_") for e in events):
            stack.clear()
            screen, npc_id = "explore", None

        if state.get("world", {}).get("inCombat"):
            if screen not in ("combat", "spells", "consumables"):
                stack.clear()
                screen, npc_id = "combat", None
        elif screen in ("combat", "spells", "consumables"):
            stack.clear()
            screen, npc_id = "explore", None

    return state