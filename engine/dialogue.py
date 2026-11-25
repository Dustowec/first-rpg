"""Блок 5.2: валидатор ответов LLM и исполнитель действий NPC (§§ 7.1, 26, 31).

Жёсткий гейткипер между нейросетью и состоянием мира:
- проверяет бой и присутствие NPC в текущей локации;
- обновляет настроение (mood) и флаг знакомства (met);
- фильтрует action.type по индивидуальному белому списку NPC (§ 31.2);
- проверяет инварианты баланса для бартера, скидок и подсказок;
- ограничивает сдвиг reputation одним шагом за сессию диалога (§ 31.1);
- не тратит AP и не продвигает stepOfDay (§ 7.1).

Все публичные функции чистые: работают на глубокой копии state и возвращают
(new_state, events). Модуль полностью детерминирован и не ходит в сеть —
llm_response приходит извне, из engine.llm_client.query_npc_llm().
"""

from __future__ import annotations

import copy
import random
import re
from typing import Any

from .data_loader import GameData
from .inventory import add_item, has_item, remove_item
from .llm_client import VALID_MOODS
from .trade import REPUTATION_LEVELS, is_npc_present, shift_reputation

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

# Глобально допустимые типы действий (§ 26.2)
GLOBAL_ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {"none", "open_trade", "discount_10", "barter_offer", "give_hint", "end_dialogue"}
)

# Дефолтный маппинг белых списков (ТЗ 5.2 / § 31.2 + end_dialogue).
# Используется, если в профиле NPC нет поля allowedActions/actionWhitelist.
DEFAULT_NPC_ACTIONS: dict[str, tuple[str, ...]] = {
    "npc_elder_miroslav": ("give_hint", "none", "end_dialogue"),
    "npc_merchant_ganna": ("open_trade", "discount_10", "none", "end_dialogue"),
    "npc_blacksmith_kolm": ("open_trade", "discount_10", "none", "end_dialogue"),
    "npc_innkeeper_boris": ("barter_offer", "discount_10", "give_hint", "none", "end_dialogue"),
    "npc_herbalist_vela": ("open_trade", "discount_10", "give_hint", "none", "end_dialogue"),
    "npc_hunter_rask": ("give_hint", "barter_offer", "discount_10", "none", "end_dialogue"),
    "npc_wanderer_kit": ("barter_offer", "give_hint", "none", "end_dialogue"),
}

# Для NPC вне таблицы (моды, будущие регионы) — только разговор и выход.
FALLBACK_NPC_ACTIONS: tuple[str, ...] = ("none", "end_dialogue")

# Инварианты бартера (§ 26.2)
BARTER_MAX_GIVE_PRICE: int = 15
BARTER_GOLD_DELTA_MIN: int = -15
BARTER_GOLD_DELTA_MAX: int = 10
BARTER_TAKE_CATEGORIES: tuple[str, ...] = ("junk", "material")
BARTER_FORBIDDEN_GIVE_CATEGORIES: tuple[str, ...] = ("weapon", "armor")

# Репутация (§ 31.1)
REP_SESSION_LIMIT: int = 1          # не больше 1 шага за сессию диалога
BARTER_REP_EVERY: int = 3           # три удачных бартера -> +1

_HOSTILE_REPUTATIONS: tuple[str, ...] = ("hated", "hostile")
_HOSTILE_MOODS: tuple[str, ...] = ("hostile", "irritated")
_DISCOUNT_MOODS: tuple[str, ...] = ("friendly", "sympathetic")

