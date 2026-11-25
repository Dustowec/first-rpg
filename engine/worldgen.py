"""
Процедурный генератор графа региона и переход в «Дальние тропы».
Блок 4.1 — специфика tecniche_4_1.md.
"""

from __future__ import annotations

import copy
import json
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Пулы названий (канон §30.2)
# ---------------------------------------------------------------------------
_NAME_POOLS: dict[str, dict[str, list[str]]] = {
    "road": {
        "adjectives": ["Сухой", "Старый", "Разбитый", "Контрабандистский"],
        "nouns": ["тракт", "шлях", "дорога", "тропа"],
    },
    "meadow": {
        "adjectives": ["Тихий", "Заячий", "Пестрящий", "Заброшенный"],
        "nouns": ["луг", "пустошь", "поле", "выгон"],
    },
    "forest_edge": {
        "adjectives": ["Волчья", "Солнечный", "Курганная", "Ольховый"],
        "nouns": ["опушка", "край леса"],
    },
    "ruins": {
        "adjectives": ["Гнилые", "Обгорелые", "Старая"],
        "nouns": ["руины", "выселки", "часовня", "мельница"],
    },
    "deep_forest": {
        "adjectives": ["Чёрная", "Дремучий", "Гнилой", "Медвежий", "Звериная"],
        "nouns": ["чаща", "бор", "ельник", "овраг"],
    },
    "swamp": {
        "adjectives": ["Туманное", "Квакающее"],
        "nouns": ["болото", "трясина"],
    },
    "lair": {
        "adjectives": ["Троллья", "Огорова", "Волчья", "Паучья", "Грифонья"],
        "nouns": ["берлога", "пещера", "нора"],
    },
    "camp": {
        "adjectives": ["Добытчиков", "Трактирный", "Странников", "Костровой"],
        "nouns": ["лагерь", "стан"],
    },
}

# ---------------------------------------------------------------------------
# Пулы биомов для диких узлов
# ---------------------------------------------------------------------------
_WILD_BIOMES = [
    "road",
    "meadow",
    "meadow",          # +1 вес для meadow
    "forest_edge",
    "forest_edge",     # +1 вес
    "ruins",
    "deep_forest",
    "swamp",
]

# Весовые коэффициенты в зависимости от глубины
_DEPTH_WEIGHTS: dict[int, dict[str, int]] = {
    1: {"road": 3, "meadow": 2, "forest_edge": 1},
    2: {"road": 2, "meadow": 2, "forest_edge": 2, "ruins": 1},
    3: {"meadow": 1, "forest_edge": 2, "ruins": 2, "deep_forest": 2, "swamp": 1},
    4: {"ruins": 2, "deep_forest": 2, "swamp": 1, "forest_edge": 1},
    5: {"deep_forest": 2, "swamp": 2, "ruins": 1},
    6: {"deep_forest": 2, "swamp": 2},
}

# ---------------------------------------------------------------------------
# Слои глубины
# ---------------------------------------------------------------------------
_LAYER_DEFS = [
    {"depth": 0, "count": 1},
    {"depth": 1, "count": 3},
    {"depth": 2, "count": 5},
    {"depth": 3, "count": 5},
    {"depth": 4, "count": 5},
    {"depth": 5, "count": 4},
    {"depth": 6, "count": 2},
]

# ---------------------------------------------------------------------------
# Данные биомов из JSON
# ---------------------------------------------------------------------------

@dataclass
class BiomeData:
    biome_type: str
    p_spawn: float
    can_search: bool
    name_pool: dict[str, list[str]] | None = None


def _load_biomes(data_dir: str | Path) -> dict[str, BiomeData]:
    """Загружает все biome-файлы из data/biomes/."""
    biomes: dict[str, BiomeData] = {}
    biomes_path = Path(data_dir) / "biomes"
    if not biomes_path.exists():
        return biomes
    for fp in biomes_path.glob("biome_*.json"):
        with open(fp, encoding="utf-8") as f:
            raw = json.load(f)
        bt = raw.get("biomeType", "")
        name_pool = raw.get("namePool")
        biomes[bt] = BiomeData(
            biome_type=bt,
            p_spawn=raw.get("pSpawn", 0.25),
            can_search=raw.get("canSearch", True),
            name_pool=name_pool if name_pool else None,
        )
    return biomes


