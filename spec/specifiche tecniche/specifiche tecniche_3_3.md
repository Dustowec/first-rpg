
ТЗ на разработку — Блок 3.3: Магическая система, заклинания и боевые перки


1. Цель задачи

Реализовать модуль магической системы (engine/magic.py) и триггеры боевых перков (§18, §19, §20, §22.1–22.2). Модуль должен обеспечивать проверку доступности заклинаний по уровню школы, расчёт стоимости MP (с учётом перка «Концентрация»), расчёт попадания и силы заклинаний (spellHitChance, spellPower), применение всех 9 заклинаний (урон, лечение, снятие дебаффов, баффы защиты, проклятия, яд, вампиризм), а также триггерные вехи боя («Второе дыхание», «Жатва душ», «Оглушающий удар», «Сокрушение»).

2. Архитектурные ограничения и стыки

• Никакого UI: Функции принимают (state, spell_id, game_data, target_monster, ...) и возвращают (new_state, events) без print() и input().
• Взаимодействие с активными эффектами:
	• Баффы игрока (spl_stone_ward, щит «Второго дыхания») складываются в state["world"]["activeEffects"] с ticksLeft, чтобы они тикали в конце каждого раунда (tick_combat_round_effects из блока 3.2) и дотикивали шагами суток после боя.
	• Дебаффы/DoT на монстре (burn, poison, spl_weakness, spl_frost_shard, perk_stunning_blow) складываются в target_monster.setdefault("activeEffects", []) с ticksLeft.
• Боевые кулдауны и одноразовые триггеры (combatFlags): Временные флаги текущего боя (перезарядка «Сокрушения», срабатывание «Второго дыхания» 1 раз за бой) хранятся в state["world"].setdefault("combatFlags", {}) и очищаются при завершении боя.

3. Структура файлов (создать)
project_root/
├── engine/
│   └── magic.py             # Заклинания (3 школы), расчёт магии и триггеры боевых перков
└── tests/
    └── test_magic.py        # Юнит-тесты всех 9 заклинаний, игнора 50% брони и перков боя/магии


4. Детальные требования к модулю engine/magic.py


А. Доступность и стоимость заклинаний (§11, §20, §22.2)

1. get_available_spells(player: dict, game_data: GameData) -> list[dict]:
	• Возвращает список всех заклинаний из game_data.spells.values(), для которых player["skills"][spell["subCategory"]] >= spell["requiredSkill"]["level"].
2. get_spell_mp_cost(player: dict, spell: dict) -> int:
	• Базовая стоимость: cost = spell["cost"]["mp"].
	• Перк pyromancy 6 («Концентрация», §22.2): если spell["subCategory"] == "pyromancy" и has_concentration(player) → cost = max(1, cost - 1).
	• Возвращает cost.

Б. Формулы магии (§18.1, §22.2)

1. calc_spell_hit_chance(player: dict, school_id: str, target_evasion: int) -> int:
	• Формула: 55 + (school_skill * 2.5) + ((intelligence - 1) * 1.5) - (target_evasion * 0.5)
	• Клампится в [25, 85]: int(max(25, min(85, round(raw)))).
	• (Лечение и баффы на себя имеют шанс попадания 100% без броска).
2. calc_spell_power(player: dict, school_id: str, min_val: int, max_val: int, rng: random.Random) -> float:
	• Базовый бросок: base = rng.randint(min_val, max_val).
	• Формула (§18.1): power = base * (1.0 + school_skill * 0.05) + ((intelligence - 1) * 0.75).
	• Перк restoration 3 («Бережливость», §22.2): если school_id == "restoration" (лечебные эффекты) и has_frugality(player) → power *= 1.20.
	• Возвращает power.

В. Применение заклинания cast_spell(state: dict, spell_id: str, game_data: GameData, target_monster: dict | None = None, target_affinities: dict[str, float] | None = None, rng: random.Random | None = None) -> tuple[dict, list[dict]]