# Эвристика хамства и попыток взлома диалога (§ 26.2, § 31.1)
_RUDE_PATTERNS: tuple[str, ...] = (
    r"\bдурак\w*", r"\bидиот\w*", r"\bдебил\w*", r"\bтупиц\w*", r"\bсволоч\w*",
    r"\bмраз\w*", r"\bурод\w*", r"\bмудак\w*", r"\bзаткнись\b", r"пош[её]л ты",
    r"\bidiot\b", r"\bmoron\b", r"\bstupid\b", r"\bshut up\b", r"\basshole\b",
)
_EXPLOIT_PATTERNS: tuple[str, ...] = (
    r"игнорируй\s+(все\s+|предыдущие\s+)?инструкц",
    r"забудь\s+(свои\s+|все\s+)?правила",
    r"ignore\s+(all\s+|previous\s+)?instructions",
    r"system\s+prompt",
    r"ты\s+теперь\s+(админ|бог|не\s+npc)",
    r"дай\s+мне\s+\d{3,}\s+золот",
    r"give\s+me\s+\d{3,}\s+gold",
)


# ---------------------------------------------------------------------------
# A. Вспомогательные функции (работают на уже созданной копии state)
# ---------------------------------------------------------------------------

def get_allowed_actions(npc_id: str, game_data: GameData) -> set[str]:
    """Возвращает белый список action.type для конкретного NPC.

    Приоритет: поле allowedActions (ТЗ 5.2) -> actionWhitelist (текущая база)
    -> дефолтный маппинг ТЗ 5.2. Результат всегда пересекается с глобальным
    списком § 26.2 и дополняется none/end_dialogue.
    """
    profile = game_data.npcs.get(npc_id, {})
    raw = profile.get("allowedActions")
    if raw is None:
        raw = profile.get("actionWhitelist")
    if raw is None:
        raw = DEFAULT_NPC_ACTIONS.get(npc_id, FALLBACK_NPC_ACTIONS)
    if not isinstance(raw, (list, tuple, set)):
        raw = FALLBACK_NPC_ACTIONS

    allowed = {a for a in raw if isinstance(a, str)}
    allowed |= {"none", "end_dialogue"}
    return allowed & GLOBAL_ALLOWED_ACTIONS


def _ensure_npc_entry(state: dict, npc_id: str) -> dict:
    """Гарантирует запись NPC с дефолтами и возвращает её (in-place)."""
    npcs = state.setdefault("npcs", {})
    entry = npcs.setdefault(npc_id, {})
    entry.setdefault("mood", "neutral")
    entry.setdefault("reputation", "neutral")
    entry.setdefault("met", False)
    entry.setdefault("pendingBarter", None)
    entry.setdefault("barterCount", 0)
    entry.setdefault("dialogueRepDeltaThisSession", 0)
    return entry


def _resolve_mood(current_mood: str, proposed: Any, reputation: str) -> str:
    """Определяет итоговое настроение NPC с учётом репутации."""
    mood = proposed if proposed in VALID_MOODS else current_mood
    if mood not in VALID_MOODS:
        mood = "neutral"
    if reputation in _HOSTILE_REPUTATIONS and mood not in _HOSTILE_MOODS:
        mood = "hostile"
    return mood


def _is_rude(player_input: str) -> bool:
    """Грубая эвристика: оскорбление или попытка сломать диалог."""
    text = (player_input or "").lower().replace("ё", "е")
    for pattern in _RUDE_PATTERNS + _EXPLOIT_PATTERNS:
        if re.search(pattern.replace("ё", "е"), text):
            return True
    return False


