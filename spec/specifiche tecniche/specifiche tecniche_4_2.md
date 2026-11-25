ТЗ на разработку — Блок 4.2: Перемещение, стелс («Осмотреться»), засады и «Поиск»

1. Цель задачи

Реализовать модуль исследования мира (engine/exploration.py) по правилам §7.1, §8, §9.2, §22.3, §27, §28, §29.2 и §30.1 спеки. Модуль должен управлять перемещением между связанными узлами карты (с ленивым спавном монстров при первом входе и проверкой засады), действием «Осмотреться», действием «Поиск» с истощением локации и биомными сдвигами весов лута, а также ожиданием (пропуском 1 AP).

2. Архитектурные ограничения и структуры данных

• Чистые функции без побочных эффектов: Никакого print(), input() и глобального random. Все случайные броски идут строго через переданный rng: random.Random. Сигнатура всех публичных функций: (state, ..., game_data, rng=None, session_path=..., template_path=...) -> tuple[dict, list[dict]].
• Атомарный порядок проверки смерти от голода: Любое действие, тратящее 1 AP, сначала вызывает advance_time(state, steps=1, ...). Если в результате тика времени игрок погиб от голода или DoT (new_state["world"]["inCombat"] сброшен и сработал handle_player_death), функция немедленно возвращает (new_state, events) без выполнения дальнейших эффектов действия.
• Инициализация монстров с учётом региона и сложности:
	• Целевой тир монстра при спавне: target_tier = clamp(node["danger"] + (state["meta"]["region"] - 1), 1, 5) (для логова lair босс берётся на тир выше базовой опасности: clamp(3 + (region - 1) + 1, 1, 5), в регионе 1 — mob_troll_hill + 2 × mob_bandit_rogue).
	• При создании экземпляра монстра в node["state"] его maxHp масштабируется на diff_mult = state["meta"].get("difficultyMultiplier", 1.0): scaled_hp = max(1, round(base_hp * diff_mult)).

3. Структура файлов (создать)
project_root/
├── engine/
│   └── exploration.py           # Перемещение, ленивый спавн, засады, осмотр, поиск, ожидание
└── tests/
    └── test_exploration.py      # Тесты перемещения, засад, осмотра, поиска, истощения и сдвигов биома


4. Детальные требования к модулю engine/exploration.py


А. Ленивый спавн монстра при первом посещении (_roll_node_spawn(state: dict, node: dict, game_data: GameData, rng: random.Random) -> None)

Вызывается при входе в узел, если node["state"]["spawnRolled"] is False:
1. Устанавливает node["state"]["spawnRolled"] = True.
2. Если node["type"] == "village": оставляет monster = None, выходит.
3. Особый случай — Логово (node["type"] == "lair", §27.4, §30.1):
	• Формирует lairQueue из 3 противников (2 стража + 1 босс):
		• В регионе 1: [mob_bandit_rogue, mob_bandit_rogue, mob_troll_hill].
		• В регионах 2+: 2 элитных/обычных врага тира min(5, 2 + region - 1) и босс тира min(5, 4 + region - 1) из пула логова/тиров.
	• Каждый элемент очереди имеет вид {"mobId": mob_id, "revealed": False, "hp": scaled_hp, "maxHp": scaled_hp}.
	• Устанавливает node["state"]["monster"] = copy.deepcopy(lairQueue[0]).
