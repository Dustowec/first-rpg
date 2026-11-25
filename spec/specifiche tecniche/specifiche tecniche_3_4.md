
ТЗ на разработку — Блок 3.4: Боевой автомат (Combat State Machine), побег и раздача наград


1. Цель задачи

Реализовать полный цикл пошагового боя (engine/combat.py) по правилам §2.4, §5.2, §6, §7.1, §27.2–27.4 и §30.1 спеки. Модуль должен управлять инициацией боя (обычное нападение за 1 AP и принудительная засада за 0 AP), исполнением раундов (атаки, магия, расходники, отступление), ИИ и спецспособностями монстров, последовательными боями в логове (босс + 2 стража), завершением боя (победа, побег, гибель игрока) и выдачей наград (XP, золото, лут).

2. Архитектурные ограничения и структуры данных

• Никакого UI: Модуль работает как чистый автомат state + action -> (new_state, events) без print() и input().
• Состояние активного боя (world["activeCombat"]):
	• Пока world["inCombat"] is False, world["activeCombat"] = None.
	• При старте боя world["inCombat"] = True и создаётся структура world["activeCombat"]:
{
  "nodeId": "node_07",
  "isAmbush": false,
  "round": 1,
  "queueIndex": 0,
  "monster": {
    "mobId": "mob_wolf_forest",
    "hp": 6,
    "maxHp": 6,
    "activeEffects": []
  }
}

• 
	• (Где queueIndex используется для логова из 3 врагов: 0 — первый страж, 1 — второй страж, 2 — босс).
• Хранение врагов в узле карты (node["state"]):
	• В обычной локации node["state"]["monster"] — один объект {"mobId": "...", "revealed": bool, "hp": int, "maxHp": int} или None.
	• В логове (type == "lair") при спавне генерируется очередь из 3 врагов в node["state"]["lairQueue"] (2 стража + босс), а node["state"]["monster"] указывает на текущего активного противника.

3. Структура файлов (создать)
project_root/
├── engine/
│   └── combat.py            # Боевой автомат: старт, раунд, ИИ монстра, побег, победа, награды
└── tests/
    └── test_combat.py       # Интеграционные тесты полного цикла боя, засад, побега, логова и лута


4. Детальные требования к модулю engine/combat.py


А. Старт боя start_combat(state: dict, game_data: GameData, is_ambush: bool = False, rng: random.Random | None = None, session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]

1. Проверяет, что world["inCombat"] is False и в текущем узле карты (map["currentNodeId"]) есть живой монстр.
2. Правило стелса и AP (§27.2, §27.4):
	• Если is_ambush is False:
		• Требует monster["revealed"] is True (нельзя напасть на скрытого монстра без «Осмотреться» или пережитой засады — иначе событие {"id": "err_monster_not_revealed"}).
		• Трата 1 AP: вызывает advance_time(state, steps=1, ...) до начала боя (если игрок умер от голода при трате этого AP — возвращает результат смерти!).
	• Если is_ambush is True:
		• Принудительно помечает monster["revealed"] = True, AP не тратится (0 AP).
3. Инициализирует world["inCombat"] = True, world["combatFlags"] = {"crushingCooldown": 0, "secondWindUsed": False} и заполняет world["activeCombat"].
4. Определение первого хода (§2.4):
	• Вызывает determine_first_attacker(player, scaled_stats, is_ambush, rng).
	• Если первым бьёт монстр ("monster"): сразу выполняет атаку монстра (через _execute_monster_turn) до передачи управления игроку! Если игрок погиб от первого удара — вызывает handle_player_death(state, reason="combat", ...).
5. Возвращает (new_state, events + [{"id": "combat_started", "mobId": mob_id, "isAmbush": is_ambush, "firstAttacker": first}]).

Б. Выполнение хода игрока combat_step(state: dict, command: dict, game_data: GameData, rng: random.Random | None = None, session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]

Принимает command вида {"type": ...}:
1. {"type": "flee"} — Отступление (§2.4, §27.3):
	• Бесплатно по AP (0 AP).
	• Бросок rng.randint(0, 100) <= 50:
		• Успех (<= 50):
			• Сохраняет текущий hp монстра в узел карты (node["state"]["monster"]["hp"] = combat_mob["hp"], revealed = True).
			• Сбрасывает world["inCombat"] = False, world["activeCombat"] = None, world["combatFlags"] = {}.
			• Игрок остаётся в текущей локации. Возвращает (new_state, [{"id": "combat_fled_success"}]).
		• Провал (> 50):
			• Раунд потерян, событие {"id": "combat_fled_failed"}, управление переходит к ходу монстра и завершению раунда (пункты В и Г).
2. {"type": "attack"} или {"type": "crushing_strike"} — Атака оружием:
	• Если "crushing_strike": проверяет can_use_crushing_strike(state) (иначе err_skill_on_cooldown), ставит combatFlags["crushingCooldown"] = 4, атакует с damage_multiplier_bonus=1.5, min_hit_override=70.
	• Вызывает roll_player_weapon_attack(...).
	• При попадании:
		• Вычитает урон из combat_mob["hp"].
		• Вызывает register_weapon_hit(state) (износ оружия / трата заточки).
		• Вызывает process_weapon_coating_on_hit(state, combat_mob, affinities) (срабатывание oil_fire или oil_poison).
		• Вызывает apply_on_weapon_hit_perks(state, combat_mob, rng) («Оглушающий удар» melee_heavy 3).
