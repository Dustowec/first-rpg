ТЗ на разработку — Блок 4.3: Ремесло (Алхимия, Кулинария и Кузнечное дело)

1. Цель задачи

Реализовать систему ремесла и полевого/верстачного улучшения экипировки (engine/crafting.py) по правилам §14, §15, §16.2, §17 и §22.3 спеки. Модуль должен проверять доступность рабочего места (поле, костёр, верстак), минимальный порог навыка (alchemy или crafting), наличие ингредиентов, тратить 1 AP на операцию, учитывать перк «Экономный алхимик» (25% шанс сохранения ингредиентов), а также обеспечивать бесплатную полевую заточку оружия (crafting >= 3) и перманентное укрепление снаряжения на верстаке (crafting == 10).

2. Архитектурные ограничения и структуры данных

• Чистые функции без побочных эффектов: Никакого print(), input() и глобального random. Все случайные проверки (сохранение ингредиентов) выполняются через переданный rng: random.Random.
• Порядок траты времени и гибели от голода: Крафт рецепта и укрепление на верстаке тратят 1 AP через advance_time(state, steps=1, ...). Сначала проверяются все предусловия (вне боя, рабочее место, навык, ингредиенты/золото); если они не выполнены — возвращается ошибка с кодом err_* без списания AP и ресурсов. Если предусловия выполнены — списываются ресурсы, выдаётся результат и вызывается advance_time(state, steps=1, ...).
• Определение доступных станций в текущем узле (_get_available_stations(state: dict) -> set[str]):
	• "any" (полевые условия): доступно в любой локации вне боя.
	• "campfire" (костёр): доступно в узлах с type in ("village", "camp").
	• "workbench" (верстак / кузня): доступно только в узлах с type == "village".

3. Структура файлов (создать)
project_root/
├── engine/
│   └── crafting.py              # Проверка рецептов, крафт (алхимия/ремонт), полевая заточка, укрепление
└── tests/
    └── test_crafting.py         # Тесты станций, порогов навыков, перков алхимии/ремесла и заточки


4. Детальные требования к модулю engine/crafting.py


А. Получение списка рецептов (get_available_recipes(state: dict, game_data: GameData) -> list[dict])

Возвращает список всех рецептов из game_data.recipes с вычисленными флагами доступности для UI/CLI:
• id: ID рецепта (например, "rec_pot_heal_minor").
• stationOk: bool — поддерживается ли recipe["station"] в текущей локации (recipe["station"] == "any" или входит в _get_available_stations(state)).
• skillOk: bool — player["skills"][req_skill_id] >= req_level.
• ingredientsOk: bool — в player["inventory"] хватает всех предметов из recipe["ingredients"].
• canCraft: bool — not world["inCombat"] and stationOk and skillOk and ingredientsOk.

Б. Создание предмета по рецепту (craft_recipe(state: dict, recipe_id: str, game_data: GameData, rng: random.Random | None = None, session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]])

Реализует §14, §15, §17 и §22.3:
1. Валидация (без траты AP):
	• Проверяет world["inCombat"] is False (иначе err_in_combat).
	• Ищет рецепт recipe_id в game_data.recipes (иначе err_unknown_recipe).
	• Проверяет рабочее место: если recipe["station"] != "any" и recipe["station"] not in _get_available_stations(state) — возвращает {"id": "err_station_required", "requiredStation": recipe["station"]}.
	• Проверяет навык: req_skill = recipe["requiredSkill"]["id"], req_lvl = recipe["requiredSkill"]["level"]. Если player["skills"].get(req_skill, 0) < req_lvl — возвращает {"id": "err_skill_too_low", "skill": req_skill, "required": req_lvl}.
	• Проверяет наличие всех ингредиентов в player["inventory"] (count >= item["count"]) — иначе {"id": "err_missing_ingredients"}.
2. Расход ингредиентов и перк «Экономный алхимик» (§22.3):
	• Проверяем перк: is_frugal = (recipe["subCategory"] == "alchemy" and player["skills"].get("alchemy", 0) >= 6).
	• Если is_frugal и rng.random() <= 0.25: ингредиенты не тратятся (saved_ingredients = True).
	• Иначе: удаляем каждый ингредиент из player["inventory"] через remove_item(state, ing["itemId"], ing["count"]) (saved_ingredients = False).
3. Выдача результата:
	• Добавляем recipe["output"]["itemId"] в количестве recipe["output"]["count"] через add_item(state, out_id, out_count, game_data).
4. Трата 1 AP (§14):
	• Вызываем advance_time(state, steps=1, ...). Если игрок погиб от голода/DoT — возвращаем результат гибели.
