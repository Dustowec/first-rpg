
ТЗ на разработку — Блок 3.1: Боевые формулы (Инициатива, Меткость, Урон, Криты и Броня)


1. Цель задачи

Реализовать модуль математического ядра боя (engine/combat_math.py) по канону §2, §5.1, §9.2 и §22.1–22.2 спеки. Модуль отвечает за расчёт инициативы (кто бьёт первым), шансов попадания игрока и монстра (с учётом капов, эликсиров и дебаффов), расчёт физического урона оружия, критических ударов игрока, модификаторов уязвимости/сопротивления (affinities) и гиперболического поглощения бронёй (10 / (10 + def)), а также масштабирование статов монстра под difficultyMultiplier.

2. Архитектурные ограничения

• Детерминированность через rng: random.Random: Все случайные величины (randint, процентные проверки rng.randint(0, 100) <= chance) принимают объект rng: random.Random (по умолчанию random.Random()), чтобы в тестах можно было прогонять как фиксированные сиды, так и статистические выборки.
• Никакого UI: Модуль возвращает только числа, словари результатов удара и ID событий.

3. Структура файлов (создать)
project_root/
├── engine/
│   └── combat_math.py       # Инициатива, меткость, урон, криты, резисты, броня, скейлинг сложности
└── tests/
    └── test_combat_math.py  # Юнит-тесты всех формул §2 и граничных условий


4. Детальные требования к модулю engine/combat_math.py


