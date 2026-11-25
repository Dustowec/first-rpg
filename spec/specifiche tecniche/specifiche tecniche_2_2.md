
ТЗ на разработку — Блок 2.2: Инвентарь, экипировка, износ и ремонт


1. Цель задачи

Реализовать чистый модуль управления инвентарём, экипировкой, прочностью и ремонтом (engine/inventory.py). Модуль должен обеспечивать добавление/удаление предметов, надевание/снятие оружия и брони с сохранением индивидуальной прочности инстанса, расчёт эффективных боевых статов с учётом износа и вех (armor_mastery, crafting), а также ремонт у кузнеца и полевой ремонт ремнаборами.

2. Архитектурные ограничения и структуры данных

• Разделение логики и UI: Никаких print() или input(). Все операции принимают state: dict и game_data: GameData, работают на копии state (copy.deepcopy) и возвращают (new_state, events).
• Хранение прочности в инвентаре (важный стык):
	• Экипированные предметы в player["equipment"] имеют формат:
{"itemId": "wpn_club_simple", "durability": {"current": 15, "max": 15}} (или None, если слот пуст).
	• Стакаемые предметы в player["inventory"] (еда, расходники, материалы, ремнаборы) хранятся как {"itemId": "...", "count": N}.
	• Если в инвентарь попадает поношенное оружие или броня (например, снятое со слота с durability.current < max), оно хранится в inventory отдельным слотом с "count": 1 и полем "durability": {"current": ..., "max": ...}. Новое оружие/броня без поля "durability" при надевании инициализируется с current = max из game_data.
• Учёт заточки и укреплений (перки crafting 3 и 10, §22.3):
	• Инстанс экипировки в equipment (и в inventory) может содержать опциональные поля модификаторов:
		• "sharpenCharges": int (от вехи crafting 3 «Полевая заточка»: +1 к min и max урону на 10 ударов).
		• "reinforced": bool (от вехи crafting 10 «Укрепление»: +1 к damage оружия или +1 к defense брони навсегда).
project_root/
├── engine/
│   └── inventory.py         # Инвентарь, экипировка, износ, расчёт эффективных статов, ремонт
└── tests/
    └── test_inventory.py    # Юнит-тесты износа, штрафов, ремонта и перков


4. Детальные требования к модулю engine/inventory.py


А. Управление инвентарём

1. add_item(state: dict, item_id: str, count: int = 1, durability: dict | None = None, game_data: GameData | None = None) -> tuple[dict, list[dict]]:
	• Если durability не передан (или равен максимуму), ищет в player["inventory"] существующий стак с тем же itemId без индивидуального износа/заточки и увеличивает count += count.
	• Если передан предмет с индивидуальным износом/модификаторами — добавляет отдельной записью с count: 1 и durability.
	• Возвращает (new_state, [{"id": "item_added", "itemId": item_id, "count": count}]).
2. remove_item(state: dict, item_id: str, count: int = 1, slot_index: int | None = None) -> tuple[dict, list[dict]]:
	• Списывает count единиц предмета (по slot_index, если передан, иначе по первому подходящему слоту itemId). Если предметов недостаточно — возвращает (state, [{"id": "err_not_enough_items", "itemId": item_id}]).
	• При count == 0 удаляет запись из списка inventory.
3. has_item(player: dict, item_id: str, count: int = 1) -> bool: проверяет суммарное количество item_id в player["inventory"].

Б. Экипировка и эффективные характеристики (§3.1, §4, §16.1, §22.1, §22.3)

1. equip_item(state: dict, slot_index: int, game_data: GameData) -> tuple[dict, list[dict]]:
	• Берёт предмет по slot_index из player["inventory"], определяет его category ("weapon" или "armor"). Если категория не подходит — событие {"id": "err_cannot_equip"}.
	• Снимает текущий предмет из player["equipment"][category] (если слот не None) и кладёт его обратно в inventory с сохранением его durability, sharpenCharges и reinforced.
	• Устанавливает выбранный предмет в player["equipment"][category] (инициализируя durability: {"current": max_dur, "max": max_dur}, если не было), уменьшает стак в inventory на 1.
2. unequip_item(state: dict, slot: str) -> tuple[dict, list[dict]]:
	• Снимает предмет из "weapon" или "armor" в инвентарь с сохранением состояния прочности.
3. get_effective_weapon_stats(player: dict, game_data: GameData) -> dict:
	• Если player["equipment"]["weapon"] is None: возвращает безоружный удар (min: 1, max: 1, type: "blunt", skill: "melee_heavy", isBroken: False, isDamaged: False).
	• Берёт базовые статы оружия из game_data.get_item(item_id).
	• Проверяет прочность cur / max:
		• cur <= 0: предмет сломан (isBroken = True) → min = 0, max = 0.
		• 0 < cur < max * 0.30: предмет повреждён (isDamaged = True) → min = math.floor(base_min * 0.75), max = math.floor(base_max * 0.75).
		• Иначе: min = base_min, max = base_max.
	• Если предмет не сломан (cur > 0): добавляет +1 к min и max, если sharpenCharges > 0 (crafting 3), и +1 к min и max, если reinforced is True (crafting 10).