4. Обычная дикая локация (§28.1, §30.1):
	• Берёт p_spawn для node["type"] (camp: 0.10, road: 0.25, meadow: 0.25, forest_edge: 0.35, ruins: 0.35, deep_forest: 0.45, swamp: 0.40).
	• Если rng.random() <= p_spawn:
		• Выбирает пул мобов по node["type"] (из biomes/*.json или справочника §30.1: road, meadow, forest_edge, ruins, deep_forest, swamp).
		• Фильтрует мобов пула по tier == target_tier; если точных совпадений нет — берёт мобов из пула с ближайшим тиром (а если пул пуст — любого моба из game_data с tier == target_tier).
		• Выбирает mob_id = rng.choice(candidates), масштабирует HP на difficultyMultiplier и записывает в node["state"]["monster"] = {"mobId": mob_id, "revealed": False, "hp": scaled_hp, "maxHp": scaled_hp}.

Б. Перемещение в соседний узел (move_to_node(state: dict, target_node_id: str, game_data: GameData, rng: random.Random | None = None, session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]])

Реализует §7.1, §27.1–27.2, §28.2, §29.3:
1. Валидация:
	• Проверяет world["inCombat"] is False (иначе err_in_combat).
	• Проверяет, что target_node_id присутствует в current_node["connections"] (иначе err_invalid_connection).
2. Трата 1 AP (§7.1):
	• Вызывает advance_time(state, steps=1, ...). Если игрок погиб (например, от голода на шаге 7/17 или от DoT), возвращает результат гибели.
3. Обновление позиции и флагов узла (§27.1, §32.3):
	• state["map"]["currentNodeId"] = target_node_id.
	• Сбрасывает target_node["state"]["lookUsed"] = False (осмотр доступен 1 раз на каждый вход).
	• Если target_node["state"]["visited"] is False: ставит visited = True и увеличивает state["world"]["locationsVisited"] += 1.
	• Если target_node["state"]["spawnRolled"] is False: вызывает _roll_node_spawn(state, target_node, game_data, rng).
	• Добавляет событие {"id": "moved_to_node", "nodeId": target_node_id, "name": target_node["name"], "type": target_node["type"]}.
4. Проверка засады (§27.2):
	• Проверяет, есть ли в target_node["state"] живой монстр (monster is not None) и не раскрыт ли он (monster["revealed"] is False).
	• Если не раскрыт:
		• Считает шанс засады: scavenging = state["player"]["skills"]["scavenging"], ambush_chance = max(5, 15 - scavenging).
		• Бросает rng.randint(0, 100) <= ambush_chance.
		• Если засада сработала: добавляет событие {"id": "ambush_triggered", "mobId": monster["mobId"]} и немедленно запускает принудительный бой через start_combat(state, game_data, is_ambush=True, rng=rng, ...) (0 дополнительных AP, монстр атакует первым без броска инициативы).
		• Если засада не сработала: монстр остаётся скрытым (revealed == False).

В. Осмотреться (look_around(state: dict, game_data: GameData, rng: random.Random | None = None, session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]])

Реализует §7.1 и §27.1:
1. Проверяет world["inCombat"] is False.
2. Проверяет current_node["state"]["lookUsed"] is False (иначе возвращает событие {"id": "err_already_looked"}, AP не тратится).
3. Тратит 1 AP через advance_time(state, steps=1, ...); если игрок погиб — возвращает результат гибели.
4. Устанавливает current_node["state"]["lookUsed"] = True.
5. Если в current_node["state"]["monster"] есть враг:
	• Ставит monster["revealed"] = True (персистентно навсегда для этого экземпляра монстра).
	• Если это логово и есть lairQueue, помечает lairQueue["revealed"] = True.
	• Возвращает (new_state, events + [{"id": "look_found_monster", "mobId": monster["mobId"], "isLair": current_node["type"] == "lair"}]).
6. Если монстра нет:
	• Возвращает (new_state, events + [{"id": "look_clear"}]).

Г. Поиск (scavenge_node(state: dict, game_data: GameData, rng: random.Random | None = None, session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]])

Реализует §8, §9.2, §22.3 и §30.1:
1. Валидация:
	• Проверяет world["inCombat"] is False.
	• Запрет поиска в деревне (current_node["type"] == "village" или searchMax <= 0 -> err_cannot_search_here).
	• Проверка истощения (current_node["state"]["searchDepleted"] is True или searchCount >= searchMax -> err_search_depleted).
2. Трата 1 AP (§8):
	• Вызывает advance_time(state, steps=1, ...). Если игрок погиб — возвращает результат гибели.
3. Обновление счётчика истощения (§8.3):
	• current_node["state"]["searchCount"] += 1.
	• Если searchCount >= searchMax: ставит current_node["state"]["searchDepleted"] = True.
4. Расчёт весов категорий (§8.1, §9.2, §22.3, §30.1):
	• Базовые веса: nothing = 35.0, food = 35.0, junk = 20.0, weapon = 7.0, armor = 3.0.
	• Биомные сдвиги (§30.1):
		• road: junk += 10.0, nothing -= 10.0.
		• meadow или forest_edge: food += 10.0, nothing -= 10.0.
		• ruins: weapon += 5.0, armor += 5.0, nothing -= 10.0.
		• deep_forest или swamp: food += 10.0, nothing -= 10.0 (и при выпадении food повышается вес грибов/мха: food_mushrooms, food_moss, food_red_mushroom).
	• Бонус Интеллекта (§9.2): intel_bonus = (player["attributes"]["intelligence"] - 1) * 1.5.
	• Бонус перка «Зоркий глаз» (scavenging >= 3, §22.3): perk_bonus = 15.0 if player["skills"]["scavenging"] >= 3 else 0.0.
	• Применение бонусов снижения пустого исхода: reduction = min(nothing, intel_bonus + perk_bonus). Уменьшаем nothing -= reduction и пропорционально (или в food/junk) перераспределяем reduction в положительные категории (например, 60% в food, 30% в junk, 10% в weapon/armor).
5. Ролл категории и выбор конкретного предмета:
	• Взвешенный выбор категории по итоговым весам через rng.uniform(0, total_weight).
	• Если выпало nothing: событие {"id": "scavenge_nothing", "depleted": current_node["state"]["searchDepleted"]}.
	• Если выпала предметная категория (food, junk, weapon, armor):
		• Фильтруем предметы категории из game_data:
			• По умолчанию берём только предметы с economy.canFind is True.
			• Перк «Чутьё кладоискателя» (scavenging >= 10, §22.3): с вероятностью 2% (rng.random() <= 0.02) разрешаем выбор из пула редких предметов категории с economy.canFind is False (например, wpn_sword_fine, arm_leather_fine, food_boiled_potatoes).
			• Для weapon и armor дополнительно фильтруем по тиру локации (item_tier <= target_tier, где target_tier = clamp(danger + region - 1, 1, 5)).
		• Добавляем 1 шт. выбранного предмета в инвентарь через add_item(state, item_id, 1, game_data).
		• Возвращаем событие {"id": "scavenge_found", "category": chosen_cat, "itemId": item_id, "depleted": current_node["state"]["searchDepleted"]}.

Д. Ожидание (wait_step(state: dict, game_data: GameData, rng: random.Random | None = None, session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]])

Реализует команду [9] Ждать (1 AP) из §7.1 и §33.1:
1. Проверяет world["inCombat"] is False.
2. Вызывает advance_time(state, steps=1, ...) (двигается время, тикает естественная регенерация HP/MP и активные эффекты).
3. Возвращает (new_state, events + [{"id": "waited_one_step"}]).

5. Критерии приёмки (tests/test_exploration.py)

1. Перемещение и ленивый спавн: переход в неподключённый узел отклоняется (err_invalid_connection); переход в соседний тратит 1 AP, устанавливает visited = True, lookUsed = False и однократно запускает spawnRolled = True.
2. Засада и навык scavenging: при входе в узел со скрытым монстром засада запускает бой без траты дополнительного AP (isAmbush == True, монстр ходит первым); при scavenging == 10 шанс засады не превышает 5%, а после пережитой засады/побега повторный вход в узел никогда не вызывает засаду (revealed == True).
3. Осмотреться (look_around): тратит 1 AP, раскрывает монстра (revealed = True), повторный вызов в том же посещении возвращает err_already_looked без траты AP, а после выхода и повторного захода флаг lookUsed сбрасывается.
4. Поиск и истощение (scavenge_node): в деревне возвращает err_cannot_search_here; в дикой локации за 3 + danger попыток доводит searchDepleted до True, после чего дальнейший поиск блокируется (err_search_depleted).
5. Биомные сдвиги и перки: статистика 2000 бросков scavenge_node подтверждает повышение доли junk на тракте (road), food на лугу (meadow), снаряжения в руинах (ruins), снижение пустых исходов при высоком intelligence и scavenging >= 3, а также возможность найти предмет с canFind == False при scavenging == 10.