А. Масштабирование монстра под сложность (Канон #3)

scale_monster_stats(monster_data: dict, difficulty_multiplier: float = 1.0) -> dict:
• Возвращает рабочий статблок монстра для боя, масштабируя maxHp и диапазон урона (min, max) на difficulty_multiplier (0.75 / 1.0 / 1.4 / 2.0):
	• scaled_hp = max(1, round(base_hp * difficulty_multiplier))
	• scaled_min = max(1, round(base_min * difficulty_multiplier)) (если base_min > 0, иначе 0)
	• scaled_max = max(scaled_min, round(base_max * difficulty_multiplier))
• Защита (defense), меткость (accuracy) и уклонение (evasion) остаются базовыми из JSON монстра, чтобы не ломать коридор попаданий 15..80%.

Б. Инициатива в первом раунде боя (§2.4, §22.1, §27.2)

determine_first_attacker(player: dict, monster_stats: dict, is_ambush: bool, rng: random.Random) -> str:
• Возвращает "monster" или "player".
• Если is_ambush is True: монстр бьёт первым безусловно ("monster"), без броска и игнорируя перки.
• Если у игрока открыт перк melee_light >= 6 («Длинная дистанция», has_long_reach): игрок всегда бьёт первым ("player").
• Иначе считается шанс первого хода монстра (§2.4):
monster_first_chance = clamp(50 + (monster_evasion * 2) - ((agility - 1) * 2), 20, 80)
Бросок: если rng.randint(0, 100) <= monster_first_chance → "monster", иначе → "player".

В. Шансы попадания и уклонения (§2.1, §2.1.1, §13.2, §22.1)

1. calc_player_evasion(player: dict, game_data: GameData, active_effects: list[dict] | None = None) -> int:
	• Берёт armor_eva из get_effective_armor_stats(player, game_data) (где уже учтён перк armor_mastery 3 «Привычка к весу», режущий штраф лат вдвое).
	• Базовое уклонение от ловкости: math.floor((agility - 1) * 1.5).
	• Если открыт перк melee_light >= 6 («Длинная дистанция»): +5 к уклонению (§22.1).
	• Учитывает модификаторы активных эффектов (например, elx_berserk даёт -5 к evasion).
	• Итог: armor_eva + agility_eva + perk_eva + effects_eva.
2. calc_player_hit_chance(player: dict, weapon_stats: dict, target_evasion: int, active_effects: list[dict] | None = None, min_cap_override: int | None = None) -> int:
	• Базовая формула (§2.1):
raw_hit = 50 + (weapon_skill * 3) + ((agility - 1) * 2) - target_evasion
	• Учитывает бонусы эффектов (например, elx_accuracy даёт +10 к точности и поднимает верхний кап с 80 до 85).
	• Нижний порог (пол): min_cap = min_cap_override if min_cap_override is not None else 15 (нужно для приёма melee_heavy 10 «Сокрушение», где пол точности 70%).
	• Верхний порог (кап): max_cap = 85 при активном elx_accuracy, иначе 80.
	• Возвращает int(clamp(round(raw_hit), min_cap, max_cap)).
3. calc_monster_hit_chance(monster_accuracy: int, player_evasion: int, monster_debuffs: list[dict] | None = None) -> int:
	• Учитывает дебаффы на монстре (например, «Оглушающий удар» melee_heavy 3 или «Проклятие слабости» spl_weakness дают -10 к accuracy).
	• Возвращает int(clamp(monster_accuracy + debuff_acc - player_evasion, 15, 80)).

Г. Расчёт урона, критов, резистов и поглощения бронёй (§2.2, §2.4, §5.1, §22.1–22.2)

1. get_damage_multiplier(damage_type: str, target_affinities: dict[str, float], has_elemental_breakthrough: bool = False) -> float:
	• Достаёт mult = target_affinities.get(damage_type, 1.0).
	• Если has_elemental_breakthrough is True (перк pyromancy 10 «Стихийный прорыв», §22.2):
		• Сопротивление 0.75 превращается в 1.0 (if 0.0 < mult < 1.0: mult = 1.0).
		• Уязвимость > 1.0 (например 1.25) усиливается до 1.5 (if mult > 1.0: mult = 1.5).
	• Возвращает mult.
2. apply_armor_absorption(typed_damage: float, target_defense: int, ignore_armor_ratio: float = 0.0) -> float:
	• effective_def = max(0.0, target_defense * (1.0 - ignore_armor_ratio))
	• Формула (§2.2 п.3): typed_damage * (10.0 / (10.0 + effective_def)).
3. roll_player_weapon_attack(player: dict, weapon_stats: dict, target_stats: dict, target_affinities: dict[str, float], rng: random.Random, active_effects: list[dict] | None = None, monster_debuffs: list[dict] | None = None, damage_multiplier_bonus: float = 1.0, min_hit_override: int | None = None) -> dict:
	• Считает hit_chance = calc_player_hit_chance(...).
	• Проверка попадания: roll = rng.randint(0, 100). Если roll > hit_chance → возвращает {"hit": False, "hitChance": hit_chance, "damage": 0, "isCrit": False, "damageType": weapon_stats["type"]}.
	• Сырой урон (§2.2 п.1):
		• base_roll = rng.randint(weapon_stats["min"], weapon_stats["max"])
		• primary_stat берётся по маппингу: melee_heavy -> strength, melee_light -> agility. Учитывается бонус силы от elx_berserk (+2), если активен.
		• raw_damage = (base_roll * (1.0 + weapon_skill * 0.05) + (primary_stat - 1) * 0.5) * damage_multiplier_bonus (где damage_multiplier_bonus = 1.5 при приёме «Сокрушение» melee_heavy 10).
	• Модификатор уязвимости: res_mult = get_damage_multiplier(weapon_stats["type"], target_affinities). typed_damage = raw_damage * res_mult.
	• Поглощение бронёй:
		• Учитывает пробитие брони: если у игрока перк melee_heavy >= 6 («Раскол брони», §22.1), ignore_armor_ratio = 0.25.
		• Учитывает снижение защиты монстра от дебаффов (например, «Иссушение» hexes 6 снижает defense на -2).
		• absorbed_damage = apply_armor_absorption(typed_damage, effective_target_def, ignore_armor_ratio).
	• Критический удар (§2.4, §22.1):
		• Критует только оружие игрока.
		• crit_chance = 5 + (5 if has_lunge(player) else 0) (веха melee_light 3 «Выпад» → 10%).
		• crit_mult = 2.0 if has_deadly_precision(player) else 1.5 (веха melee_light 10 «Смертоносная точность» → ×2.0).
		• Проверка крита: is_crit = (rng.randint(1, 100) <= crit_chance).
		• Если is_crit: final_damage = absorbed_damage * crit_mult, иначе absorbed_damage.
	• Округление итогового урона: int_damage = max(1, round(final_damage)) если res_mult > 0 и base_roll > 0 (или 0 при иммунитете res_mult == 0.0 / сломанном оружии с 0 урона).
	• Возвращает словарь: {"hit": True, "hitChance": hit_chance, "damage": int_damage, "isCrit": is_crit, "damageType": weapon_stats["type"], "resMultiplier": res_mult}.
4. roll_monster_attack(monster_stats: dict, monster_damage_type: str, player: dict, game_data: GameData, rng: random.Random, active_effects: list[dict] | None = None, monster_debuffs: list[dict] | None = None, ignore_armor_ratio: float = 0.0) -> dict:
	• Считает mob_hit_chance = calc_monster_hit_chance(...).
	• При промахе (rng.randint(0, 100) > mob_hit_chance) → {"hit": False, "hitChance": mob_hit_chance, "damage": 0, "damageType": monster_damage_type}.
	• Бросок урона монстра: raw = rng.randint(monster_stats["min"], monster_stats["max"]) (минус штраф урона от дебаффа spl_weakness, но не ниже 1).
	• Защита игрока: player_def из get_effective_armor_stats + бонусы от эффектов (elx_ironskin +3, spl_stone_ward +4, щит «Второго дыхания» +5).
	• Поглощение бронёй: final = apply_armor_absorption(raw, player_def, ignore_armor_ratio) (для кастеров типа карги/призрака/лича ignore_armor_ratio = 0.5).
	• Перк armor_mastery 10 («Несокрушимый», §22.1): входящий урон не может превысить 35% от MaxHP игрока за один удар (cap = max(1, math.floor(player["resources"]["hp"]["max"] * 0.35))).
	• Итог: int_damage = max(1, round(final)) (применённый к cap, если есть перк).
	• Возвращает {"hit": True, "hitChance": mob_hit_chance, "damage": int_damage, "damageType": monster_damage_type}.

5. Критерии приёмки (tests/test_combat_math.py)

1. Проверка формулы calc_player_hit_chance: пол 15%, кап 80%, подъём капа до 85% при активной elx_accuracy, пол 70% при «Сокрушении».
2. Проверка гиперболы брони: при def = 0 проходит 100% урона, при def = 10 проходит ровно 50%, при def = 10 и ignore_armor_ratio = 0.5 проходит 66.7%.
3. Проверка эталонного примера из §2.2: Fine Sword (3..5), melee_heavy = 10, strength = 6 выдаёт rawDamage строго в диапазоне 7.0..10.0.
4. Проверка перков: «Привычка к весу» режет штраф лат вдвое; «Несокрушимый» (armor_mastery 10) режет входящий ваншот-урон до 35% от MaxHP; «Стихийный прорыв» (pyromancy 10) превращает 0.75 в 1.0 и 1.25 в 1.5.
5. Проверка скейлинга сложности scale_monster_stats для 0.75 / 1.0 / 1.4 / 2.0.
