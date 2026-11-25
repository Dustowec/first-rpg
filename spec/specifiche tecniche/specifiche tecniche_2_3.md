
ТЗ на разработку — Блок 2.3: Счётчик AP/суток, голод, ночлег, регенерация и респавн


1. Цель задачи

Реализовать модуль управления временем мира и выживанием (engine/world_time.py). Модуль должен обеспечивать продвижение времени на N шагов (advance_time), проверку дедлайнов завтрака и ужина (с вызовом permadeath-сброса при голодной смерти), употребление еды (eat_food), платный ночлег у трактирщика Бориса за 5 золота (rest_at_inn), тик активных эффектов вне боя (DoT и остатков эликсиров), естественную регенерацию HP/MP и периодический респавн монстров раз в 5 дней.

2. Архитектурные ограничения и стыки

• Разделение логики и UI: Никаких print() / input(). Модуль возвращает (new_state, events) или (fresh_state, events) в случае смерти игрока.
• Стык со смертью (§32 и блок 1.1): Если игрок погибает от голода или яда вне боя, модуль вызывает handle_player_death(state, reason=...) из engine/storage.py (передав optional session_path / template_path, по умолчанию стандартные).

3. Структура файлов (создать)
project_root/
├── engine/
│   └── world_time.py        # Время суток (AP), голод, еда, ночлег за 5 монет, реген, респавн
└── tests/
    └── test_world_time.py   # Юнит-тесты цикла дня, голода, перка «Тугий пояс», ночлега и респавна


4. Детальные требования к модулю engine/world_time.py


А. Окна голода и перк «Тугий пояс» (§7.2, §22.3)

Реализовать хелперы проверки состояния голода:
1. get_hunger_deadlines(player: dict) -> tuple[int, int]:
	• Базово: завтрак до шага 7 (morning_deadline = 7), ужин до шага 17 (evening_deadline = 17).
	• Если открыт перк scavenging >= 6 («Тугий пояс», has_tight_belt): сдвиг на +2 хода → (9, 19).
2. is_hungry_now(world: dict, player: dict) -> bool:
	• Возвращает True, если персонаж сейчас в фазе активного голода (блокирует регенерацию HP по §7.3):
		• 1 <= stepOfDay < morning_deadline и fedMorning is False, ИЛИ
		• 10 <= stepOfDay < evening_deadline и fedEvening is False.

Б. Продвижение времени суток advance_time(state: dict, steps: int = 1, game_data: GameData | None = None, rng: random.Random | None = None, session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]

Выполняется пошагово (for _ in range(steps):) для каждого 1 AP:
1. Проверка текущего шага на дедлайн голода (до или при переходе на шаг):
	• Увеличиваем world["stepOfDay"] += 1.
	• Если world["stepOfDay"] > 20:
		• world["stepOfDay"] = 1
		• world["day"] += 1
		• world["fedMorning"] = False
		• world["fedEvening"] = False
		• Вызываем обработку смены суток _on_new_day(state, game_data, rng, events) (см. пункт Д про респавн).
	• Проверяем дедлайны (morning_deadline, evening_deadline = get_hunger_deadlines(player)):
		• Если stepOfDay == morning_deadline и not world["fedMorning"]: мгновенная смерть → возвращаем handle_player_death(state, reason="starvation_morning", ...).
		• Если stepOfDay == evening_deadline и not world["fedEvening"]: мгновенная смерть → возвращаем handle_player_death(state, reason="starvation_evening", ...).
2. Тик активных эффектов вне боя (world["activeEffects"], §7.1, §13.2):
	• Для каждого эффекта в activeEffects:
		• Если есть hpDeltaPerTurn (например, poison от красного гриба): изменяет player["resources"]["hp"]["current"] += hpDeltaPerTurn (кламп к max).
		• Уменьшает ticksLeft -= 1. Если ticksLeft <= 0 — удаляет эффект и добавляет событие {"id": "effect_expired", "type": effect["type"]}.
	• Если player["resources"]["hp"]["current"] <= 0: мгновенная смерть → возвращаем handle_player_death(state, reason="dot_damage", ...).
3. Естественная регенерация вне боя (§7.3, §10.1):
	• Срабатывает только если world["inCombat"] is False:
	• Реген MP: каждые 5 шагов суток (stepOfDay % 5 == 0):
mp.current = min(mp.max, mp.current + player["level"]).
	• Реген HP: каждые 3 шага суток (stepOfDay % 3 == 0), только если:
		1. Нет активных негативных DoT-эффектов (poison, bleeding).
		2. not is_hungry_now(world, player) (игрок не голодает в текущем окне!).
При выполнении условий: hp.current = min(hp.max, hp.current + player["level"]).

В. Употребление еды eat_food(state: dict, item_id: str, game_data: GameData) -> tuple[dict, list[dict]] (§7.2, §3.2)

