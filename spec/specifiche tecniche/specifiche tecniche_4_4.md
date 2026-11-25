ТЗ на разработку — Блок 4.4: Сервисы деревни, торговля и репутация NPC

1. Цель задачи

Реализовать модуль торговли и взаимодействия с сервисами NPC (engine/trade.py) по правилам §7.1, §16.2, §26.2, §31 и канону #2 (§35) спеки. Модуль должен проверять доступность конкретного NPC в текущей локации (деревня или лагерь), рассчитывать цены покупки и продажи с учётом reputation и активных временных скидок (discount_10), исполнять сделки купли/продажи без траты AP, а также предоставлять прямой доступ к сервисам кузнеца Колма (ремонт экипировки за золото) и трактирщика Бориса (ночлег за 5 золота).

2. Архитектурные ограничения и структуры данных

• Чистые функции без побочных эффектов: Никакого print(), input() и глобального random.
• Время суток: Диалоги и торговля с NPC не тратят AP (§7.1). Ночлег у Бориса перематывает время на следующее утро (rest_at_inn из блока 2.3).
• Шкала репутации (REPUTATION_LEVELS, §31.1):
	• Упорядоченный список уровней: ["hated", "hostile", "neutral", "friendly", "honored"] (индексы 0..4).
	• Вспомогательная функция shift_reputation(state: dict, npc_id: str, delta: int) -> str: сдвигает индекс в REPUTATION_LEVELS с клампом в [0, 4] и сохраняет в state["npcs"][npc_id]["reputation"].
• Проверка присутствия NPC (is_npc_present(state: dict, npc_id: str) -> bool, §31.2–31.3):
	• В узле type == "village" присутствуют все 5 деревенских NPC: {"npc_elder_miroslav", "npc_merchant_ganna", "npc_blacksmith_kolm", "npc_innkeeper_boris", "npc_herbalist_vela"}.
	• В узле type == "camp" присутствует только один NPC, указанный в current_node.get("npcId").
	• В остальных узлах NPC отсутствуют.

3. Структура файлов (создать)
project_root/
├── engine/
│   └── trade.py                 # Проверка доступности NPC, расчёт цен, покупка/продажа, сервисы Колма и Бориса
└── tests/
    └── test_trade.py            # Тесты репутации, скидок, ассортимента NPC, купли/продажи и сервисов деревни


4. Детальные требования к модулю engine/trade.py


А. Расчёт цен покупки и продажи (get_buy_price(...) и get_sell_price(...), §26.2, §31.1)

1. Цена покупки у NPC (get_buy_price(item_data: dict, npc_state: dict, world_flags: dict | None = None) -> int):
	• Базовая цена: base_buy = item_data["economy"]["buyPrice"].
	• Модификатор репутации:
		• Если reputation == "friendly": скидка 5% (mult = 0.95, §31.1: «friendly открывает скидки»).
		• Если reputation == "honored": скидка 10% (mult = 0.90).
		• Иначе: mult = 1.0.
	• Временная диалоговая скидка (discount_10, §26.2): если у NPC или в world_flags активна скидка 10% (например, npc_state.get("tempDiscount10") is True), применяем дополнительный множитель 0.90 и сбрасываем флаг после совершения сделки (или до конца диалога).
	• Итоговая цена: max(1, round(base_buy * mult)) (если base_buy > 0, иначе 0).
2. Цена продажи игроком (get_sell_price(item_data: dict, npc_state: dict) -> int):
	• Базовая цена: base_sell = item_data["economy"]["sellPrice"].
	• Если base_sell <= 0: возвращаем 0 (такой хлам/мох NPC принимает за 0 монет или не покупает за деньги).
	• Модификатор репутации (§31.1):
		• Если reputation == "honored": бонус +5% к цене продажи (mult = 1.05).
		• Иначе: mult = 1.0.
	• Итоговая цена: max(1, round(base_sell * mult)).

Б. Покупка предмета у NPC (buy_item(state: dict, npc_id: str, item_id: str, count: int, game_data: GameData) -> tuple[dict, list[dict]])

