"""
Исследование мира: перемещение, стелс, засады, поиск, ожидание.
Блок 4.2 — специфика tecniche_4_2.md.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

DEFAULT_SESSION_PATH = "state_session.json"
DEFAULT_TEMPLATE_PATH = "state_template.json"

# ---------------------------------------------------------------------------
# Пулы монстров по типу локации (канон §30.1)
# ---------------------------------------------------------------------------
_MONSTER_POOLS: dict[str, list[str]] = {
    "road": ["mob_rat_giant", "mob_bandit_scout", "mob_bandit_rogue"],
    "meadow": ["mob_rat_giant", "mob_wolf_forest", "mob_boar_wild", "mob_wolf_alpha"],
    "forest_edge": ["mob_wolf_forest", "mob_boar_wild", "mob_wolf_alpha", "mob_bear_black"],
    "ruins": ["mob_ghoul", "mob_bandit_rogue", "mob_skeleton_warrior", "mob_bandit_chief"],
    "deep_forest": ["mob_spider_giant", "mob_bear_black", "mob_troll_hill"],
    "swamp": ["mob_spider_giant", "mob_ghoul", "mob_swamp_hag"],
}

# pSpawn по типу локации (§28.1)
_PSPAWN: dict[str, float] = {
    "village": 0.00, "camp": 0.10, "road": 0.25, "meadow": 0.25,
    "forest_edge": 0.35, "ruins": 0.35, "deep_forest": 0.45,
    "swamp": 0.40, "lair": 1.00,
}

# ---------------------------------------------------------------------------
# Утилиты: загрузка GameData
# ---------------------------------------------------------------------------

def _load_game_data(data_dir: str | Path = "data") -> dict[str, Any]:
    """Загружает все JSON из data/ в единый словарь."""
    gd: dict[str, list[dict]] = {}
    p = Path(data_dir)
    if not p.exists():
        return gd
    for sub in ["armor", "consumables", "food", "materials", "monsters", "weapons", "biomes"]:
        items: list[dict] = []
        sp = p / sub
        if sp.exists():
            for fp in sorted(sp.glob("*.json")):
                with open(fp, encoding="utf-8") as f:
                    items.append(json.load(f))
        if items:
            gd[sub] = items
    return gd


def _find_item(gd: dict, item_id: str) -> dict | None:
    """Ищет предмет по itemId во всём GameData."""
    for items in gd.values():
        for it in items:
            if it.get("id") == item_id:
                return it
    return None


def _find_monster(gd: dict, mob_id: str) -> dict | None:
    """Ищет монстра по mobId."""
    monsters = gd.get("monsters", [])
    for m in monsters:
        if m.get("id") == mob_id:
            return m
    return None


def _get_monsters_by_tier(gd: dict, tier: int) -> list[dict]:
    """Все монстры заданного тира."""
    out = []
    for m in gd.get("monsters", []):
        if m.get("tier") == tier:
            out.append(m)
    return out


# ---------------------------------------------------------------------------
# Вспомогательная: добавление предмета в инвентарь
# ---------------------------------------------------------------------------

def _add_item(state: dict, item_id: str, count: int) -> None:
    """Добавляет предмет в инвентарь (или увеличивает count)."""
    inv = state["player"].setdefault("inventory", [])
    for slot in inv:
        if slot["itemId"] == item_id:
            slot["count"] += count
            return
    inv.append({"itemId": item_id, "count": count})


# ---------------------------------------------------------------------------
# Вспомогательная: масштабирование HP монстра
# ---------------------------------------------------------------------------

def _scale_monster_hp(base_hp: int, diff_mult: float) -> int:
    return max(1, round(base_hp * diff_mult))


# ---------------------------------------------------------------------------
# Вспомогательная: выбор монстра из пула
# ---------------------------------------------------------------------------

def _pick_monster_from_pool(pool_ids: list[str], target_tier: int,
                            gd: dict, rng: random.Random) -> str | None:
    """Выбирает mob_id из пула, фильтруя по tier."""
    candidates = []
    for mid in pool_ids:
        m = _find_monster(gd, mid)
        if m and m.get("tier") == target_tier:
            candidates.append(mid)
    if not candidates:
        # Ближайший тир
        for delta in [1, -1, 2, -2, 3, -3, 4, -4, 5, -5]:
            tt = target_tier + delta
            if 1 <= tt <= 5:
                for mid in pool_ids:
                    m = _find_monster(gd, mid)
                    if m and m.get("tier") == tt:
                        candidates.append(mid)
                        break
                if candidates:
                    break
    if not candidates:
        # Любой монстр target_tier
        all_at_tier = _get_monsters_by_tier(gd, target_tier)
        if all_at_tier:
            candidates = [m["id"] for m in all_at_tier]
    if not candidates:
        return None
    return rng.choice(candidates)


# ---------------------------------------------------------------------------
# А. Ленивый спавн монстра
# ---------------------------------------------------------------------------

def _roll_node_spawn(state: dict, node: dict, gd: dict, rng: random.Random) -> None:
    """Ленивый спавн монстра при первом посещении узла (§4.2 А)."""
    node["state"]["spawnRolled"] = True
    ntype = node["type"]

    if ntype == "village":
        node["state"]["monster"] = None
        return

    region = state["meta"]["region"]
    diff_mult = state["meta"].get("difficultyMultiplier", 1.0)
    danger = node.get("danger", 1)
    target_tier = min(5, max(1, danger + region - 1))

    # --- Логово ---
    if ntype == "lair":
        boss_tier = min(5, max(1, 4 + region - 1))
        if region == 1:
            queue_ids = ["mob_bandit_rogue", "mob_bandit_rogue", "mob_troll_hill"]
        else:
            elite_tier = min(5, 2 + region - 1)
            e1 = _pick_monster_from_pool(_MONSTER_POOLS.get("deep_forest", []), elite_tier, gd, rng) or "mob_ogre"
            e2 = _pick_monster_from_pool(_MONSTER_POOLS.get("deep_forest", []), elite_tier, gd, rng) or "mob_ogre"
            boss_id = _pick_monster_from_pool(_get_monsters_by_tier(gd, boss_tier), boss_tier, gd, rng) or "mob_troll_ancient"
            queue_ids = [e1, e2, boss_id]

        queue = []
        for qid in queue_ids:
            base = _find_monster(gd, qid)
            base_hp = base.get("hp", 10) if base else 10
            hp = _scale_monster_hp(base_hp, diff_mult)
            queue.append({"mobId": qid, "revealed": False, "hp": hp, "maxHp": hp})

        node["state"]["lairQueue"] = queue
        node["state"]["monster"] = copy.deepcopy(queue[0])
        return

    # --- Обычная дикая локация ---
    p_spawn = _PSPAWN.get(ntype, 0.25)
    if rng.random() > p_spawn:
        node["state"]["monster"] = None
        return

    pool_ids = _MONSTER_POOLS.get(ntype, [])
    if not pool_ids:
        pool_ids = [m["id"] for m in _get_monsters_by_tier(gd, target_tier)]

    mob_id = _pick_monster_from_pool(pool_ids, target_tier, gd, rng)
    if not mob_id:
        node["state"]["monster"] = None
        return

    base = _find_monster(gd, mob_id)
    # Монстры хранят HP напрямую как base["hp"], а не base["stats"]["hp"]["max"]
    base_hp = base.get("hp", 6) if base else 6
    hp = _scale_monster_hp(base_hp, diff_mult)
    node["state"]["monster"] = {"mobId": mob_id, "revealed": False, "hp": hp, "maxHp": hp}


# ---------------------------------------------------------------------------
# Вспомогательная: advance_time
# ---------------------------------------------------------------------------

def advance_time(state: dict, steps: int = 1,
                 gd: dict | None = None,
                 rng: random.Random | None = None,
                 session_path: str = DEFAULT_SESSION_PATH,
                 template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]:
    """
    Продвигает время на steps шагов. Тикает регенерацию, DoT, проверяет голод.
    Возвращает (new_state, events). Если игрок погиб — events содержит death.

    Канон голода (§ 7.2) берётся из world_time.get_hunger_deadlines: перк
    «Тугий пояс» (scavenging >= 6) сдвигает дедлайны 7/17 -> 9/19. На новом дне
    флаги сытости обнуляются, счётчик дней с зачистки тикает (§ 28.2).
    """
    # Локальный импорт — чтобы не завязывать модуль на порядок импортов engine.
    from engine.world_time import get_hunger_deadlines

    st = copy.deepcopy(state)
    world = st["world"]
    player = st["player"]
    level = player.get("level", 1)

    try:
        morning_deadline, evening_deadline = get_hunger_deadlines(player)
    except (KeyError, AttributeError, TypeError):
        morning_deadline, evening_deadline = 7, 17

    for _ in range(steps):
        # Шаг суток
        world["stepOfDay"] += 1
        if world["stepOfDay"] > 20:
            world["stepOfDay"] = 1
            world["day"] += 1
            # Новый день (§ 7.2): два приёма пищи нужно закрыть заново
            world["fedMorning"] = False
            world["fedEvening"] = False
            # Счётчик дней с зачистки для респавна (§ 28.2, канон #1)
            for nd in st.get("map", {}).get("nodes", []):
                nd_state = nd.get("state", {})
                if isinstance(nd_state.get("daysSinceCleared"), int):
                    nd_state["daysSinceCleared"] += 1

        step = world["stepOfDay"]

        # --- Проверка голода (§7.2), дедлайны с учётом перка ---
        if step == morning_deadline and not world.get("fedMorning"):
            _kill_player(st, "starvation_morning")
            return st, [{"id": "player_death", "cause": "starvation_morning"}]
        if step == evening_deadline and not world.get("fedEvening"):
            _kill_player(st, "starvation_evening")
            return st, [{"id": "player_death", "cause": "starvation_evening"}]

        # --- Блокировка регенерации в фазе голода (окна от дедлайнов) ---
        hunger_blocked = False
        if step < morning_deadline and not world.get("fedMorning"):
            hunger_blocked = True
        if 10 <= step < evening_deadline and not world.get("fedEvening"):
            hunger_blocked = True

        # --- Естественная регенерация (§7.3) ---
        if not world.get("inCombat") and not hunger_blocked:
            # Проверяем нет ли активных DoT
            has_dot = any(ef.get("type") in ("poison", "bleeding") for ef in world.get("activeEffects", []))
            if not has_dot:
                # HP: +level каждые 3 хода
                if step % 3 == 0:
                    res = player["resources"]
                    cur = min(res["hp"]["max"], res["hp"]["current"] + level)
                    res["hp"]["current"] = cur
                # MP: +level каждые 5 ходов
                if step % 5 == 0:
                    res = player["resources"]
                    cur = min(res["mp"]["max"], res["mp"]["current"] + level)
                    res["mp"]["current"] = cur

        # --- Тик активных эффектов ---
        effects = world.get("activeEffects", [])
        for ef in effects:
            ticks = ef.get("ticksLeft", 0)
            delta = ef.get("hpDeltaPerTurn", 0)
            if delta != 0:
                res = player["resources"]
                res["hp"]["current"] = max(0, res["hp"]["current"] + delta)
                if res["hp"]["current"] <= 0:
                    _kill_player(st, "dot_damage")
                    return st, [{"id": "player_death", "cause": "dot_damage"}]
            ef["ticksLeft"] = ticks - 1
        world["activeEffects"] = [ef for ef in effects if ef.get("ticksLeft", 0) > 0]

    return st, []


def _kill_player(state: dict, cause: str) -> None:
    """Помечает игрока как мёртвого."""
    state["world"]["inCombat"] = False
    state["world"]["playerDead"] = True
    state["world"]["deathCause"] = cause


# ---------------------------------------------------------------------------
# Вспомогательная: start_combat (заглушка, вызывается из exploration)
# ---------------------------------------------------------------------------

def _start_combat(state: dict, game_data: dict, is_ambush: bool = False,
                  rng: random.Random | None = None,
                  session_path: str = DEFAULT_SESSION_PATH,
                  template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]:
    """
    Запускает бой. Заглушка — возвращает событие start_combat.
    Реальная боевая логика будет в engine/combat.py.
    """
    st = copy.deepcopy(state)
    st["world"]["inCombat"] = True
    map_data = st["map"]
    current_node = None
    for nd in map_data["nodes"]:
        if nd["id"] == map_data["currentNodeId"]:
            current_node = nd
            break

    monster = current_node["state"]["monster"] if current_node else None
    if not monster:
        return st, [{"id": "err_no_monster_for_combat"}]

    # Если засада — монстр ходит первым
    monster_first = is_ambush

    return st, [{
        "id": "combat_start",
        "mobId": monster["mobId"],
        "isAmbush": is_ambush,
        "monsterFirst": monster_first,
    }]


# ---------------------------------------------------------------------------
# Б. Перемещение
# ---------------------------------------------------------------------------

def move_to_node(state: dict, target_node_id: str, game_data: dict | None = None,
                 rng: random.Random | None = None,
                 session_path: str = DEFAULT_SESSION_PATH,
                 template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]:
    """Перемещение в соседний узел (§4.2 Б)."""
    if game_data is None:
        game_data = _load_game_data()
    if rng is None:
        rng = random.Random(state["meta"]["seed"])

    st = copy.deepcopy(state)
    world = st["world"]
    map_data = st["map"]

    # 1. Валидация
    if world.get("inCombat"):
        return st, [{"id": "err_in_combat"}]

    current_node_id = map_data["currentNodeId"]
    current_node = None
    for nd in map_data["nodes"]:
        if nd["id"] == current_node_id:
            current_node = nd
            break

    if not current_node:
        return st, [{"id": "err_no_current_node"}]

    target_ids = [nd["id"] for nd in map_data["nodes"]]
    if target_node_id not in current_node["connections"]:
        return st, [{"id": "err_invalid_connection"}]

    target_node = None
    for nd in map_data["nodes"]:
        if nd["id"] == target_node_id:
            target_node = nd
            break

    # 2. Трата 1 AP
    new_state, events = advance_time(st, steps=1, gd=game_data, rng=rng,
                                     session_path=session_path, template_path=template_path)
    if new_state.get("world", {}).get("playerDead"):
        return new_state, events

    # 3. Обновление позиции и флагов
    new_map = new_state["map"]
    new_map["currentNodeId"] = target_node_id

    # Находим target_node в new_state
    for nd in new_map["nodes"]:
        if nd["id"] == target_node_id:
            tnode = nd
            break
    else:
        return new_state, events

    tnode["state"]["lookUsed"] = False
    if not tnode["state"]["visited"]:
        tnode["state"]["visited"] = True
        new_state["world"]["locationsVisited"] = new_state["world"].get("locationsVisited", 0) + 1

    if not tnode["state"]["spawnRolled"]:
        _roll_node_spawn(new_state, tnode, game_data, rng)

    events.append({
        "id": "moved_to_node",
        "nodeId": target_node_id,
        "name": tnode["name"],
        "type": tnode["type"],
    })

    # 4. Проверка засады (§27.2)
    monster = tnode["state"].get("monster")
    if monster and not monster.get("revealed"):
        scav = new_state["player"]["skills"].get("scavenging", 0)
        ambush_chance = max(5, 15 - scav)
        if rng.randint(0, 100) <= ambush_chance:
            monster["revealed"] = True
            events.append({"id": "ambush_triggered", "mobId": monster["mobId"]})
            combat_state, combat_events = _start_combat(new_state, game_data, is_ambush=True, rng=rng,
                                                        session_path=session_path, template_path=template_path)
            return combat_state, events + combat_events

    return new_state, events


# ---------------------------------------------------------------------------
# В. Осмотреться
# ---------------------------------------------------------------------------

def look_around(state: dict, game_data: dict | None = None,
                rng: random.Random | None = None,
                session_path: str = DEFAULT_SESSION_PATH,
                template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]:
    """Осмотреться (§4.2 В)."""
    if game_data is None:
        game_data = _load_game_data()
    if rng is None:
        rng = random.Random(state["meta"]["seed"])

    st = copy.deepcopy(state)
    world = st["world"]
    map_data = st["map"]

    if world.get("inCombat"):
        return st, []

    current_node_id = map_data["currentNodeId"]
    current_node = None
    for nd in map_data["nodes"]:
        if nd["id"] == current_node_id:
            current_node = nd
            break

    if not current_node or current_node["state"].get("lookUsed"):
        return st, [{"id": "err_already_looked"}]

    # Трата 1 AP
    new_state, events = advance_time(st, steps=1, gd=game_data, rng=rng,
                                     session_path=session_path, template_path=template_path)
    if new_state.get("world", {}).get("playerDead"):
        return new_state, events

    # Находим current_node в new_state
    new_map = new_state["map"]
    new_current = None
    for nd in new_map["nodes"]:
        if nd["id"] == current_node_id:
            new_current = nd
            break

    new_current["state"]["lookUsed"] = True

    monster = new_current["state"].get("monster")
    if monster:
        monster["revealed"] = True
        # Помечаем lairQueue если логово
        if new_current["type"] == "lair":
            lq = new_current["state"].get("lairQueue")
            if lq:
                for entry in lq:
                    entry["revealed"] = True
        events.append({
            "id": "look_found_monster",
            "mobId": monster["mobId"],
            "isLair": new_current["type"] == "lair",
        })
    else:
        events.append({"id": "look_clear"})

    return new_state, events


# ---------------------------------------------------------------------------
# Г. Поиск
# ---------------------------------------------------------------------------

# Биомные сдвиги весов (§30.1)
_BIOME_WEIGHT_SHIFTS: dict[str, dict[str, float]] = {
    "road": {"junk": 10.0, "nothing": -10.0},
    "meadow": {"food": 10.0, "nothing": -10.0},
    "forest_edge": {"food": 10.0, "nothing": -10.0},
    "ruins": {"weapon": 5.0, "armor": 5.0, "nothing": -10.0},
    "deep_forest": {"food": 10.0, "nothing": -10.0},
    "swamp": {"food": 10.0, "nothing": -10.0},
}


def scavenge_node(state: dict, game_data: dict | None = None,
                  rng: random.Random | None = None,
                  session_path: str = DEFAULT_SESSION_PATH,
                  template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]:
    """Поиск (§4.2 Г)."""
    if game_data is None:
        game_data = _load_game_data()
    if rng is None:
        rng = random.Random(state["meta"]["seed"])

    st = copy.deepcopy(state)
    world = st["world"]
    map_data = st["map"]

    # 1. Валидация
    if world.get("inCombat"):
        return st, []

    current_node_id = map_data["currentNodeId"]
    current_node = None
    for nd in map_data["nodes"]:
        if nd["id"] == current_node_id:
            current_node = nd
            break

    if not current_node:
        return st, []

    ntype = current_node["type"]
    search_max = current_node["state"].get("searchMax", 0)

    if ntype == "village" or search_max <= 0:
        return st, [{"id": "err_cannot_search_here"}]

    if current_node["state"].get("searchDepleted") or current_node["state"]["searchCount"] >= search_max:
        return st, [{"id": "err_search_depleted"}]

    # 2. Трата 1 AP
    new_state, events = advance_time(st, steps=1, gd=game_data, rng=rng,
                                     session_path=session_path, template_path=template_path)
    if new_state.get("world", {}).get("playerDead"):
        return new_state, events

    # 3. Обновление счётчика
    new_map = new_state["map"]
    new_current = None
    for nd in new_map["nodes"]:
        if nd["id"] == current_node_id:
            new_current = nd
            break

    new_current["state"]["searchCount"] += 1
    depleted = False
    if new_current["state"]["searchCount"] >= search_max:
        new_current["state"]["searchDepleted"] = True
        depleted = True

    # 4. Расчёт весов
    base_weights = {"nothing": 35.0, "food": 35.0, "junk": 20.0, "weapon": 7.0, "armor": 3.0}
    shifts = _BIOME_WEIGHT_SHIFTS.get(ntype, {})
    for k, v in shifts.items():
        base_weights[k] = base_weights.get(k, 0.0) + v

    # Бонусы
    intel = new_state["player"]["attributes"].get("intelligence", 1)
    intel_bonus = (intel - 1) * 1.5
    scav_skill = new_state["player"]["skills"].get("scavenging", 0)
    perk_bonus = 15.0 if scav_skill >= 3 else 0.0

    reduction = min(base_weights["nothing"], intel_bonus + perk_bonus)
    if reduction > 0:
        base_weights["nothing"] -= reduction
        base_weights["food"] += reduction * 0.6
        base_weights["junk"] += reduction * 0.3
        base_weights["weapon"] += reduction * 0.05
        base_weights["armor"] += reduction * 0.05

    # 5. Ролл категории
    total = sum(base_weights.values())
    roll = rng.uniform(0, total)
    cumulative = 0.0
    chosen_cat = "nothing"
    for cat, w in base_weights.items():
        cumulative += w
        if roll <= cumulative:
            chosen_cat = cat
            break

    if chosen_cat == "nothing":
        return new_state, events + [{"id": "scavenge_nothing", "depleted": depleted}]

    # Маппинг категорий поиска на ключи GameData
    _CAT_MAP = {"food": "food", "junk": "materials", "weapon": "weapons", "armor": "armor", "consumable": "consumables"}
    items = game_data.get(_CAT_MAP.get(chosen_cat, chosen_cat), [])
    candidates = [it for it in items if it.get("economy", {}).get("canFind", True)]

    # Перк «Чутьё кладоискателя» (§22.3)
    include_rare = False
    if scav_skill >= 10 and rng.random() <= 0.02:
        include_rare = True
        # Добавляем все предметы категории (включая canFind=False)
        all_items = game_data.get(chosen_cat, [])
        candidates = all_items

    if not candidates:
        return new_state, events + [{"id": "scavenge_nothing", "depleted": depleted}]

    # Фильтр weapon/armor по тиру локации
    target_tier = min(5, max(1, new_current.get("danger", 1) + new_state["meta"]["region"] - 1))
    if chosen_cat in ("weapon", "armor"):
        candidates = [it for it in candidates if it.get("tier", 1) <= target_tier]
        if not candidates:
            # Fallback — любой предмет
            candidates = [it for it in game_data.get(chosen_cat, []) if it.get("economy", {}).get("canFind", True)]

    # Для deep_forest/swamp — повышенный вес грибов/мха
    if chosen_cat == "food" and ntype in ("deep_forest", "swamp"):
        preferred = ["food_mushrooms", "food_moss", "food_red_mushroom"]
        pref_items = [it for it in candidates if it.get("id") in preferred]
        if pref_items and rng.random() < 0.5:
            candidates = pref_items

    item = rng.choice(candidates)
    item_id = item["id"]
    _add_item(new_state, item_id, 1)

    return new_state, events + [{
        "id": "scavenge_found",
        "category": chosen_cat,
        "itemId": item_id,
        "depleted": depleted,
    }]


# ---------------------------------------------------------------------------
# Д. Ожидание
# ---------------------------------------------------------------------------

def wait_step(state: dict, game_data: dict | None = None,
              rng: random.Random | None = None,
              session_path: str = DEFAULT_SESSION_PATH,
              template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]:
    """Ожидание 1 AP (§4.2 Д)."""
    if game_data is None:
        game_data = _load_game_data()
    if rng is None:
        rng = random.Random(state["meta"]["seed"])

    st = copy.deepcopy(state)
    if st["world"].get("inCombat"):
        return st, []

    new_state, events = advance_time(st, steps=1, gd=game_data, rng=rng,
                                     session_path=session_path, template_path=template_path)
    if new_state.get("world", {}).get("playerDead"):
        return new_state, events

    return new_state, events + [{"id": "waited_one_step"}]


def _is_dead(state: dict) -> bool:
    """Проверяет, мёртв ли игрок."""
    return state.get("world", {}).get("playerDead", False)
