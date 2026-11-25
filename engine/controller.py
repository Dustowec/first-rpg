"""Блок 5.3: единый диспетчер команд игрового цикла (§§ 32, 33, 34).

Чистое ядро без print()/input(): (state, command, game_data, ...) -> (new_state, events).
После каждого успешного действия — атомарный автосейв (§ 32.2),
при гибели игрока — permadeath-сброс сессии (канон #4).
"""

from __future__ import annotations

import copy
import random
from typing import Any, Callable

from . import combat, consumables, crafting, dialogue, exploration, inventory
from . import llm_client, offline_npc, progression, trade, world_time, worldgen
from .constants import DEFAULT_SESSION_PATH, DEFAULT_TEMPLATE_PATH
from .data_loader import GameData
from .storage import handle_player_death, save_state

# engine/exploration.py ждёт «плоский» словарь списков, а не GameData.
_EXPLORATION_BUCKETS: dict[str, str] = {
    "weapon": "weapons", "armor": "armor", "food": "food", "consumable": "consumables",
    "material": "materials", "junk": "materials", "repair_kit": "materials",
    "monster": "monsters", "biome": "biomes",
}


def exploration_view(game_data: GameData) -> dict[str, list[dict]]:
    """GameData -> dict[str, list[dict]] в формате Блока 4.2."""
    view: dict[str, list[dict]] = {}
    for entity in game_data.entities.values():
        bucket = _EXPLORATION_BUCKETS.get(entity.get("category", ""))
        if bucket is not None:
            view.setdefault(bucket, []).append(entity)
    return view


def _find_slot_index(player: dict, item_id: str) -> int | None:
    for index, entry in enumerate(player.get("inventory", [])):
        if entry.get("itemId") == item_id:
            return index
    return None


def _is_creation_phase(state: dict) -> bool:
    player = state.get("player", {})
    world = state.get("world", {})
    return (player.get("unspentPoints", {}).get("attributes", 0) == 3
            and world.get("day") == 1 and world.get("stepOfDay") == 1)


def _normalize_death_event(event: dict) -> dict:
    """Приводит событие гибели к канону § 32: id=player_died, поле reason.

    Блок 4.2 (exploration.advance_time) возвращает player_death/cause,
    блоки 2.3 и 3.x — player_died/reason. Контроллер унифицирует оба варианта,
    чтобы permadeath-сброс срабатывал для любого источника смерти.
    """
    if event.get("id") in ("player_death", "player_died"):
        normalized = dict(event)
        normalized["id"] = "player_died"
        normalized["reason"] = event.get("reason") or event.get("cause") or "unknown"
        return normalized
    return event