def _shift_rep_inplace(state: dict, npc_id: str, delta: int) -> list[dict]:
    """Сдвиг репутации: суммарный сдвиг за диалог держится в окне [-1, +1].

    Окно считается по net-сумме: после +1 можно вернуться на -1 (net 0),
    но уйти на -2 уже нельзя — так формулирует § 31.1 («не больше 1 шага
    за диалог»). Делегирует изменение в shift_reputation (Блок 4.4), которая
    мутирует переданный state, поэтому вызывать только на рабочей копии.
    """
    entry = _ensure_npc_entry(state, npc_id)
    used = int(entry.get("dialogueRepDeltaThisSession", 0))

    if delta > 0:
        granted = min(delta, REP_SESSION_LIMIT - used)
    elif delta < 0:
        granted = max(delta, -REP_SESSION_LIMIT - used)
    else:
        granted = 0

    if granted == 0:
        return [{
            "id": "dialogue_rep_shift_capped",
            "npcId": npc_id,
            "requested": delta,
            "applied": 0,
        }]

    before = entry.get("reputation", "neutral")
    new_rep = shift_reputation(state, npc_id, granted)

    # Считаем реально пройденные шаги (на краю шкалы сдвиг может быть нулевым).
    try:
        before_idx = REPUTATION_LEVELS.index(before)
    except ValueError:
        before_idx = REPUTATION_LEVELS.index("neutral")
    actual = REPUTATION_LEVELS.index(new_rep) - before_idx
    entry["dialogueRepDeltaThisSession"] = used + actual

    if actual == 0:
        return [{
            "id": "dialogue_rep_shift_capped",
            "npcId": npc_id,
            "requested": delta,
            "applied": 0,
        }]

    return [{
        "id": "dialogue_reputation_changed",
        "npcId": npc_id,
        "delta": actual,
        "reputation": new_rep,
    }]


def _parse_gold_delta(raw: Any) -> int | None:
    """Валидирует goldDelta из ответа модели (None = невалидно)."""
    if raw is None:
        return 0
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and raw.is_integer():
        return int(raw)
    return None


def _is_forbidden_give_item(item: dict) -> bool:
    """Квестовые/запрещённые к выдаче предметы (задел на будущие флаги)."""
    if item.get("questItem") is True:
        return True
    if item.get("economy", {}).get("canTrade") is False:
        return True
    return item.get("category") in BARTER_FORBIDDEN_GIVE_CATEGORIES


def _validate_barter(
    state: dict,
    npc_id: str,
    action: dict,
    game_data: GameData,
) -> tuple[dict | None, str | None]:
    """Проверяет предложение бартера. Возвращает (offer, None) или (None, reason)."""
    entry = state.get("npcs", {}).get(npc_id, {})
    if entry.get("reputation", "neutral") in _HOSTILE_REPUTATIONS:
        return None, "barter_reputation_blocked"

    give_id = action.get("giveItemId")
    take_id = action.get("takeItemId")
    if not isinstance(give_id, str) or not isinstance(take_id, str):
        return None, "invalid_barter_params"

    try:
        give_item = game_data.get_item(give_id)
        take_item = game_data.get_item(take_id)
    except KeyError:
        return None, "invalid_barter_params"

    # Выдаваемый предмет: существует, не квестовый/запрещённый, дешёвый (<= 15).
    if _is_forbidden_give_item(give_item):
        return None, "invalid_barter_params"
    if give_item.get("economy", {}).get("buyPrice", 0) > BARTER_MAX_GIVE_PRICE:
        return None, "invalid_barter_params"

    # Принимаемый предмет: хлам/материалы и есть у игрока хотя бы 1 ед.
    if take_item.get("category") not in BARTER_TAKE_CATEGORIES:
        return None, "invalid_barter_params"
    if not has_item(state.get("player", {}), take_id, 1):
        return None, "invalid_barter_params"

    gold_delta = _parse_gold_delta(action.get("goldDelta"))
    if gold_delta is None:
        return None, "invalid_barter_params"
    if not (BARTER_GOLD_DELTA_MIN <= gold_delta <= BARTER_GOLD_DELTA_MAX):
        return None, "invalid_barter_params"
    if gold_delta < 0 and state.get("player", {}).get("gold", 0) < abs(gold_delta):
        return None, "invalid_barter_params"

    return {
        "giveItemId": give_id,
        "takeItemId": take_id,
        "goldDelta": gold_delta,
    }, None


def _bfs_distances(map_data: dict, start_id: str) -> dict[str, int]:
    """Расстояния в рёбрах от текущего узла (для «ближайшей» подсказки)."""
    connections = {n["id"]: n.get("connections", []) for n in map_data.get("nodes", [])}
    distances = {start_id: 0}
    queue = [start_id]
    while queue:
        current = queue.pop(0)
        for neighbour in connections.get(current, []):
            if neighbour not in distances:
                distances[neighbour] = distances[current] + 1
                queue.append(neighbour)
    return distances