4. get_effective_armor_stats(player: dict, game_data: GameData) -> dict:
	• Если player["equipment"]["armor"] is None: возвращает defense: 0, evasion: 0, isBroken: False, isDamaged: False.
	• Берёт base_def и base_eva из game_data.
	• Перк armor_mastery 3 («Привычка к весу», §22.1): если броня имеет подтип "plate" и base_eva < 0, штраф base_eva снижается вдвое (math.ceil(base_eva / 2), например -6 -> -3, -4 -> -2).
	• Перк armor_mastery 6 («Закалка», §22.1): даёт +1 к defense любой надетой (не сломанной) брони.
	• Перк crafting 10 («Укрепление», §22.3): даёт +1 к defense, если reinforced is True.
	• Проверяет прочность cur / max:
		• cur <= 0: сломана (isBroken = True) → defense = 0 (штраф evasion при этом сохраняется, если он отрицательный, или обнуляется положительный уворот: положительный evasion = 0, отрицательный остаётся).
		• 0 < cur < max * 0.30: повреждена (isDamaged = True) → defense = math.floor(total_def * 0.75).

В. Механика износа (§16.1, §22.1)

1. register_weapon_hit(state: dict) -> tuple[dict, list[dict]]:
	• Вызывается при каждом успешном ударе оружием игрока.
	• Если у оружия есть sharpenCharges > 0, уменьшает sharpenCharges -= 1 (если дошло до 0 — событие {"id": "weapon_sharpen_worn_out"}).
	• Увеличивает внутренний счётчик ударов на инстансе оружия hitCounter = inst.get("hitCounter", 0) + 1.
	• Каждые 3 успешных удара (hitCounter >= 3): сбрасывает hitCounter = 0, снижает durability.current = max(0, cur - 1). Если прочность упала ниже 30% впервые — событие {"id": "equipment_damaged", "slot": "weapon"}; если дошла до 0 — событие {"id": "equipment_broken", "slot": "weapon"}.
2. register_armor_hit(state: dict) -> tuple[dict, list[dict]]:
	• Вызывается при каждом полученном игроком ударе.
	• Увеличивает hitCounter брони на +1.
	• Учёт перка armor_mastery 6 («Закалка»): без перка 1 ед. прочности снимается каждые 3 полученных удара; с перком «Закалка» прочность тратится в 2 раза медленнее — каждые 6 полученных ударов.

Г. Два способа ремонта (§16.2, §22.3)

1. calc_smith_repair_cost(player: dict, slot: str, game_data: GameData) -> int:
	• Берёт инстанс из player["equipment"][slot]. Если None или current >= max — возвращает 0.
	• Формула (§16.2, без минимума 1): raw_cost = buy_price * 0.25 * (1.0 - current / max).
	• Перк crafting 6 («Мастер ремонта»): снижает стоимость починки у кузнеца на 30% (raw_cost *= 0.70).
	• Возвращает round(raw_cost).
2. repair_at_smith(state: dict, slot: str, game_data: GameData) -> tuple[dict, list[dict]]:
	• Проверяет, что игрок находится в деревне (текущий узел имеет type == "village"), предмет в слоте slot существует и current < max.
	• Считает cost = calc_smith_repair_cost(...). Если player["gold"] < cost — возвращает (state, [{"id": "err_not_enough_gold", "required": cost}]).
	• Списывает player["gold"] -= cost, восстанавливает durability.current = durability.max, сбрасывает hitCounter = 0. (Время суток не тратит!).
	• Возвращает (new_state, [{"id": "smith_repaired", "slot": slot, "cost": cost}]).
3. repair_with_kit(state: dict, kit_item_id: str, target_slot: str, game_data: GameData) -> tuple[dict, list[dict]]:
	• Проверяет наличие ремнабора (category == "repair_kit") в inventory и надетого предмета в target_slot ("weapon" или "armor") с current < max.
	• Проверяет совместимость по stats.targetCategories и stats.targetSubCategories ремнабора (например, rep_patch_kit чинит только cloth и leather, но не plate; rep_whetstone чинит только weapon; rep_smith_kit чинит любое оружие и броню). При несовместимости — событие {"id": "err_incompatible_repair_kit"}.
	• Объём восстановления: restore = kit["stats"]["durabilityRestore"]. При перке crafting 6 («Мастер ремонта») восстанавливает в 2 раза больше прочности (restore *= 2).
	• Списывает 1 ремнабор, увеличивает durability.current = min(max, current + restore).
	• Возвращает (new_state, [{"id": "field_repaired", "slot": target_slot, "restored": actual_restored, "apCost": 1}]) (само продвижение шага суток на 1 AP подключим в блоке 2.3/контроллере, либо принимаем флаг/вызов тика).

5. Критерии приёмки (tests/test_inventory.py)

1. Надевание и снятие предметов сохраняет их текущую прочность при перемещении между equipment и inventory.
2. Расчёт эффективных статов: при прочности 4/15 (< 30%) урон/защита режутся на 25% (floor), при 0/15 становятся равными 0.
3. Износ: каждые 3 удара снимают 1 прочность; с перком armor_mastery == 6 броня теряет 1 прочность раз в 6 ударов, а штраф уклонения лат снижается вдвое при armor_mastery == 3.
4. Ремонт у кузнеца: для целого предмета возвращает 0 и запрещает починку; для убитого wpn_sword_fine (buyPrice: 120, 0/55) стоит 30 золота (и 21 золото при crafting == 6).
5. Полевой ремонт: rep_patch_kit чинит кожаную/тканевую броню на +10 (+20 при crafting == 6), но выдаёт ошибку на латы (arm_plate_poor).
