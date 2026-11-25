
ТЗ на разработку — Блок 3.2: Расходники, покрытия оружия и конвертация длительности эффектов


1. Цель задачи

Реализовать модуль применения алхимических расходников (engine/consumables.py) по правилам §12, §13 и §22.3 спеки. Модуль должен поддерживать использование зелий, эликсиров, масел/ядов для оружия и метательных бомб как вне боя, так и в бою, обеспечивать корректный стакинг эффектов, расчёт дополнительного урона и отравления от покрытий при попадании, а также единую модель длительности (ticksLeft), которая тикает боевыми раундами в бою и шагами суток вне боя.

2. Архитектурные ограничения и стыки

• Единая модель world["activeEffects"] (§13.2, §32.3):
	• Эликсиры и покрытия хранятся в общем списке state["world"]["activeEffects"], так как по канону §13.2 1 боевой ход = 1 шаг суток, и остаток длительности после боя автоматически дотикивает шагами мира (блок 2.3 уже тикает ticksLeft на шагах суток!).
	• Формат записи эликсира в activeEffects:
{"id": "elx_ironskin", "category": "elixir", "stat": "defense", "value": 3, "ticksLeft": 5, ...}
	• Формат записи покрытия в activeEffects:
{"id": "oil_fire", "category": "coating", "chargesLeft": 4, "bonusDamage": 2, "damageType": "fire"} (или для oil_poison: {"id": "oil_poison", "category": "coating", "chargesLeft": 3, "dotType": "poison", "hpDeltaPerTurn": -2, "dotTurns": 3}).
• Никакого UI: Модуль принимает (state, item_id, game_data, ...) и возвращает (new_state, events) без print() / input().

3. Структура файлов (создать)
project_root/
├── engine/
│   └── consumables.py       # Применение зелий, бомб, эликсиров, покрытий и триггеры ударов
└── tests/
    └── test_consumables.py  # Юнит-тесты расходников, стакинга, oil_fire и перков алхимии


4. Детальные требования к модулю engine/consumables.py


А. Перки алхимии (§22.3)

1. Веха alchemy 3 («Травник», has_herbalist): зелья лечения (hpRestore) и маны (mpRestore) восстанавливают на +25% больше ресурса (round(base_restore * 1.25)).
2. Веха alchemy 10 («Двойная доза», has_double_dose): длительность всех эликсиров (ticksLeft) и количество зарядов масел (chargesLeft) увеличиваются в 1.5 раза (round(base_duration * 1.5)).

Б. Применение расходника use_consumable(state: dict, item_id: str, game_data: GameData, target_monster: dict | None = None, target_affinities: dict[str, float] | None = None, rng: random.Random | None = None) -> tuple[dict, list[dict]]

1. Проверяет наличие item_id в player["inventory"] и что item["category"] == "consumable". Иначе — (state, [{"id": "err_invalid_consumable", "itemId": item_id}]).
2. Если subCategory == "bomb": разрешено использовать только в бою (world["inCombat"] is True и передан target_monster). При попытке кинуть бомбу вне боя — (state, [{"id": "err_bomb_only_in_combat"}]).
3. Списывает 1 единицу item_id из инвентаря через remove_item.
4. Обрабатывает по subCategory:
	• potion (Зелья, §13.1):
		• Если есть hpRestore: вычисляет восстановление (с бонусом ×1.25 при alchemy >= 3), прибавляет к player["resources"]["hp"]["current"] (кламп до max). Событие {"id": "potion_healed", "amount": actual_healed}.
		• Если есть mpRestore: вычисляет восстановление (с бонусом ×1.25 при alchemy >= 3), прибавляет к player["resources"]["mp"]["current"] (кламп до max). Событие {"id": "potion_mana_restored", "amount": actual_restored}.
		• Если есть cureEffects (например, ["poison", "bleeding"] у pot_antidote): удаляет из world["activeEffects"] все эффекты с типом из этого списка. Событие {"id": "potion_cured", "cured": removed_types}.
	• elixir (Эликсиры / Настойки, §13.2):
		• Правило стакинга (§13.2): одновременно активен максимум 1 эликсир (category == "elixir"). Перед добавлением нового удаляет любой существующий эффект с category == "elixir" из world["activeEffects"].
		• Рассчитывает длительность: ticks = buff["durationCombatTurns"], если has_double_dose(player) → ticks = round(ticks * 1.5).
		• Добавляет эффект в world["activeEffects"] (сохраняя все поля stat, value, maxHitCapOverride, evasionPenalty, ticksLeft: ticks).
		• Событие {"id": "elixir_applied", "itemId": item_id, "ticksLeft": ticks}.
	• coating (Масла и яды, §13.2):
		• Правило стакинга (§13.2): одновременно активен максимум 1 покрытие (category == "coating"), масла разных типов не смешиваются. Перед наложением удаляет любой существующий эффект с category == "coating".
		• Рассчитывает заряды: charges = coat["charges"], если has_double_dose(player) → charges = round(charges * 1.5).
		• Добавляет эффект покрытия в world["activeEffects"] с chargesLeft: charges.
		• Событие {"id": "coating_applied", "itemId": item_id, "chargesLeft": charges}.
	• bomb (Алхимический огонь bmb_fire, §13.2):
		• Шанс попадания фиксированный: hit_chance = dmg_stats.get("hitChance", 80).
		• Бросок попадания rng.randint(0, 100) <= hit_chance. При промахе — событие {"id": "bomb_missed", "itemId": item_id}.
		• При попадании: raw = rng.randint(dmg_stats["min"], dmg_stats["max"]).
		• Применяет матрицу уязвимостей get_damage_multiplier(dmg_stats["type"], target_affinities or {}, has_elemental_breakthrough(player)) — броня цели бомбой игнорируется (§13.2).
		• Итоговый урон: final_dmg = max(0, round(raw * mult)). Вычитает final_dmg из target_monster["hp"] (max(0, hp - final_dmg)).
		• Событие {"id": "bomb_hit", "itemId": item_id, "damage": final_dmg, "damageType": dmg_stats["type"]}.