def _pick_map_hint(state: dict, target_id: Any) -> str | None:
    """Выбирает нераскрытую точку интереса: логово, затем ближайший danger >= 2."""
    flags = state.setdefault("flags", {})
    revealed = flags.setdefault("revealedHints", [])
    map_data = state.get("map", {})
    nodes = map_data.get("nodes", [])

    candidates = [
        n for n in nodes
        if not n.get("state", {}).get("visited", False)
        and n.get("danger", 0) >= 2
        and n["id"] not in revealed
    ]
    if not candidates:
        return None

    if isinstance(target_id, str) and any(n["id"] == target_id for n in candidates):
        return target_id

    distances = _bfs_distances(map_data, map_data.get("currentNodeId", ""))
    candidates.sort(key=lambda n: (
        0 if n.get("type") == "lair" else 1,
        distances.get(n["id"], 999),
        -n.get("danger", 0),
        n["id"],
    ))
    return candidates[0]["id"]


def _region_monster_pool(state: dict, game_data: GameData) -> list[str]:
    """Монстры региона: объединение monsterPool биомов текущей карты."""
    pool: set[str] = set()
    for node in state.get("map", {}).get("nodes", []):
        try:
            biome = game_data.get_biome(node.get("type", ""))
        except KeyError:
            continue
        for mob_id in biome.get("monsterPool", []):
            if mob_id in game_data.monsters:
                pool.add(mob_id)
    return sorted(pool)


def _pick_bestiary_hint(
    state: dict,
    game_data: GameData,
    target_id: Any,
    rng: random.Random | None,
) -> dict | None:
    """Готовит запись о слабости монстра региона для бестиария."""
    flags = state.setdefault("flags", {})
    unlocked = flags.setdefault("bestiaryUnlocked", [])
    known = {e.get("mobId") for e in unlocked if isinstance(e, dict)}
    known |= {e for e in unlocked if isinstance(e, str)}

    candidates = [m for m in _region_monster_pool(state, game_data) if m not in known]
    if not candidates:
        return None

    if isinstance(target_id, str) and target_id in candidates:
        mob_id = target_id
    elif rng is not None:
        mob_id = rng.choice(candidates)
    else:
        mob_id = candidates[0]

    monster = game_data.get_monster(mob_id)
    affinities = monster.get("affinities", {}) or {}
    weakness = sorted(k for k, v in affinities.items() if isinstance(v, (int, float)) and v > 1.0)
    return {
        "mobId": mob_id,
        "creatureType": monster.get("type", "unknown"),
        "weakness": weakness,
    }


