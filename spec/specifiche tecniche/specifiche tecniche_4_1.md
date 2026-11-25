ТЗ на разработку — Блок 4.1: Процедурный генератор графа региона и переход в «Дальние тропы»

1. Цель задачи

Реализовать детерминированный процедурный генератор карты региона (engine/worldgen.py) и генератор эталонного стартового сохранения (scripts/generate_template.py) по правилам §28, §29, §30 и §31.3 спеки. Модуль должен строить связный неориентированный граф из 25 узлов по слоям глубины 0..6, проверять степени узлов (2..4) и плотность спавна (0.20..0.50), присваивать уникальные названия локаций, размещать NPC и обеспечивать переход в следующий регион («Дальние тропы», region + 1) после зачистки логова.

2. Архитектурные ограничения и структуры данных

• Чистые функции без побочных эффектов: Модуль engine/worldgen.py не использует print(), input() и глобальный random — все случайные выборы идут строго через переданный экземпляр rng = random.Random(seed).
• Детерминизм: Одинаковый seed и region всегда дают идентичный граф, названия и размещение NPC. При провале валидации графа или плотности спавна генератор инкрементирует рабочий сид (attempt_seed = base_seed + attempt).
• Контракт узла карты (node):
{
  "id": "node_07",
  "type": "forest_edge",
  "name": "Курганская опушка",
  "danger": 1,
  "depth": 2,
  "connections": ["node_01", "node_09"],
  "npcId": null,
  "state": {
    "visited": false,
    "lookUsed": false,
    "searchCount": 0,
    "searchMax": 4,
    "searchDepleted": false,
    "spawnRolled": false,
    "monster": null,
    "lairQueue": null,
    "daysSinceCleared": null
  }
}

• Примечание: Для type == "village" поле npcId не используется (в деревне доступны все 5 деревенских NPC из пула §31.3), для type == "camp" в npcId записывается ID одного выбранного лагерного NPC.

3. Структура файлов (создать)
project_root/
├── engine/
│   └── worldgen.py              # Генератор графа региона, валидация, переход в region + 1
├── scripts/
│   └── generate_template.py     # Скрипт генерации эталонного state_template.json (seed 20260101)
└── tests/
    └── test_worldgen.py         # Тесты графа, степеней, связности, плотности, имён и Дальних троп


4. Детальные требования к модулю engine/worldgen.py


А. Топология слоёв и построение рёбер (_build_topology(rng: random.Random) -> list[dict])

1. Распределение 25 узлов по слоям (depth 0..6, §29.2):
	• depth 0: 1 узел (node_00).
	• depth 1: 3 узла (node_01..node_03).
	• depth 2: 5 узлов (node_04..node_08).
	• depth 3: 5 узлов (node_09..node_13).
	• depth 4: 5 узлов (node_14..node_18).
	• depth 5: 4 узла (node_19..node_22).
	• depth 6: 2 узла (node_23..node_24).
2. Межслойные связи (d >= 1 к d - 1):
	• Узел node_00 (depth 0) соединяется со всеми 3 узлами depth 1 (итоговая степень node_00 строго 3, боковые рёбра к node_00 не добавляются).
	• Для каждого узла u слоя d >= 2 выбирается родитель v из слоя d - 1 с наименьшей текущей степенью (при равенстве — случайный выбор через rng.choice среди кандидатов со степенью < 4).
	• После первичной привязки для повышения ветвистости можно добавить 1–2 случайных межслойных ребра между узлами со степенью < 3.
3. Устранение тупиков (степень 1 -> минимум 2, §29.2):
	• Проходим по всем узлам слоёв d >= 1 в перемешанном через rng порядке.
	• Если у узла u степень == 1, соединяем его с другим узлом w того же слоя d, у которого текущая степень < 4 (предпочтение отдаём узлам со степенью 1, затем < 4). Если в слое нет свободного соседа (например, на depth 6 оба уже соединены или у второго степень 4), соединяем с узлом слоя d - 1 со степенью < 4.

Б. Назначение типов биомов, названий и NPC (_assign_biomes_and_names(...))

1. Стартовый узел node_00:
	• Если region == 1: type = "village", name = "Приграничная деревня", danger = 0, searchMax = 0, visited = true, spawnRolled = true.
	• Если region > 1 («Дальние тропы», §29.2 п.6): type = "camp", уникальное лагерное имя, danger = 0, searchMax = 0, visited = true, spawnRolled = true, и в npcId назначается случайный NPC из пула ["npc_hunter_rask", "npc_wanderer_kit", "npc_herbalist_vela"].
2. Логово (lair):
	• Выбирается ровно 1 случайный узел на максимальной глубине (depth == 6): type = "lair", danger = 3 (базово), searchMax = 3 + danger.