# ---------------------------------------------------------------------------
# A. Топология
# ---------------------------------------------------------------------------

def _build_topology(rng: random.Random) -> list[dict[str, Any]]:
    """Строит связный неориентированный граф из 25 узлов по слоям глубины."""

    # 1. Создаём узлы
    nodes: list[dict[str, Any]] = []
    layers: dict[int, list[int]] = {}  # depth -> list of node indices
    idx = 0
    for layer in _LAYER_DEFS:
        d = layer["depth"]
        count = layer["count"]
        start = idx
        for _ in range(count):
            nodes.append({
                "id": f"node_{idx:02d}",
                "depth": d,
                "connections": [],
            })
            idx += 1
        layers[d] = list(range(start, idx))

    # 2. Межслойные связи
    # node_00 (depth 0) -> все узлы depth 1
    for ni in layers[1]:
        _add_edge(nodes, 0, ni)

    # Узлы d >= 2 -> родитель из d-1 с наименьшей степенью
    for d in range(2, 7):
        for ni in layers[d]:
            parents = layers[d - 1]
            # Кандидаты со степенью < 4
            candidates = [p for p in parents if len(nodes[p]["connections"]) < 4]
            if not candidates:
                candidates = parents
            # Выбираем с наименьшей текущей степенью
            candidates.sort(key=lambda p: len(nodes[p]["connections"]))
            best = candidates[0]
            # При равенстве — случайный выбор среди лучших
            best_deg = len(nodes[best]["connections"])
            best_candidates = [p for p in candidates if len(nodes[p]["connections"]) == best_deg]
            parent = rng.choice(best_candidates)
            _add_edge(nodes, ni, parent)

    # 3. 1-2 случайных межслойных ребра для ветвистости
    for _ in range(2):
        d = rng.randint(2, 6)
        ni = rng.choice(layers[d])
        if len(nodes[ni]["connections"]) >= 4:
            continue
        parents = layers[d - 1]
        free = [p for p in parents if len(nodes[p]["connections"]) < 4]
        if free:
            parent = rng.choice(free)
            _add_edge(nodes, ni, parent)

    # 4. Устранение тупиков (степень 1 -> минимум 2)
    for d in range(1, 7):
        shuffled = list(layers[d])
        rng.shuffle(shuffled)
        for ni in shuffled:
            if len(nodes[ni]["connections"]) > 1:
                continue
            # Ищем соседа в том же слое
            same_layer = [x for x in layers[d] if x != ni and len(nodes[x]["connections"]) < 4]
            # Предпочтение узлам со степенью 1
            same_layer.sort(key=lambda x: len(nodes[x]["connections"]))
            if same_layer:
                _add_edge(nodes, ni, same_layer[0])
            else:
                # Соединяем с узлом d-1
                prev_layer = layers[d - 1]
                free = [p for p in prev_layer if len(nodes[p]["connections"]) < 4]
                if free:
                    _add_edge(nodes, ni, rng.choice(free))

    # Конвертируем connections из индексов в строковые ID
    for nd in nodes:
        nd["connections"] = [nodes[i]["id"] for i in nd["connections"]]

    return nodes


def _add_edge(nodes: list[dict], a: int, b: int) -> None:
    """Добавляет двустороннее ребро по индексам (без дубликатов и петель)."""
    if a == b:
        return
    conn_a = nodes[a]["connections"]
    if b in conn_a:
        return
    conn_a.append(b)
    nodes[b]["connections"].append(a)


# ---------------------------------------------------------------------------
# Б. Назначение биомов, названий и NPC
# ---------------------------------------------------------------------------

_CAMP_NPCS = ["npc_hunter_rask", "npc_wanderer_kit", "npc_herbalist_vela"]


def _generate_name(biome_type: str, rng: random.Random, used_names: set[str]) -> str:
    """Генерирует уникальное название для локации."""
    pool = _NAME_POOLS.get(biome_type, _NAME_POOLS["deep_forest"])
    adj = rng.choice(pool["adjectives"])
    noun = rng.choice(pool["nouns"])

    base = f"{adj} {noun}"
    if base not in used_names:
        return base

    # При исчерпании — суффикс
    suffix_num = 2
    while True:
        candidate = f"{base} №{suffix_num}"
        if candidate not in used_names:
            return candidate
        suffix_num += 1