5. Возвращаем (new_state, events + [{"id": "crafted_item", "recipeId": recipe_id, "itemId": out_id, "count": out_count, "savedIngredients": saved_ingredients}]).

В. Бесплатная полевая заточка оружия (sharpen_weapon(state: dict, game_data: GameData) -> tuple[dict, list[dict]])

Реализует веху 3 навыка crafting («Полевая заточка», §22.3: «вне боя можно бесплатно заточить оружие (+1 к min/max урону на 10 ударов)»):
1. Проверяет world["inCombat"] is False (иначе err_in_combat).
2. Проверяет навык: player["skills"].get("crafting", 0) >= 3 (иначе err_skill_too_low).
3. Проверяет, что у игрока надето оружие (player["equipment"]["weapon"] is not None) и оно не сломано (durability["current"] > 0) — иначе err_no_valid_weapon.
4. Проверяет, не заточено ли оружие уже на максимум (weapon.get("sharpenCharges", 0) >= 10) — если уже заточено и не израсходовано, возвращает err_already_sharpened (чтобы не спамить без смысла).
5. Устанавливает на экипированное оружие player["equipment"]["weapon"]["sharpenCharges"] = 10 (в блоке 2.2/3.1 get_effective_weapon_stats и register_weapon_hit уже учитывают +1 к min/max урону при sharpenCharges > 0 и уменьшают счётчик при ударах).
6. Важно: заточка бесплатна по золоту и не требует расходников (если в ТЗ 2.3/7.1 заточка приравнена к ремеслу за 1 AP или бесплатна по AP — сверяем с флагом: в §22.3 указано «бесплатно заточить оружие», поэтому золото = 0, AP = 0, чтобы игрок мог точить клинок перед боем без риска умереть от голода; если у вас в 2.2 уже заведен хелпер — делегируем ему).
7. Возвращает (new_state, [{"id": "weapon_sharpened", "itemId": weapon["itemId"], "charges": 10}]).

Г. Укрепление снаряжения на верстаке (reinforce_equipment(state: dict, slot: str, game_data: GameData, session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]])

Реализует веху 10 навыка crafting («Укрепление», §22.3: «игрок может улучшить любую броню или оружие на верстаке (+1 defense или +1 damage навсегда)»):
1. Проверяет world["inCombat"] is False (иначе err_in_combat).
2. Проверяет наличие верстака: "workbench" in _get_available_stations(state) (type == "village", иначе err_station_required).
3. Проверяет навык: player["skills"].get("crafting", 0) >= 10 (иначе err_skill_too_low).
4. Проверяет корректность слота (slot in ("weapon", "armor")) и наличие предмета в player["equipment"][slot] (иначе err_empty_slot).
5. Проверяет, что предмет ещё не был укреплён (item_inst.get("reinforced", False) is False — одно перманентное укрепление на предмет, иначе err_already_reinforced).
6. Применяет бонус:
	• Устанавливает item_inst["reinforced"] = True и item_inst["reinforceBonus"] = 1 (в get_effective_weapon_stats / get_effective_armor_stats из блока 2.2 это даёт +1 к min/max урону оружия или +1 к defense брони навсегда).
7. Тратит 1 AP через advance_time(state, steps=1, ...).
8. Возвращает (new_state, events + [{"id": "equipment_reinforced", "slot": slot, "itemId": item_inst["itemId"]}]).

5. Критерии приёмки (tests/test_crafting.py)

1. Проверка станций: рецепты со station == "any" крафтятся в дикой локации (forest_edge), рецепты со station == "campfire" требуют camp или village, рецепты со station == "workbench" отклоняются вне village (err_station_required) без списания AP и ресурсов.
2. Пороги навыков и ингредиенты: попытка скрафтить rec_pot_heal_regular при alchemy < 4 возвращает err_skill_too_low; при нехватке ресурсов — err_missing_ingredients; при успехе списывает ингредиенты, добавляет выходной предмет и тратит 1 AP.
3. Перк «Экономный алхимик» (alchemy >= 6): серия из 400 крафтов алхимического зелья подтверждает сохранение ингредиентов в ~25% случаев (savedIngredients == True).
4. Полевая заточка (crafting >= 3): недоступна при crafting == 2; при crafting >= 3 вешает sharpenCharges = 10 на экипированное оружие, повышая его эффективный урон на +1.
5. Укрепление на верстаке (crafting == 10): работает только в деревне (workbench), перманентно даёт +1 к урону оружия или защите брони (reinforced == True), повторное укрепление того же предмета отклоняется (err_already_reinforced).