def _execute_action(
    state: dict,
    npc_id: str,
    action: dict,
    action_type: str,
    game_data: GameData,
    rng: random.Random | None,
) -> list[dict]:
    """Исполняет уже отфильтрованное действие на рабочей копии state."""
    entry = _ensure_npc_entry(state, npc_id)
    reputation = entry.get("reputation", "neutral")
    events: list[dict] = []

    if action_type == "none":
        return events

    if action_type == "open_trade":
        if reputation in _HOSTILE_REPUTATIONS:
            return [{"id": "err_npc_refuses_trade", "npcId": npc_id, "reason": reputation}]
        return [{"id": "dialogue_open_trade", "npcId": npc_id}]

    if action_type == "discount_10":
        if entry.get("mood") in _DISCOUNT_MOODS and reputation not in _HOSTILE_REPUTATIONS:
            entry["tempDiscount10"] = True
            return [{
                "id": "dialogue_discount_granted",
                "npcId": npc_id,
                "discountPercent": 10,
            }]
        return [{
            "id": "dialogue_action_ignored",
            "reason": "discount_conditions_not_met",
            "actionType": action_type,
        }]

    if action_type == "barter_offer":
        offer, reason = _validate_barter(state, npc_id, action, game_data)
        if offer is None:
            entry["pendingBarter"] = None
            return [{
                "id": "dialogue_action_ignored",
                "reason": reason,
                "actionType": action_type,
            }]
        entry["pendingBarter"] = offer
        return [{
            "id": "dialogue_barter_offered",
            "npcId": npc_id,
            "offer": copy.deepcopy(offer),
        }]

    if action_type == "give_hint":
        hint_type = action.get("hintType")
        target_id = action.get("targetId")
        want_bestiary = hint_type in ("bestiary", "monster", "weakness")

        if not want_bestiary:
            node_id = _pick_map_hint(state, target_id)
            if node_id is not None:
                state["flags"]["revealedHints"].append(node_id)
                return [{
                    "id": "dialogue_hint_given",
                    "npcId": npc_id,
                    "hintType": "map_poi",
                    "targetId": node_id,
                }]

        record = _pick_bestiary_hint(state, game_data, target_id, rng)
        if record is not None:
            state["flags"]["bestiaryUnlocked"].append(record)
            return [{
                "id": "dialogue_hint_given",
                "npcId": npc_id,
                "hintType": "bestiary",
                "targetId": record["mobId"],
            }]

        if want_bestiary:
            node_id = _pick_map_hint(state, target_id)
            if node_id is not None:
                state["flags"]["revealedHints"].append(node_id)
                return [{
                    "id": "dialogue_hint_given",
                    "npcId": npc_id,
                    "hintType": "map_poi",
                    "targetId": node_id,
                }]

        return [{
            "id": "dialogue_action_ignored",
            "reason": "no_hint_available",
            "actionType": action_type,
        }]

    if action_type == "end_dialogue":
        entry["pendingBarter"] = None
        return [{"id": "dialogue_ended", "npcId": npc_id}]

    return events


# ---------------------------------------------------------------------------
# B. Публичное API
# ---------------------------------------------------------------------------

def reset_dialogue_session(state: dict, npc_id: str) -> tuple[dict, list[dict]]:
    """Сбрасывает счётчик сдвига репутации за диалог (вход/выход из диалога)."""
    new_state = copy.deepcopy(state)
    entry = _ensure_npc_entry(new_state, npc_id)
    entry["dialogueRepDeltaThisSession"] = 0
    return new_state, []


def apply_dialogue_reputation_shift(
    state: dict,
    npc_id: str,
    delta: int,
) -> tuple[dict, list[dict]]:
    """Сдвигает репутацию NPC, соблюдая лимит ±1 за сессию диалога (§ 31.1)."""
    new_state = copy.deepcopy(state)
    _ensure_npc_entry(new_state, npc_id)
    events = _shift_rep_inplace(new_state, npc_id, delta)
    return new_state, events