def _assign_biomes_and_names(
    nodes: list[dict],
    rng: random.Random,
    region: int,
    biomes_data: dict[str, BiomeData],
) -> None:
    """Назначает типы, названия, NPC и параметры для каждого узла."""

    used_names: set[str] = set()

    # --- node_00 (деревня / лагерь) ---
    n0 = nodes[0]
    if region == 1:
        n0["type"] = "village"
        n0["name"] = "Приграничная деревня"
        n0["danger"] = 0
        n0["searchMax"] = 0
        n0["visited"] = True
        n0["spawnRolled"] = True
        n0["npcId"] = None
        used_names.add(n0["name"])
    else:
        n0["type"] = "camp"
        n0["name"] = _generate_name("camp", rng, used_names)
        n0["danger"] = 0
        n0["searchMax"] = 0
        n0["visited"] = True
        n0["spawnRolled"] = True
        n0["npcId"] = rng.choice(_CAMP_NPCS)
        used_names.add(n0["name"])

    # --- Логово (ровно 1 на depth 6) ---
    lair_candidates = [i for i, nd in enumerate(nodes) if nd["depth"] == 6 and i != 0]
    lair_idx = rng.choice(lair_candidates)
    nodes[lair_idx]["type"] = "lair"
    nodes[lair_idx]["name"] = _generate_name("lair", rng, used_names)
    nodes[lair_idx]["danger"] = 3
    nodes[lair_idx]["searchMax"] = 3 + 3  # 3 + danger
    nodes[lair_idx]["visited"] = False
    nodes[lair_idx]["spawnRolled"] = False
    nodes[lair_idx]["npcId"] = None
    used_names.add(nodes[lair_idx]["name"])

    # --- Остальные 23 узла (исключая node_00 и lair) ---
    wild_indices = [
        i for i in range(1, len(nodes))
        if i != lair_idx
    ]

    for idx in wild_indices:
        nd = nodes[idx]
        d = nd["depth"]

        # Опасность по глубине
        if d <= 2:
            danger = 1
        elif d <= 4:
            danger = 2
        else:
            danger = 3

        # Выбор биома с весами
        weights: dict[str, int] = _DEPTH_WEIGHTS.get(d, {})
        pool = _WILD_BIOMES[:]
        for bt, w in weights.items():
            pool.extend([bt] * (w - 1))  # уже есть 1 базовый вес

        biome_type = rng.choice(pool)
        nd["type"] = biome_type
        nd["danger"] = danger
        nd["searchMax"] = 3 + danger
        nd["visited"] = False
        nd["spawnRolled"] = False
        nd["npcId"] = None

        # NPC для camp
        if biome_type == "camp":
            nd["npcId"] = rng.choice(_CAMP_NPCS)

        nd["name"] = _generate_name(biome_type, rng, used_names)
        used_names.add(nd["name"])

    # --- Инициализация state для каждого узла ---
    for nd in nodes:
        nd["state"] = {
            "visited": nd.get("visited", False),
            "lookUsed": False,
            "searchCount": 0,
            "searchMax": nd.get("searchMax", 4),
            "searchDepleted": False,
            "spawnRolled": nd.get("spawnRolled", False),
            "monster": None,
            "lairQueue": None,
            "daysSinceCleared": None,
        }


# ---------------------------------------------------------------------------
# В. Валидация
# ---------------------------------------------------------------------------

def _p_spawn_for_type(biome_type: str) -> float:
    """Возвращает pSpawn для типа локации (§28.1)."""
    mapping = {
        "village": 0.00,
        "camp": 0.10,
        "road": 0.25,
        "meadow": 0.25,
        "forest_edge": 0.35,
        "ruins": 0.35,
        "deep_forest": 0.45,
        "swamp": 0.40,
        "lair": 1.00,
    }
    return mapping.get(biome_type, 0.25)