3. Остальные 23 диких узла (node_01..node_24 без логова):
	• Типы выбираются взвешенно из пула диких локаций (camp, road, meadow, forest_edge, ruins, deep_forest, swamp) с опорой на biomes/*.json (из GameData) и с учётом depth (например, camp не более 1–2 на регион, deep_forest и swamp чаще на depth >= 3).
	• Опасность (danger, §29.2): depth 1..2 -> 1, depth 3..4 -> 2, depth 5..6 -> 3.
	• Запас поиска (searchMax, §8.3): 0 для village, иначе 3 + danger.
	• Если узел получил type == "camp", в npcId записывается случайный NPC из пула ["npc_hunter_rask", "npc_wanderer_kit", "npc_herbalist_vela"] (§31.3).
4. Генератор уникальных названий (§30.2):
	• Использует пулы прилагательных и существительных из data/biomes/*.json (или встроенный справочник §30.2: road, meadow, forest_edge, ruins, deep_forest, swamp, lair, camp).
	• Гарантирует отсутствие дубликатов name внутри одного региона (хранит used_names: set[str]; при исчерпании комбинаций добавляет суффикс вида " №2" / " (дальняя)").

В. Валидация региона (validate_region_nodes(nodes: list[dict], game_data: GameData) -> bool)

Генерация считается успешной только если выполнены все условия (§28.2, §29.1, §29.2):
1. Количество узлов: ровно 25.
2. Степени узлов: у node_00 степень ровно 3; у каждого из остальных 24 узлов степень в диапазоне 2..4.
3. Зеркальность и отсутствие петель: нет рёбер A -> A, нет дублей в connections, и для каждого B in A["connections"] выполняется A in B["connections"].
4. Связность: обход в ширину (BFS) от node_00 посещает все 25 узлов.
5. Логово: в графе ровно 1 узел с type == "lair", и он находится на depth == 6.
6. Контроль плотности спавна (§28.2):
	• Берём все дикие узлы (исключая node_00 и узел с type == "lair", итого 23 узла).
	• Считаем ожидаемую плотность: avg_density = sum(pSpawn(node["type"]) for node in wild_nodes) / len(wild_nodes).
	• Требуется 0.20 <= avg_density <= 0.50.

Г. Главная функция генерации (generate_region(seed: int, region: int, game_data: GameData) -> dict)

• Перебирает attempt от 0 до 1000, создавая rng = random.Random(seed + attempt).
• Строит топологию, назначает типы, названия, NPC и прогоняет validate_region_nodes.
• При успехе возвращает структуру карты региона:
{
    "region": region,
    "seedUsed": seed + attempt,
    "currentNodeId": "node_00",
    "nodes": nodes,
}
• Если за 1000 попыток не удалось (защита от бесконечного цикла), бросает RuntimeError("Failed to generate valid region map").

Д. Переход в «Дальние тропы» (enter_next_region(state: dict, game_data: GameData) -> tuple[dict, list[dict]])

Реализует §29.2 п.6 и §30.1:
1. Проверяет, что world["inCombat"] is False.
2. Проверяет, что игрок находится в узле логова (current_node["type"] == "lair") и логово зачищено (current_node["state"]["monster"] is None и not current_node["state"].get("lairQueue")) — иначе возвращает событие {"id": "err_lair_not_cleared"}.
3. Сохраняет текущую карту в архив пройденных регионов state.setdefault("archivedRegions", {})[str(current_region)] = copy.deepcopy(state["map"]) (чтобы обеспечить возможность возврата, как указано в §29.2).
4. Увеличивает new_region = state["meta"]["region"] + 1, state["meta"]["region"] = new_region.
5. Вычисляет свежий детерминированный сид: next_seed = state["meta"]["seed"] + new_region * 10007.
6. Генерирует новую карту через generate_region(next_seed, region=new_region, game_data=game_data) (где node_00 — лагерь со случайным NPC, а тиры монстров при спавне в следующих регионах сдвигаются на +(region - 1) с капом на Tier 5).
7. Заменяет state["map"] на новую карту (currentNodeId = "node_00"), увеличивает state["world"]["locationsVisited"] += 1.
8. Возвращает (new_state, [{"id": "region_changed", "region": new_region, "entryNodeName": new_map["nodes"][0]["name"]}]).

5. Генератор эталонного шаблона (scripts/generate_template.py)

• Скрипт загружает GameData из data/, вызывает generate_region(seed=20260101, region=1, game_data=game_data) и собирает полный валидный state_template.json (schemaVersion = 1, meta.seed = 20260101, meta.region = 1, стартовый игрок §11, world §32.3, npcs со всеми 7 NPC в статусе neutral, flags).
• Сохраняет state_template.json в корень проекта и прогоняет через валидатор сейва из блока 1.1.

6. Критерии приёмки (tests/test_worldgen.py)

1. Детерминизм: два вызова generate_region(20260101, 1, game_data) дают побайтово идентичный результат.
2. Инварианты графа: 25 узлов, node_00 имеет тип village и степень 3, все остальные узлы имеют степень 2..4, все связи зеркальны, граф полностью связен от node_00, ровно 1 lair на depth == 6.
3. Плотность спавна: для серии из 20 разных сидов средняя плотность спавна диких узлов всегда попадает в [0.20, 0.50].
4. Уникальность имён: все 25 узлов в регионе имеют попарно различные name.
5. Переход в «Дальние тропы»: невозможность перейти при живом боссе в логове (err_lair_not_cleared); после зачистки логова enter_next_region архивирует регион 1, выставляет meta.region == 2, ставит игрока в node_00 типа camp с назначенным npcId.