Реализует §7.1, §31.1–31.3:
1. Валидация (без траты AP):
	• Проверяет world["inCombat"] is False (иначе err_in_combat) и count >= 1.
	• Проверяет is_npc_present(state, npc_id) (иначе err_npc_not_here).
	• Загружает профиль NPC из game_data.npcs[npc_id].
	• Проверяет репутацию: если reputation in ("hated", "hostile") — возвращает {"id": "err_npc_refuses_trade", "reason": "hostile"} (§31.1).
	• Проверяет, что NPC вообще торгует и item_id входит в его торговый ассортимент (npc_profile.get("shopInventory") / разрешённые категории NPC по таблице §31.2: у Ганны — еда, зелья, базовые расходники; у Колма — оружие и броня; у Велы — зелья, эликсиры, рецепты/ингредиенты; у Бориса — еда; у Раска — покрытия и охотничьи припасы) и у предмета economy.canBuy is True. Иначе — {"id": "err_item_not_sold_by_npc"}.
	• Считает общую стоимость: total_cost = get_buy_price(item_data, npc_state) * count.
	• Проверяет золото: если player["gold"] < total_cost — возвращает {"id": "err_not_enough_gold", "required": total_cost, "current": player["gold"]}.
2. Исполнение сделки:
	• Списывает player["gold"] -= total_cost.
	• Выдаёт count единиц item_id в player["inventory"] через add_item(state, item_id, count, game_data).
	• Если была активна разовая tempDiscount10, сбрасывает npc_state["tempDiscount10"] = False.
	• Возвращает (new_state, [{"id": "item_bought", "npcId": npc_id, "itemId": item_id, "count": count, "goldSpent": total_cost}]).

В. Продажа предмета NPC (sell_item(state: dict, npc_id: str, item_id: str, count: int, game_data: GameData) -> tuple[dict, list[dict]])

Реализует §7.1, §31.1–31.2:
1. Валидация (без траты AP):
	• Проверяет world["inCombat"] is False и count >= 1.
	• Проверяет is_npc_present(state, npc_id) (иначе err_npc_not_here).
	• Проверяет репутацию: если reputation in ("hated", "hostile") — возвращает {"id": "err_npc_refuses_trade", "reason": "hostile"}.
	• Проверяет, что NPC является торговцем/скупщиком (в пуле §31.2 скупку ведут как минимум npc_merchant_ganna, npc_blacksmith_kolm, npc_herbalist_vela, npc_innkeeper_boris, npc_hunter_rask; npc_elder_miroslav не торгует — err_npc_not_trader).
	• Проверяет наличие count единиц item_id в player["inventory"] (иначе err_not_enough_items).
2. Исполнение сделки:
	• Считает выручку: unit_price = get_sell_price(item_data, npc_state), total_gain = unit_price * count.
	• Удаляет count единиц item_id из инвентаря через remove_item(state, item_id, count).
	• Начисляет player["gold"] += total_gain.
	• Возвращает (new_state, [{"id": "item_sold", "npcId": npc_id, "itemId": item_id, "count": count, "goldEarned": total_gain}]).

Г. Сервисные обёртки деревни (use_smith_repair(...) и use_inn_rest(...))

Чтобы CLI и будущий Godot UI вызывали единый фасад сервисов деревни с проверкой присутствия нужного NPC:
1. use_smith_repair(state: dict, slot: str, game_data: GameData, session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]:
	• Проверяет is_npc_present(state, "npc_blacksmith_kolm") (иначе err_npc_not_here) и reputation != "hated" (при hated Колм отказывает в ремонте — err_npc_refuses_service).
	• Делегирует расчёт цены и починку в repair_at_smith(state, slot, game_data, ...) из блока 2.2 (учитывая перк crafting >= 6 на скидку -30% и трату 1 AP).
2. use_inn_rest(state: dict, game_data: GameData, rng: random.Random | None = None, session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]:
	• Проверяет is_npc_present(state, "npc_innkeeper_boris") (иначе err_npc_not_here) и reputation != "hated".
	• Делегирует ночлег за 5 золота в rest_at_inn(state, game_data, rng=rng, ...) из блока 2.3 (перемотка на stepOfDay = 1, day += 1, закрытие ужина, тик регена).

5. Критерии приёмки (tests/test_trade.py)

1. Присутствие NPC: в node_00 (village) доступны все 5 деревенских NPC; в дикой локации (forest_edge) любая попытка торговли/ремонта/ночлега возвращает err_npc_not_here; в лагере (camp) доступен только назначенный node["npcId"].
2. Влияние репутации: при reputation == "hostile" или "hated" покупка и продажа отклоняются (err_npc_refuses_trade); при reputation == "friendly" цена покупки снижается; при reputation == "honored" цена продажи возрастает на +5%.
3. Покупка и продажа: buy_item корректно списывает золото и добавляет предмет в инвентарь (и отклоняет при нехватке золота err_not_enough_gold); sell_item удаляет предмет и начисляет золото без траты AP.
4. Сервисы деревни: use_smith_repair работает только при наличии Колма в деревне и чинит слот; use_inn_rest работает только при наличии Бориса и переводит время на следующее утро за 5 золота.