3. {"type": "cast", "spellId": "..."} — Применение заклинания:
	• Вызывает cast_spell(state, spell_id, game_data, target_monster=combat_mob, target_affinities=affinities, rng=rng). При ошибке (err_not_enough_mp и т.п.) возвращает её сразу, не тратя ход.
4. {"type": "use_item", "itemId": "..."} — Расходник в бою:
	• Вызывает use_consumable(state, item_id, game_data, target_monster=combat_mob, target_affinities=affinities, rng=rng). При ошибке возвращает её сразу, не тратя ход.
5. Проверка смерти монстра после действия игрока:
	• Если combat_mob["hp"] <= 0: переходит к обработке победы (_on_monster_defeated, пункт Д) и завершает шаг (монстр не контратакует).

В. Ход монстра и его спецспособности (_execute_monster_turn, §5.2)

Выполняется, если монстр жив и побег не удался:
1. Учитывает specialTraits из JSON монстра:
	• ignoreArmorRatio (например 0.5 у mob_swamp_hag, mob_wraith, mob_lich_lesser).
	• Регенерация троллей (regenHp, regenIntervalRounds): если у монстра задан regenHp (например, +1 HP каждые 2 раунда у mob_troll_hill или +2 HP каждый 1 раунд у mob_troll_ancient), восстанавливает combat_mob["hp"] = min(maxHp, hp + regenHp) в начале хода монстра (если round % regenIntervalRounds == 0).
2. Бросает атаку через roll_monster_attack(...).
3. При попадании по игроку:
	• Вычитает урон из player["resources"]["hp"]["current"].
	• Вызывает register_armor_hit(state) (износ брони).
	• Отравляющий укус паука (onHitDot у mob_spider_giant): если в specialTraits есть onHitDot и rng.random() <= chance (25%), вешает на игрока poison (-1 HP / ход на 3 хода) в world["activeEffects"].
	• Проверяет триггер «Второе дыхание» (check_second_wind_trigger(state)).
4. Если player["resources"]["hp"]["current"] <= 0:
	• Вызывает handle_player_death(state, reason="combat", ...) и возвращает сброшенное состояние!

Г. Завершение раунда боя

1. Вызывает tick_combat_round_effects(state, combat_mob) (тикают яды/горение/баффы игрока и монстра).
2. Уменьшает combatFlags["crushingCooldown"] = max(0, cd - 1).
3. Проверяет:
	• Не умер ли монстр от DoT (горения/яда) в конце раунда → если combat_mob["hp"] <= 0, вызывает _on_monster_defeated.
	• Не умер ли игрок от DoT в конце раунда → если hp.current <= 0, вызывает handle_player_death(state, reason="combat", ...).
4. Увеличивает activeCombat["round"] += 1.

Д. Победа над монстром и раздача наград (_on_monster_defeated, §5.2, §6, §27.4, §30.1)

1. Срабатывает перк «Жатва душ» (apply_on_monster_killed_perks(state, combat_mob)).
2. Увеличивает world["killsTotal"] += 1.
3. Награды (§6):
	• Начисляет опыт через grant_xp(state, monster_data["rewards"]["xp"]).
	• Начисляет золото: gold_gain = rng.randint(gold_min, gold_max), player["gold"] += gold_gain.
	• Роллит лут по rewards["lootTable"]: для каждой записи если rng.random() <= entry["chance"], добавляет rng.randint(entry["min"], entry["max"]) штук entry["itemId"] через add_item.
4. Обновление узла карты и логова (§27.4, §30.1):
	• Если в логове (lairQueue) остались следующие противники (queueIndex + 1 < len(lairQueue)):
		• Переключает бой на следующего стража/босса из очереди (queueIndex += 1, обновляет activeCombat["monster"] и node["state"]["monster"], round = 1) — три последовательных боя один на один!
	• Иначе (врагов в локации больше нет):
		• Ставит node["state"]["monster"] = None, node["state"]["daysSinceCleared"] = 0 (запускает таймер респавна раз в 5 дней!).
		• Завершает бой: world["inCombat"] = False, world["activeCombat"] = None, world["combatFlags"] = {}.

5. Критерии приёмки (tests/test_combat.py)

1. Невозможность начать обычный бой (is_ambush=False) с нераскрытым монстром (revealed=False); списание 1 AP при обычном старте и 0 AP при засаде.
2. Засада (is_ambush=True) всегда даёт монстру первый удар без броска инициативы.
3. Отступление (flee): при успехе (<= 50) бой завершается, игрок остаётся в том же узле карты, а у монстра в узле сохраняется остаток HP и revealed == True.
4. Полный бой с победой: начисление XP, золота, ролл лута, инкремент killsTotal и очистка node["state"]["monster"].
5. Логово (lair): последовательный переход от 1-го стража ко 2-му и затем к боссу после победы над каждым.
6. Гибель игрока в бою (hp <= 0) запускает permadeath-сброс из блока 1.1.