В. Срабатывание покрытия при успешном ударе оружием (§13.2)

process_weapon_coating_on_hit(state: dict, target_monster: dict, target_affinities: dict[str, float]) -> tuple[dict, list[dict]]:
• Вызывается боевым движком сразу после успешного попадания оружием игрока.
• Ищет в world["activeEffects"] активный эффект с category == "coating". Если нет — возвращает (state, []).
• Если это oil_fire (бонусный стихийный урон):
	• Отдельный пакет урона типом fire (bonusDamage = 2): применяется множитель уязвимости mult = get_damage_multiplier("fire", target_affinities, has_elemental_breakthrough(player)), броня цели не применяется (§13.2).
	• extra_dmg = max(0, round(bonus_damage * mult)).
	• Вычитает extra_dmg из target_monster["hp"].
	• Генерирует событие {"id": "coating_damage", "itemId": coating["id"], "damage": extra_dmg, "damageType": "fire"}.
• Если это oil_poison (наложение DoT):
	• Вешает/обновляет на target_monster (в списке target_monster.setdefault("activeEffects", [])) эффект отравления: {"type": "poison", "hpDeltaPerTurn": -2, "ticksLeft": 3} (если цель не имеет иммунитета affinities.get("poison", 1.0) == 0.0, например undead или construct — при иммунитете возвращается событие {"id": "coating_immune", "damageType": "poison"}).
• Расход заряда:
	• Уменьшает coating["chargesLeft"] -= 1.
	• Если chargesLeft <= 0: удаляет покрытие из world["activeEffects"] и добавляет событие {"id": "coating_depleted", "itemId": coating["id"]}.

Г. Тик боевых эффектов за 1 раунд боя

tick_combat_round_effects(state: dict, target_monster: dict) -> tuple[dict, list[dict]]:
• Вызывается в конце каждого боевого раунда (1 боевой ход = 1 шаг суток).
• Тикает ticksLeft -= 1 у всех эффектов игрока в world["activeEffects"] (кроме покрытий, которые тратятся по ударам), применяя DoT (например, яд от паука) и удаляя истёкшие баффы.
• Тикает ticksLeft -= 1 у всех эффектов монстра в target_monster.get("activeEffects", []) (например, яд от oil_poison), нанося монстру урон hpDeltaPerTurn и удаляя истёкшие эффекты.

5. Критерии приёмки (tests/test_consumables.py)

1. Зелье pot_heal_minor лечит 6 HP в норме и 8 HP (round(6 * 1.25)) при alchemy == 3; pot_antidote снимает poison.
2. Стакинг эликсиров: при активном elx_ironskin выпитый elx_accuracy заменяет его (в activeEffects остаётся только 1 эликсир), а при alchemy == 10 длительность увеличивается с 5 до 8 ходов.
3. Покрытие oil_fire при ударе по зверю (fire: 1.25) наносит round(2 * 1.25) = 3 урона поверх основного удара в обход высокой брони, а через 4 удара исчезает.
4. Покрытие oil_poison накладывает яд на гуманоида/зверя, но получает coating_immune на нежити (undead) и конструктах (construct).
5. Бомба bmb_fire запрещена вне боя и игнорирует defense монстра в бою.