def _route(state, command, game_data, rng, session_path, template_path, llm_transport_fn):
    """Вызывает функцию нужного модуля. Возвращает (new_state, events)."""
    ctype = command.get("type")
    view = exploration_view(game_data)
    paths = {"session_path": session_path, "template_path": template_path}

    # --- Мир и исследование (Блоки 4.1–4.2) ---
    if ctype == "move":
        return exploration.move_to_node(state, command.get("targetNodeId", ""), game_data=view, rng=rng, **paths)
    if ctype == "look":
        return exploration.look_around(state, game_data=view, rng=rng, **paths)
    if ctype == "search":
        return exploration.scavenge_node(state, game_data=view, rng=rng, **paths)
    if ctype == "wait":
        return exploration.wait_step(state, game_data=view, rng=rng, **paths)
    if ctype == "travel_next_region":
        return worldgen.enter_next_region(state, game_data)

    # --- Бой (Блоки 3.1–3.4) ---
    if ctype == "start_combat":
        return combat.start_combat(state, game_data, is_ambush=bool(command.get("isAmbush", False)), rng=rng, **paths)
    if ctype == "combat_attack":
        action = {"type": "crushing_strike" if command.get("useCrushingStrike") else "attack"}
        return combat.combat_step(state, action, game_data, rng=rng, **paths)
    if ctype == "combat_spell":
        return combat.combat_step(state, {"type": "cast", "spellId": command.get("spellId")}, game_data, rng=rng, **paths)
    if ctype == "combat_item":
        return combat.combat_step(state, {"type": "use_item", "itemId": command.get("itemId")}, game_data, rng=rng, **paths)
    if ctype == "combat_retreat":
        return combat.combat_step(state, {"type": "flee"}, game_data, rng=rng, **paths)

    # --- Инвентарь, еда, прокачка (Блоки 2.1–2.3) ---
    if ctype == "eat":
        return world_time.eat_food(state, command.get("itemId", ""), game_data)
    if ctype == "use_item":
        item_id = command.get("itemId", "")
        if state.get("world", {}).get("inCombat"):
            return combat.combat_step(state, {"type": "use_item", "itemId": item_id}, game_data, rng=rng, **paths)
        try:
            item_def = game_data.get_item(item_id)
        except KeyError:
            return state, [{"id": "err_item_not_found", "itemId": item_id}]
        if item_def.get("category") == "repair_kit":
            return inventory.repair_with_kit(state, item_id, command.get("slot", "weapon"), game_data)
        return consumables.use_consumable(state, item_id, game_data, rng=rng)
    if ctype == "equip":
        slot_index = command.get("slotIndex")
        if slot_index is None:
            slot_index = _find_slot_index(state.get("player", {}), command.get("itemId", ""))
        if slot_index is None:
            return state, [{"id": "err_item_not_found", "itemId": command.get("itemId")}]
        return inventory.equip_item(state, int(slot_index), game_data)
    if ctype == "unequip":
        return inventory.unequip_item(state, command.get("slot", "weapon"))
    if ctype == "allocate_attribute":
        is_creation = bool(command.get("isCreation")) or _is_creation_phase(state)
        return progression.allocate_attribute(state, command.get("attribute", ""), is_creation=is_creation)
    if ctype == "allocate_skill":
        return progression.allocate_skill(state, command.get("skill", ""))

    # --- Ремесло и сервисы деревни (Блоки 4.3–4.4) ---
    if ctype == "craft":
        return crafting.craft_recipe(state, command.get("recipeId", ""), game_data, rng=rng, **paths)
    if ctype == "field_sharpen":
        return crafting.sharpen_weapon(state, game_data)
    if ctype == "smith_repair":
        return trade.use_smith_repair(state, command.get("slot", "weapon"), game_data, **paths)
    if ctype == "inn_rest":
        return trade.use_inn_rest(state, game_data, rng=rng, **paths)
    if ctype == "buy_item":
        return trade.buy_item(state, command.get("npcId", ""), command.get("itemId", ""), int(command.get("count", 1)), game_data)
    if ctype == "sell_item":
        return trade.sell_item(state, command.get("npcId", ""), command.get("itemId", ""), int(command.get("count", 1)), game_data)

    # --- Диалоги LLM-NPC (Блоки 5.1–5.2) ---
    if ctype == "close_dialogue":
        npc_id = command.get("npcId", "")
        new_state, _ = dialogue.reset_dialogue_session(state, npc_id)
        events = [{"id": "dialogue_closed", "npcId": npc_id}]
        if new_state.get("npcs", {}).get(npc_id, {}).get("pendingBarter"):
            new_state, decline_events = dialogue.decline_barter_offer(new_state, npc_id)
            events.extend(decline_events)
        return new_state, events
    if ctype == "open_dialogue":
        # Приветствие при входе в диалог: реплика + варианты ответов (§ 33.2)
        npc_id = command.get("npcId", "")
        new_state, events = dialogue.reset_dialogue_session(state, npc_id)
        greeting = offline_npc.get_greeting(npc_id, game_data)
        new_state, spoke = dialogue.process_npc_dialogue(
            new_state, npc_id, "", greeting, game_data, rng=rng
        )
        return new_state, spoke
    if ctype == "talk_npc":
        npc_id = command.get("npcId", "")
        player_input = command.get("playerInput", "")
        response, meta = llm_client.query_npc_llm(state, npc_id, player_input, game_data, transport_fn=llm_transport_fn)
        if meta.get("usedFallback") and offline_npc.has_offline_dialogue(npc_id):
            # Офлайн-сценарий вместо статичной заглушки: бартер/скидка/подсказки живут и без LLM
            response = offline_npc.get_offline_response(state, npc_id, player_input, game_data)
        new_state, events = dialogue.process_npc_dialogue(state, npc_id, player_input, response, game_data, rng=rng)
        if meta.get("usedFallback"):
            events = events + [{"id": "llm_fallback_used", "reason": meta.get("reason")}]
        return new_state, events
    if ctype == "accept_barter":
        return dialogue.accept_barter_offer(state, command.get("npcId", ""), game_data)
    if ctype == "decline_barter":
        return dialogue.decline_barter_offer(state, command.get("npcId", ""))

    return state, [{"id": "err_unknown_command", "type": ctype}]


def dispatch_command(
    state: dict,
    command: dict,
    game_data: GameData,
    rng: random.Random | None = None,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
    llm_transport_fn: Callable | None = None,
) -> tuple[dict, list[dict]]:
    """Единая точка входа в ядро (§ 32.2, § 34.1).

    Returns:
        (new_state, events). Автосейв — если нет событий err_*.
        При player_died сессия сбрасывается + событие session_reset_permadeath.
    """
    if not isinstance(command, dict):
        return state, [{"id": "err_unknown_command", "type": None}]

    new_state, events = _route(state, command, game_data, rng, session_path, template_path, llm_transport_fn)
    events = [_normalize_death_event(e) for e in events]

    # --- Permadeath (канон #4) ---
    if any(e.get("id") == "player_died" for e in events):
        if not any(e.get("id") == "sys_permadeath_reset" for e in events):
            reason = next((e.get("reason", "unknown") for e in events if e.get("id") == "player_died"), "unknown")
            new_state, death_events = handle_player_death(copy.deepcopy(new_state), reason, session_path, template_path)
            events.extend(death_events)
        events.append({"id": "session_reset_permadeath"})
        return new_state, events

    # --- Автосейв после каждого успешного действия (§ 32.2) ---
    if not any(str(e.get("id", "")).startswith("err_") for e in events):
        try:
            save_state(new_state, session_path)
        except (ValueError, OSError) as exc:
            events.append({"id": "sys_save_failed", "reason": str(exc)})

    return new_state, events