1. Проверяет, что spell_id существует, навык школы игрока >= requiredSkill.level (иначе err_spell_locked) и player["resources"]["mp"]["current"] >= mp_cost (иначе err_not_enough_mp).
2. Проверяет контекст: атакующие заклинания и проклятия требуют world["inCombat"] is True и target_monster is not None (лечение spl_minor_mend и spl_purify можно применять и в бою, и вне боя).
3. Списывает ману: mp.current -= mp_cost.
4. Реализует механику каждого из 9 заклинаний (§20):
	• Школа pyromancy (Стихии):
		• spl_spark (Огненная искра, 2 MP, мин. навык 0):
			• Проверка попадания по calc_spell_hit_chance. При промахе — событие spell_missed.
			• Урон 2..3 типом fire: умножается на get_damage_multiplier("fire", affinities, has_elemental_breakthrough(player)), проходит через apply_armor_absorption(..., target_defense, ignore_armor_ratio=0.5) (§18.1 — игнор 50% физической брони). Заклинания не критуют (§2.4).
			• Шанс 30% (rng.random() <= 0.30) наложить burn: -1 HP / ход на 2 хода (+1 ход при перке pyromancy 3 «Жар пламени» → итого 3 хода).
		• spl_frost_shard (Ледяной осколок, 4 MP, мин. навык 3):
			• Проверка попадания. Урон 4..6 типом ice (с учётом affinities и игнором 50% брони).
			• Накладывает на цель дебафф evasionDelta: -10 на 3 хода (ticksLeft: 3).
		• spl_fireball (Огненный шар, 8 MP, мин. навык 6):
			• Проверка попадания. Урон 8..11 типом fire (с учётом affinities и игнором 50% брони).
			• Гарантированно накладывает burn: -2 HP / ход на 3 хода (+1 ход при перке pyromancy 3 «Жар пламени» → итого 4 хода).
	• Школа restoration (Восстановление):
		• spl_minor_mend (Малое исцеление, 2 MP, мин. навык 0):
			• Лечит round(calc_spell_power(player, "restoration", 4, 5, rng)) HP (уже включает бонус +20% от restoration 3).
		• spl_stone_ward (Магический покров, 4 MP, мин. навык 3):
			• Вешает на игрока бафф {"id": "spl_stone_ward", "category": "buff", "stat": "defense", "value": 4, "ticksLeft": duration}, где duration = 4 + (2 if has_sturdy_barrier(player) else 0) (веха restoration 6 «Стойкий барьер» даёт +2 хода → 6 ходов).
		• spl_purify (Очищение, 5 MP, мин. навык 4):
			• Снимает с игрока эффекты poison и bleeding, а также лечит round(calc_spell_power(player, "restoration", 6, 8, rng)) HP.
	• Школа hexes (Порча):
		• spl_weakness (Проклятие слабости, 2 MP, мин. навык 0):
			• Проверка попадания. Вешает на монстра проклятие (isCurse: True): damageDelta: -2, accuracyDelta: -10, ticksLeft: 4.
			• Перк hexes 6 («Иссушение», §22.2): проклятия дополнительно добавляют defenseDelta: -2.
		• spl_venom_touch (Змеиное касание, 4 MP, мин. навык 3):
			• Проверка попадания. Урон 2..3 типом poison (с учётом affinities и игнором 50% брони; если у цели иммунитет poison == 0.0, урон и яд не проходят).
			• Накладывает на монстра poison: базово -2 HP / ход на 3 хода; при перке hexes 3 («Едкие токсины», §22.2) урон яда увеличивается на +1 HP / ход (итого -3 HP / ход).
		• spl_life_drain (Похищение жизни, 7 MP, мин. навык 6):
			• Проверка попадания. Наносит 5..7 урона типом arcane (с учётом affinities и игнором 50% брони).
			• Лечит кастера на 50% от фактически нанесённого урона (math.floor(dealt_damage * 0.5)).

Г. Боевые перки и триггеры (§22.1–22.2)

Реализовать хелперы для интеграции в боевой цикл (блок 3.4):
1. apply_on_weapon_hit_perks(state: dict, target_monster: dict, rng: random.Random) -> list[dict]:
	• Веха melee_heavy 3 («Оглушающий удар»): 20% шанс (rng.random() <= 0.20) наложить на монстра дебафф {"id": "perk_stunning_blow", "accuracyDelta": -10, "ticksLeft": 2}.
2. check_second_wind_trigger(state: dict) -> list[dict]:
	• Веха restoration 10 («Второе дыхание»): если has_second_wind(player), hp.current > 0 и hp.current < hp.max * 0.20, и флаг combatFlags.get("secondWindUsed") ещё False:
		• Ставит combatFlags["secondWindUsed"] = True.
		• Накладывает на игрока бафф {"id": "perk_second_wind", "category": "buff", "stat": "defense", "value": 5, "ticksLeft": 3 + (2 if has_sturdy_barrier(player) else 0)}.
		• Возвращает событие {"id": "perk_second_wind_triggered"}.
3. apply_on_monster_killed_perks(state: dict, target_monster: dict) -> list[dict]:
	• Веха hexes 10 («Жатва душ»): если has_soul_harvest(player) и на монстре в момент смерти висело любое проклятие (any(eff.get("isCurse") for eff in target_monster.get("activeEffects", []))):
		• Восстанавливает игроку +3 HP и +3 MP (с клампом до max).
		• Возвращает событие {"id": "perk_soul_harvest_triggered", "hpRestored": 3, "mpRestored": 3}.
4. can_use_crushing_strike(state: dict) -> bool:
	• Проверяет has_crushing_strike(player) (melee_heavy >= 10) и state["world"].get("combatFlags", {}).get("crushingCooldown", 0) == 0. При использовании ставит crushingCooldown = 4, а атака проходит через roll_player_weapon_attack с damage_multiplier_bonus=1.5 и min_hit_override=70.

5. Критерии приёмки (tests/test_magic.py)

1. Проверка формул calc_spell_hit_chance и calc_spell_power: скейлинг от уровня школы и интеллекта, отсутствие критов у заклинаний, игнорирование 50% физической брони цели.
2. Проверка перка pyromancy 6 («Концентрация»): spl_spark снижается с 2 MP до 1 MP (не опускается ниже 1), spl_fireball с 8 MP до 7 MP.
3. Проверка перка pyromancy 10 («Стихийный прорыв»): spl_fireball по цели с сопротивлением fire: 0.75 бьёт с множителем 1.0, а по цели с уязвимостью fire: 1.25 — с множителем 1.5.
4. Проверка spl_life_drain (восстанавливает 50% от нанесённого урона) и spl_purify (снимает poison и лечит).
5. Проверка срабатывания триггеров «Второе дыхание» (1 раз за бой при падении HP < 20%), «Жатва душ» (при добивании проклятого врага) и «Сокрушение» (перезарядка 4 хода, пол точности 70%, урон ×1.5).