def process_npc_dialogue(
    state: dict,
    npc_id: str,
    player_input: str,
    llm_response: dict,
    game_data: GameData,
    rng: random.Random | None = None,
) -> tuple[dict, list[dict]]:
    """Валидирует ответ LLM и исполняет разрешённое действие NPC (§ 26, § 31).

    Args:
        state: Текущее состояние игры (не мутируется).
        npc_id: ID собеседника.
        player_input: Реплика игрока (для эвристики хамства).
        llm_response: Ответ модели из query_npc_llm (без meta).
        game_data: База контента.
        rng: Опциональный ГСЧ для выбора записи бестиария.

    Returns:
        (new_state, events); первым событием всегда идёт npc_spoke.
        AP не тратится, stepOfDay не меняется (§ 7.1).
    """
    world = state.get("world", {})
    if world.get("inCombat") is True:
        return state, [{"id": "err_in_combat"}]
    if not is_npc_present(state, npc_id):
        return state, [{"id": "err_npc_not_here", "npcId": npc_id}]

    new_state = copy.deepcopy(state)
    entry = _ensure_npc_entry(new_state, npc_id)
    response = llm_response if isinstance(llm_response, dict) else {}

    # --- Базовое состояние NPC: знакомство и настроение ---
    entry["met"] = True
    entry["mood"] = _resolve_mood(
        entry.get("mood", "neutral"),
        response.get("mood"),
        entry.get("reputation", "neutral"),
    )

    action = response.get("action") or {"type": "none"}
    if not isinstance(action, dict):
        action = {"type": "none"}
    action_type = action.get("type") or "none"

    events: list[dict] = [{
        "id": "npc_spoke",
        "npcId": npc_id,
        "npcReply": response.get("npcReply", ""),
        "mood": entry["mood"],
        "suggestedReplies": response.get("suggestedReplies", []),
    }]

    # --- Эвристика хамства / взлома диалога (§ 26.2, § 31.1) ---
    rude = _is_rude(player_input)
    hostile_exit = action_type == "end_dialogue" and entry["mood"] in _HOSTILE_MOODS
    if rude or hostile_exit:
        events.extend(_shift_rep_inplace(new_state, npc_id, -1))

    # --- Фильтрация по белому списку NPC (§ 31.2) ---
    allowed = get_allowed_actions(npc_id, game_data)
    if action_type not in allowed:
        events.append({
            "id": "dialogue_action_ignored",
            "reason": "not_allowed_for_npc",
            "actionType": action_type,
        })
        action_type = "none"

    events.extend(_execute_action(new_state, npc_id, action, action_type, game_data, rng))
    return new_state, events


def accept_barter_offer(
    state: dict,
    npc_id: str,
    game_data: GameData,
) -> tuple[dict, list[dict]]:
    """Атомарно исполняет ранее предложенный бартер (§ 26.1, § 31.1)."""
    if state.get("world", {}).get("inCombat") is True:
        return state, [{"id": "err_in_combat"}]
    if not is_npc_present(state, npc_id):
        return state, [{"id": "err_npc_not_here", "npcId": npc_id}]

    offer = state.get("npcs", {}).get(npc_id, {}).get("pendingBarter")
    if not offer:
        return state, [{"id": "err_no_active_barter", "npcId": npc_id}]

    new_state = copy.deepcopy(state)
    entry = _ensure_npc_entry(new_state, npc_id)
    offer = copy.deepcopy(entry["pendingBarter"])

    # Повторная проверка инвариантов: игрок мог всё потратить между репликами.
    recheck, reason = _validate_barter(new_state, npc_id, offer, game_data)
    if recheck is None:
        entry["pendingBarter"] = None
        return new_state, [{
            "id": "dialogue_action_ignored",
            "reason": reason,
            "actionType": "barter_offer",
        }]

    # --- Обмен: списали хлам -> золото -> выдали предмет ---
    new_state, remove_events = remove_item(new_state, offer["takeItemId"], 1)
    if any(e["id"].startswith("err_") for e in remove_events):
        return state, remove_events
    entry = _ensure_npc_entry(new_state, npc_id)
    new_state["player"]["gold"] += offer["goldDelta"]
    new_state, _ = add_item(new_state, offer["giveItemId"], 1, game_data=game_data)
    entry = _ensure_npc_entry(new_state, npc_id)
    entry["pendingBarter"] = None
    entry["barterCount"] = int(entry.get("barterCount", 0)) + 1

    events: list[dict] = [{
        "id": "barter_completed",
        "npcId": npc_id,
        "offer": offer,
    }]

    # Три удачных бартера -> +1 репутации (с лимитом сессии).
    if entry["barterCount"] % BARTER_REP_EVERY == 0:
        events.extend(_shift_rep_inplace(new_state, npc_id, +1))

    return new_state, events


def decline_barter_offer(state: dict, npc_id: str) -> tuple[dict, list[dict]]:
    """Отклоняет активное предложение бартера (кнопка «Отказаться» в CLI)."""
    new_state = copy.deepcopy(state)
    entry = _ensure_npc_entry(new_state, npc_id)
    entry["pendingBarter"] = None
    return new_state, [{"id": "dialogue_barter_declined", "npcId": npc_id}]