• Не тратит AP (0 шагов суток).
• Проверяет, что предмет существует в game_data, имеет category == "food" и есть в player["inventory"]. Иначе — событие {"id": "err_invalid_food"}.
• Списывает 1 единицу item_id из инвентаря (remove_item).
• Восстанавливает HP: hp_restore = item["stats"].get("hpRestore", 0), hp.current = min(hp.max, hp.current + hp_restore).
• Если у еды есть dotEffect (как у food_red_mushroom): добавляет/обновляет эффект в world["activeEffects"] ({"type": "poison", "hpDeltaPerTurn": -1, "ticksLeft": 3}).
• Закрытие окон голода:
	• Если 1 <= world["stepOfDay"] < morning_deadline и not world["fedMorning"]: ставит world["fedMorning"] = True, событие {"id": "hunger_satisfied", "meal": "morning"}.
	• Иначе если 10 <= world["stepOfDay"] < evening_deadline и not world["fedEvening"]: ставит world["fedEvening"] = True, событие {"id": "hunger_satisfied", "meal": "evening"}.
	• (Повторное поедание в рамках уже закрытого окна только лечит HP, но не закрывает ужин авансом на шагах 1..9).

Г. Платный ночлег у трактирщика Бориса rest_at_inn(state: dict, game_data: GameData, rng: random.Random | None = None, session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]] (Канон #2)

• Проверяет, что игрок находится в узле с type == "village" (где сидит трактирщик npc_innkeeper_boris). Иначе — {"id": "err_not_in_village"}.
• Берёт стоимость из данных Бориса (restCost = 5). Проверяет player["gold"] >= 5. Иначе — {"id": "err_not_enough_gold", "required": 5}.
• Списывает player["gold"] -= 5.
• Вычисляет, сколько шагов осталось до утра следующего дня: steps_to_morning = (20 - world["stepOfDay"]) + 1.
• Важно: перед перемоткой закрывает ужин текущих суток (world["fedEvening"] = True, если вечернее окно не было просрочено; если игрок пришёл в таверну уже после дедлайна или до него — считаем, что постоялец поужинал/переночевал под крышей и не умрёт от голода во сне).
• Прогоняет advance_time(state, steps=steps_to_morning, ...) — таким образом естественно тикают регенерация HP/MP, спадают баффы/DoT, наступает day + 1, stepOfDay = 1, и срабатывает проверка респавна монстров.
• Возвращает (new_state, events + [{"id": "inn_rested", "cost": 5, "newDay": new_state["world"]["day"]}]).

Д. Периодический респавн монстров раз в 5 дней (Канон #1)

Внутренняя функция _on_new_day(state, game_data, rng, events):
• Для каждого узла в state["map"]["nodes"]:
	• Пропускает узел, если node["type"] == "village" или если монстр в локации уже жив (node["state"]["monster"] is not None или в логове остались живые враги).
	• Если узел был зачищен (node["state"]["spawnRolled"] is True и node["state"]["monster"] is None):
		• Увеличивает node["state"]["daysSinceCleared"] = node["state"].get("daysSinceCleared", 0) + 1.
		• Если daysSinceCleared >= 5:
			• Сбрасывает daysSinceCleared = 0.
			• Респавнит одного обычного (не босса, not mob.get("isBoss", False)) монстра из monsterPool биома этого узла (отфильтрованного по тиру локации / региону, с учётом difficultyMultiplier из meta).
			• Устанавливает node["state"]["monster"] = {"mobId": chosen_mob_id, "revealed": False, "hp": scaled_hp, "maxHp": scaled_hp} (и для логова с несколькими врагами — респавнит ровно 1 стража, без повторного босса).
			• Добавляет событие {"id": "monster_respawned", "nodeId": node["id"], "mobId": chosen_mob_id}.

5. Критерии приёмки (tests/test_world_time.py)

1. Переход с шага 20 на шаг 1 увеличивает day на +1 и сбрасывает fedMorning и fedEvening в False.
2. Смерть от голода: если не поесть до шага 7 (или 9 при scavenging == 6), advance_time запускает permadeath-сброс (reason="starvation_morning"). Аналогично для ужина (шаг 17 / 19).
3. Блокировка регенерации HP при голоде: на шаге 3 и 6 при fedMorning == False HP не восстанавливается, а MP на шаге 5 восстанавливается; после eat_food("food_berries") реген HP включается.
4. Красный гриб (food_red_mushroom): закрывает окно голода, но вешает poison (-1 HP / шаг на 3 шага), который блокирует реген HP и может убить персонажа с 1–2 HP.
5. Ночлег у Бориса: стоит 5 золота, переводит время на day + 1, stepOfDay = 1, восстанавливает HP/MP за пропущенные шаги и не убивает игрока голодом во сне.
6. Респавн монстров: в зачищенном диком узле ровно на 5-й день (daysSinceCleared == 5) появляется 1 новый монстр со статусом revealed = False.