def validate_region_nodes(nodes: list[dict], _game_data: Any = None) -> bool:
    """Валидирует сгенерированный регион по правилам §28.2, §29.1, §29.2."""

    # 1. Количество узлов
    if len(nodes) != 25:
        return False

    # 2. Степени
    if len(nodes[0]["connections"]) != 3:
        return False
    for i in range(1, 25):
        deg = len(nodes[i]["connections"])
        if deg < 2 or deg > 4:
            return False

    # 3. Зеркальность и отсутствие петель
    for i, nd in enumerate(nodes):
        for conn_id in nd["connections"]:
            if conn_id == i:
                return False
            if conn_id not in nodes[i]["connections"]:
                return False
        # Нет дубликатов
        if len(nd["connections"]) != len(set(nd["connections"])):
            return False

    # 4. Связность (BFS)
    id_map = {nd["id"]: nd for nd in nodes}
    visited = set()
    queue = ["node_00"]
    visited.add("node_00")
    while queue:
        curr_id = queue.pop(0)
        for conn_id in id_map[curr_id]["connections"]:
            if conn_id not in visited:
                visited.add(conn_id)
                queue.append(conn_id)
    if len(visited) != 25:
        return False

    # 5. Логово
    lairs = [nd for nd in nodes if nd["type"] == "lair"]
    if len(lairs) != 1:
        return False
    if lairs[0]["depth"] != 6:
        return False

    # 6. Плотность спавна
    wild_nodes = [nd for nd in nodes if nd["type"] not in ("village", "lair")]
    if not wild_nodes:
        return False
    avg_density = sum(_p_spawn_for_type(nd["type"]) for nd in wild_nodes) / len(wild_nodes)
    if not (0.20 <= avg_density <= 0.50):
        return False

    return True


# ---------------------------------------------------------------------------
# Г. Главная функция
# ---------------------------------------------------------------------------

def generate_region(seed: int, region: int, _game_data: Any = None) -> dict[str, Any]:
    """
    Генерирует карту региона.
    Перебирает attempt_seed = seed + attempt до 1000 раз.
    """
    for attempt in range(1000):
        rng = random.Random(seed + attempt)
        nodes = _build_topology(rng)
        _assign_biomes_and_names(nodes, rng, region, {})

        if validate_region_nodes(nodes, _game_data):
            return {
                "region": region,
                "seedUsed": seed + attempt,
                "currentNodeId": "node_00",
                "nodes": nodes,
            }

    raise RuntimeError("Failed to generate valid region map")


# ---------------------------------------------------------------------------
# Д. Переход в «Дальние тропы»
# ---------------------------------------------------------------------------

def enter_next_region(state: dict, _game_data: Any = None) -> tuple[dict, list[dict]]:
    """
    Переход в следующий регион (§29.2 п.6).
    Возвращает (new_state, events).
    """
    world = state.get("world", {})
    if world.get("inCombat"):
        return state, [{"id": "err_in_combat"}]

    map_data = state.get("map", {})
    current_node_id = map_data.get("currentNodeId", "node_00")
    nodes = map_data.get("nodes", [])
    current_node = None
    for nd in nodes:
        if nd["id"] == current_node_id:
            current_node = nd
            break

    if not current_node or current_node.get("type") != "lair":
        return state, [{"id": "err_not_in_lair"}]

    lair_state = current_node.get("state", {})
    if lair_state.get("monster") is not None or lair_state.get("lairQueue"):
        return state, [{"id": "err_lair_not_cleared"}]

    current_region = state["meta"]["region"]

    # Архивируем текущий регион
    state.setdefault("archivedRegions", {})
    state["archivedRegions"][str(current_region)] = copy.deepcopy(map_data)

    # Новый регион
    new_region = current_region + 1
    state["meta"]["region"] = new_region

    # Новый сид
    next_seed = state["meta"]["seed"] + new_region * 10007

    # Генерируем новую карту
    new_map = generate_region(state["meta"]["seed"], new_region, _game_data)

    # Обновляем state
    state["map"] = new_map
    state["world"]["locationsVisited"] = world.get("locationsVisited", 0) + 1

    event = {
        "id": "region_changed",
        "region": new_region,
        "entryNodeName": new_map["nodes"][0]["name"],
    }

    return state, [event]
