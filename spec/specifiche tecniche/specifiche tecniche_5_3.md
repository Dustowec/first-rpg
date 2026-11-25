
ТЗ на разработку — Блок 5.3: Главный контроллер, CLI-интерфейс в 1 кнопку и интеграционные тесты


1. Цель задачи

Реализовать единый диспетчер команд игрового цикла с автоматическим сохранением (engine/controller.py), текстовый интерфейс управления в одну кнопку без утечки скрытых параметров (cli/app.py), точку входа (main.py) и сквозные интеграционные автотесты (tests/test_integration_flow.py) согласно §§ 32, 33 и 34 спецификации.

2. Архитектурные ограничения и структуры данных

• Строгое разделение ядра и UI (§ 33.2, § 34.1):
	• engine/controller.py — чистое ядро без print() и input(): принимает (state, command_dict, game_data, rng, ...) -> возвращает (new_state, events) и выполняет атомарный автосейв (save_state) после каждого мирового/игрового действия (§ 32.2).
	• cli/app.py — тонкий презентационный слой: преобразует state и events в текст с опорой на data/strings_ru.json, считывает ввод одной цифры + Enter и формирует command_dict для контроллера.
• Маскировка скрытых данных (hidden: true, § 33.2):
	• UI никогда не выводит числовые значения полей, у которых в JSON стоит "hidden": true (урон, защита, точность, уклонение монстров).
	• Здоровье монстра в бою отображается исключительно текстовой полосой вида [HP ######----] (масштаб 10 делений: filled = round(cur / max * 10)), а не числами.
• Обработка смерти (Permadeath, § 32, канон #4):
	• При обнаружении события гибели игрока (player_died, будь то голод на шаге 7/17 или падение HP до 0 в бою) контроллер или CLI фиксирует экран смерти, после чего handle_player_death() сбрасывает state_session.json в свежую копию state_template.json.

3. Структура файлов (создать)
project_root/
├── engine/
│   └── controller.py            # Единый диспетчер команд (dispatch_command) + автосейв после действий
├── cli/
│   ├── __init__.py
│   └── app.py                   # Консольный рендер экранов в 1 кнопку, маскировка hidden: true, цикл ввода
├── main.py                      # Точка входа (загрузка GameData, load_state, запуск CLI)
└── tests/
    └── test_integration_flow.py # Сквозные интеграционные тесты всех ключевых игровых циклов


4. Детальные требования к модулям


А. Главный диспетчер команд (engine/controller.py, § 32.2, § 34.1)

1. Единая точка входа в ядро:
def dispatch_command(
    state: dict,
    command: dict,
    game_data: GameData,
    rng: random.Random | None = None,
    session_path: str = DEFAULT_SESSION_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
    llm_transport_fn: Callable | None = None,
) -> tuple[dict, list[dict]]

2. Маршрутизация command["type"] по реализованным модулям:
	• Мир и исследование (Блок 4.2):
		• "move" (targetNodeId) -> move_to_node(...) (может вызвать засаду ambush_triggered и перевод inCombat = True).
		• "look" -> look_around(...).
		• "search" -> search_location(...).
		• "wait" -> advance_time(..., steps=1) (ожидание 1 AP).
		• "travel_next_region" -> advance_to_next_region(...) (Блок 4.1).
	• Бой (Блоки 3.1–3.4):
		• "start_combat" -> start_combat(...).
		• "combat_attack" (useCrushingStrike: bool = False) -> combat_step(..., {"type": "attack", ...}).
		• "combat_spell" (spellId) -> combat_step(..., {"type": "spell", "spellId": ...}).
		• "combat_item" (itemId) -> combat_step(..., {"type": "item", "itemId": ...}).
		• "combat_retreat" -> combat_step(..., {"type": "retreat"}).
	• Инвентарь, еда и прокачка (Блоки 2.1–2.3):
		• "eat" (itemId) -> eat_food(...).
		• "use_item" (itemId) -> вне боя применяет зелье/эликсир/покрытие или ремнабор (repair_with_kit).
		• "equip" (itemId) -> equip_item(...).
		• "unequip" (slot) -> unequip_item(...).
		• "allocate_attribute" (attribute) -> allocate_attribute(...).
		• "allocate_skill" (skill) -> allocate_skill(...).
	• Ремесло и сервисы деревни (Блоки 4.3–4.4):
		• "craft" (recipeId) -> craft_recipe(...).
		• "field_sharpen" -> field_sharpen_weapon(...).
		• "smith_repair" (slot) -> use_smith_repair(...).
		• "inn_rest" -> use_inn_rest(...).
		• "buy_item" (npcId, itemId, count) -> buy_item(...).
		• "sell_item" (npcId, itemId, count) -> sell_item(...).
	• Диалоги LLM-NPC (Блоки 5.1–5.2):
		• "talk_npc" (npcId, playerInput) -> вызывает query_npc_llm(...), затем process_npc_dialogue(...).
		• "accept_barter" (npcId) -> accept_barter_offer(...).
3. Правило автосейва (§ 32.2):
	• Если команда не вернула ошибку (not any(e["id"].startswith("err_") for e in events)), dispatch_command автоматически вызывает save_state(new_state, session_path).
	• Если в событиях есть гибель игрока (any(e["id"] == "player_died" for e in events)), вызывает handle_player_death(session_path, template_path) и добавляет событие {"id": "session_reset_permadeath"}.

Б. Консольный рендер и цикл в 1 кнопку (cli/app.py, § 33.1–33.2)

1. Неизменная статус-строка (1-я линия любого экрана, § 33.1):
	• Формат: ДЕНЬ {day} · ШАГ {stepOfDay}/20 · HP {hp}/{maxHp} · MP {mp}/{maxMp} · ЗОЛОТО {gold} · [{статус голода}]
	• Предупреждение о голоде рассчитывается по активному дедлайну (7/17 или 9/19 при перке «Тугий пояс»): например [завтрак: поесть до шага 7!] или [сыт].
2. Журнал событий:
	• Хранит кольцевой буфер последних 5–6 сообщений, переведённых из events с использованием game_data.strings_ru.
3. Режимы экранов (управление цифрой + Enter):
	• Стартовое распределение очков (если unspentPoints.attributes == 3 и day == 1, stepOfDay == 1): краткий экран вложения 3 стартовых очков (лимит +2 на стат) или пропуска.
	• Основной экран исследования (inCombat == False, § 33.1):
		• Название локации, уровень опасности (безопасно / низкая / средняя / высокая), список выходов [1]..[N].
		• Если монстр в локации раскрыт (revealed == True), выводит его имя и полосу HP без скрытых чисел.
		• Пункты меню: Осмотреться (1 AP), Поиск (1 AP), В бой (1 AP, если есть видимый монстр), Инвентарь/Еда, Персонаж, Карта, Крафт/Заточка, Переход в «Дальние тропы» (если босс логова побеждён), NPC/Сервисы (если в деревне или лагере), Ждать (1 AP), Выход.
	• Боевой экран (inCombat == True, § 33.1):
		• Заголовок: БОЙ · {Имя монстра} [HP ######----] · вы [HP ######----] · раунд {round} (строго без числового HP монстра!).
		• Меню в 1 кнопку: [1] Ударить, [2] Заклинание (подменю доступных по уровню навыка заклинаний), [3] Расходник (подменю зелий/бомб/масел), [4] Отступить (шанс 50%) (и [5] Сокрушение, если открыта веха melee_heavy == 10 и откат 0).
	• Подменю (Инвентарь, Персонаж, Карта, Крафт, Деревня/NPC, Диалог с NPC):
		• В диалоге с NPC выводится npcReply, настроение mood и нумерованные варианты suggestedReplies ([1]..[3]), а также [4] Ввести свою фразу, [5] Принять обмен (если есть pendingBarter) и [0] Закончить разговор.
	• Защита от неверного ввода: При вводе не-числа или несуществующего номера выводит строку из strings_ru ("введите номер действия", § 33.2) без краша.

В. Точка входа (main.py)

• Инициализирует GameData из папки data/.
• Загружает состояние через load_state("state_session.json", "state_template.json").
• Запускает главный цикл run_cli(state, game_data).

5. Критерии приёмки (tests/test_integration_flow.py)

Написать набор сквозных тестов (без интерактивного input, через dispatch_command и render_* функции CLI):
1. Сквозной цикл выживания, автосейва и смерти от голода: Старт новой игры в node_00, переход в соседнюю локацию, «Поиск», пропуск ходов до дедлайна завтрака (шаг 7) -> проверка, что state_session.json перезаписывался после каждого шага, а на шаге 7 сработали player_died (голод) и полный permadeath-сброс сессии.
2. Полный боевой цикл и лут: Осмотр локации (revealed = True), вступление в бой (inCombat = True), атака / победа над монстром, начисление XP/золота/лута и проверка, что рендер боевого экрана содержит полосу [HP ...] и не содержит скрытых числовых статов монстра (hidden: true).
3. Цикл деревни и диалога с LLM-моком: Возврат в node_00, диалог с трактирщиком Борисом через dispatch_command("talk_npc", ...) с мок-транспортом (эталонный бартер § 26.1), подтверждение сделки accept_barter, поедание полученного хлеба (eat) и ночлег (inn_rest за 5 золота до day == 2, stepOfDay == 1).
4. Зачистка логова и переход в «Дальние тропы»: Победа над 3 противниками логова (lairQueue + босс) и переход через travel_next_region в region == 2.
