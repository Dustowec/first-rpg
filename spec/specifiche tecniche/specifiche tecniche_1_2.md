
ТЗ на разработку — Блок 1.2 (обновлённый): Атомарная JSON-база (Предметы, Рецепты, Заклинания, Навыки)


1. Цель задачи

Реализовать чистый data-driven слой контента: каждая игровая сущность (предмет, рецепт, заклинание, навык) хранится в отдельном JSON-файле data/<category_dir>/<id>.json, где "id" служит уникальным ключом индексации в движке. Написать генератор базы (scripts/build_static_data.py) и загрузчик с проверкой ссылочной целостности (engine/data_loader.py).

2. Архитектурные ограничения и унификация схем

• Правило «1 файл = 1 сущность»: Имя файла строго <id>.json (например, data/weapons/wpn_sword_fine.json). Загрузчик проверяет совпадение file.stem == data["id"] и уникальность всех id в рамках проекта.
• Единый формат урона оружия (stats.damage): Унифицируем поле из §3.1 и §6 в единую структуру:
"stats": {
  "damage": { "min": 3, "max": 5, "type": "slashing", "hidden": false },
  "skill": { "id": "melee_heavy", "hidden": false },
  "durability": { "max": 55, "hidden": false }
}

• Единая экономика (economy): У каждого предмета есть блок:
"economy": { "buyPrice": int, "sellPrice": int, "canBuy": bool, "canFind": bool }.
• Двуязычность: Все сущности содержат "name": {"en": "...", "ru": "..."} и "description": {"en": "...", "ru": "..."}.

3. Структура папок проекта
project_root/
├── data/
│   ├── weapons/             # wpn_*.json (13 файлов)
│   ├── armor/               # arm_*.json (9 файлов)
│   ├── food/                # food_*.json (11 файлов)
│   ├── materials/           # junk_*.json, mat_*.json (6 файлов)
│   ├── consumables/         # pot_*.json, elx_*.json, oil_*.json, bmb_*.json (12 файлов)
│   ├── repair_kits/         # rep_*.json (3 файла)
│   ├── recipes/             # rec_*.json (12 файлов)
│   ├── spells/              # spl_*.json (9 файлов)
│   └── skills/              # skl_*.json (9 файлов)
├── engine/
│   └── data_loader.py       # Рекурсивный загрузчик JSON-базы + проверка ссылочной целостности
├── scripts/
│   └── build_static_data.py # Скрипт генерации всех отдельных JSON-файлов
└── tests/
    └── test_static_data.py  # Тесты загрузки, уникальности id и валидности ссылок


4. Полный перечень JSON-файлов для генерации (scripts/build_static_data.py)


А. data/weapons/<id>.json (category: "weapon")

Маппинг подтипов: blunt → skill.id: "melee_heavy", damage.type: "blunt"; sword → skill.id: "melee_heavy", damage.type: "slashing"; spear → skill.id: "melee_light", damage.type: "piercing".
• wpn_club_simple (blunt, Простая дубина): урон 1..2, прочность 15, цена 3 / 0, canBuy: true, canFind: true
• wpn_club_regular (blunt, Дубина): урон 2..3, прочность 20, цена 15 / 3, canBuy: true, canFind: true
• wpn_club_heavy (blunt, Тяжёлая дубина): урон 3..4, прочность 35, цена 80 / 18, canBuy: true, canFind: false
• wpn_spear_stick (spear, Копьё-палка): урон 0..2, прочность 15, цена 5 / 1, canBuy: true, canFind: true
• wpn_spear_regular (spear, Обычное копьё): урон 1..4, прочность 30, цена 20 / 5, canBuy: true, canFind: true
• wpn_spear_military (spear, Армейское копьё): урон 3..4, прочность 40, цена 100 / 20, canBuy: true, canFind: false
• wpn_sword_rusty (sword, Ржавый меч): урон 1..3, прочность 15, цена 7 / 2, canBuy: true, canFind: true
• wpn_sword_regular (sword, Обычный меч): урон 2..4, прочность 35, цена 25 / 7, canBuy: true, canFind: true
• wpn_sword_fine (sword, Качественный меч): урон 3..5, прочность 55, цена 120 / 30, canBuy: true, canFind: false
• Оружие Тира 3 и 4 (§3.1):
	• wpn_sword_steel (sword, Стальной меч, Тир 3): урон 4..6, прочность 55, цена 260 / 65, canBuy: true, canFind: false
	• wpn_spear_partisan (spear, Боевой протазан, Тир 3): урон 3..6, прочность 50, цена 240 / 60, canBuy: true, canFind: false
	• wpn_club_warhammer (blunt, Боевой молот, Тир 3): урон 4..5, прочность 55, цена 220 / 55, canBuy: true, canFind: false
	• wpn_sword_runic (sword, Рунный клинок, Тир 4): урон 5..8, прочность 60, цена 650 / 160, canBuy: true, canFind: false

Б. data/armor/<id>.json (category: "armor")

Поля stats: defense (value, hidden: false), evasion (value, hidden: false), durability (max, hidden: false):
• arm_cloth_poor (cloth, Паршивая ткань): def: 1, eva: 4, dur: 15, цена 8 / 1, canBuy: true, canFind: true
• arm_cloth_regular (cloth, Стёганая куртка): def: 2, eva: 6, dur: 20, цена 22 / 5, canBuy: true, canFind: true
• arm_cloth_fine (cloth, Тканый кафтан мастера): def: 3, eva: 8, dur: 30, цена 65 / 15, canBuy: true, canFind: false
• arm_leather_poor (leather, Потёртая кожанка): def: 2, eva: 0, dur: 20, цена 18 / 4, canBuy: true, canFind: true
• arm_leather_regular (leather, Дублёная кожа): def: 4, eva: 0, dur: 35, цена 55 / 12, canBuy: true, canFind: true
• arm_leather_fine (leather, Усиленная кожа): def: 6, eva: 2, dur: 55, цена 140 / 35, canBuy: true, canFind: false
• arm_plate_poor (plate, Ржавые латы): def: 5, eva: -4, dur: 25, цена 110 / 25, canBuy: true, canFind: true
• arm_plate_regular (plate, Стальные латы): def: 8, eva: -6, dur: 45, цена 240 / 60, canBuy: true, canFind: false
• arm_plate_fine (plate, Рыцарские латы): def: 10, eva: -8, dur: 60, цена 420 / 105, canBuy: true, canFind: false

В. data/food/<id>.json (category: "food")

• food_moss (foraged, Мох): hpRestore: 0, satietyOnly: true, цена 0 / 0, canBuy: false, canFind: true
• food_red_mushroom (foraged, Красный гриб): hpRestore: 0, dotEffect: {"type": "poison", "hpDeltaPerTurn": -1, "ticks": 3}, цена 0 / 0, canBuy: false, canFind: true
• food_berries (foraged, Ягоды): hpRestore: 1, цена 1 / 0, canBuy: true, canFind: true
• food_fish (raw, Сырая рыба): hpRestore: 1, цена 1 / 0, canBuy: true, canFind: true
• food_roots (foraged, Коренья): hpRestore: 1, цена 1 / 0, canBuy: true, canFind: true
• food_cabbage (vegetable, Капуста): hpRestore: 2, цена 2 / 1, canBuy: true, canFind: true
• food_mushrooms (foraged, Грибы): hpRestore: 2, цена 2 / 1, canBuy: true, canFind: true
• food_bread (baked, Хлеб): hpRestore: 3, цена 3 / 1, canBuy: true, canFind: false
• food_dried_fish (preserved, Вяленая рыба): hpRestore: 3, цена 3 / 1, canBuy: true, canFind: false
• food_cured_fatback (preserved, Сало): hpRestore: 4, цена 5 / 2, canBuy: true, canFind: false
• food_boiled_potatoes (cooked, Варёная картошка): hpRestore: 5, цена 10 / 5, canBuy: true, canFind: false

Г. data/materials/<id>.json (category: "junk" или "material")

• junk_rags (category: "junk", subCategory: "scrap", Тряпьё): цена 1 / 0, canBuy: false, canFind: true
• junk_stone (category: "junk", subCategory: "scrap", Булыжник): цена 1 / 0, canBuy: false, canFind: true
• junk_scrap_metal (category: "junk", subCategory: "scrap", Металлолом): цена 2 / 1, canBuy: false, canFind: true
• junk_broken_hilt (category: "junk", subCategory: "scrap", Сломанная рукоять меча): цена 2 / 1, canBuy: false, canFind: true
• mat_bone (category: "material", subCategory: "trophy", Звериная кость): цена 2 / 1, canBuy: false, canFind: false
• mat_wolf_eye (category: "material", subCategory: "trophy", Волчий глаз): цена 3 / 1, canBuy: false, canFind: false

Д. data/consumables/<id>.json (category: "consumable")

• pot_antidote (subCategory: "potion", Противоядие): stats: {"cureEffects": ["poison", "bleeding"]}, цена 12 / 3, canBuy: true, canFind: true
• pot_heal_minor (subCategory: "potion", Малое зелье лечения): stats: {"hpRestore": {"value": 6, "hidden": false}}, цена 15 / 4, canBuy: true, canFind: true
• pot_heal_regular (subCategory: "potion", Зелье лечения): stats: {"hpRestore": {"value": 14, "hidden": false}}, цена 35 / 9, canBuy: true, canFind: true
• pot_heal_greater (subCategory: "potion", Большое зелье лечения): stats: {"hpRestore": {"value": 28, "hidden": false}}, цена 75 / 18, canBuy: true, canFind: false
• pot_mana_minor (subCategory: "potion", Малое зелье маны): stats: {"mpRestore": {"value": 4, "hidden": false}}, цена 18 / 4, canBuy: true, canFind: true
• pot_mana_regular (subCategory: "potion", Зелье маны): stats: {"mpRestore": {"value": 10, "hidden": false}}, цена 40 / 10, canBuy: true, canFind: false
• elx_accuracy (subCategory: "elixir", Настойка зоркости): stats: {"buffEffect": {"stat": "accuracy", "value": 10, "maxHitCapOverride": 85, "durationCombatTurns": 5, "hidden": false}}, цена 25 / 6, canBuy: true, canFind: false
• elx_ironskin (subCategory: "elixir", Отвар каменной кожи): stats: {"buffEffect": {"stat": "defense", "value": 3, "durationCombatTurns": 5, "hidden": false}}, цена 30 / 7, canBuy: true, canFind: false
• elx_berserk (subCategory: "elixir", Настойка ярости): stats: {"buffEffect": {"stat": "strength", "value": 2, "evasionPenalty": -5, "durationCombatTurns": 4, "hidden": false}}, цена 35 / 8, canBuy: true, canFind: false
• oil_poison (subCategory: "coating", Болотный яд): stats: {"coatingEffect": {"dotType": "poison", "hpDeltaPerTurn": -2, "dotTurns": 3, "charges": 3, "hidden": false}}, цена 28 / 7, canBuy: true, canFind: false
• oil_fire (subCategory: "coating", Горючее масло): stats: {"coatingEffect": {"bonusDamage": 2, "damageType": "fire", "charges": 4, "hidden": false}}, цена 32 / 8, canBuy: true, canFind: false
• bmb_fire (subCategory: "bomb", Алхимический огонь): stats: {"damage": {"min": 5, "max": 7, "type": "fire", "hitChance": 80, "hidden": false}}, цена 40 / 10, canBuy: true, canFind: false

Е. data/repair_kits/<id>.json (category: "repair_kit")

• rep_whetstone (subCategory: "weapon", Точильный камень): stats: {"durabilityRestore": 10, "targetCategories": ["weapon"]}, цена 10 / 2, canBuy: true, canFind: false
• rep_patch_kit (subCategory: "armor", Набор для заплат): stats: {"durabilityRestore": 10, "targetSubCategories": ["cloth", "leather"]}, цена 12 / 3, canBuy: true, canFind: false
• rep_smith_kit (subCategory: "universal", Походный набор кузнеца): stats: {"durabilityRestore": 15, "targetCategories": ["weapon", "armor"]}, цена 25 / 6, canBuy: true, canFind: false

Ж. data/recipes/<id>.json (category: "recipe")

12 отдельных файлов (rec_pot_heal_minor, rec_pot_antidote, rec_oil_poison, rec_oil_fire, rec_food_stew, rec_pot_heal_regular, rec_pot_mana_minor, rec_elx_accuracy, rec_elx_ironskin, rec_rep_whetstone, rec_rep_patch_kit, rec_rep_smith_kit) по схеме §17 спеки.

З. data/spells/<id>.json (category: "spell")

9 отдельных файлов (spl_spark, spl_frost_shard, spl_fireball, spl_minor_mend, spl_stone_ward, spl_purify, spl_weakness, spl_venom_touch, spl_life_drain) по схеме §20.1 спеки.

И. data/skills/<id>.json (category: "skill")

9 отдельных файлов (skl_melee_heavy, skl_melee_light, skl_armor_mastery, skl_pyromancy, skl_restoration, skl_hexes, skl_alchemy, skl_crafting, skl_scavenging) по схеме §23 спеки. Важно: id внутри файла навыка и имя файла совпадают с ключами в player.skills (melee_heavy, melee_light и т.д. — т.е. data/skills/melee_heavy.json с "id": "melee_heavy"), чтобы не плодить лишний маппинг имён.

5. Требования к engine/data_loader.py

• Класс GameData рекурсивно обходит data/**/*.json, загружает каждый файл и индексирует в единый реестр entities: dict[str, dict], а также в типизированные словари items, recipes, spells, skills.
• Проверяет при загрузке:
	1. Уникальность каждого "id" во всей базе данных (при дубликате — ValueError).
	2. Совпадение имени файла с полем "id" (path.stem == entity["id"]).
	3. Ссылочную целостность: все itemId в recipes существуют в items; все requiredSkill.id в recipes и spells существуют в skills.
• Публичные методы: get(entity_id: str) -> dict, get_item(item_id: str) -> dict, get_recipe(recipe_id: str) -> dict, get_spell(spell_id: str) -> dict, get_skill(skill_id: str) -> dict, list_items(category: str | None = None, can_find_only: bool = False) -> list[dict].

6. Критерии приёмки (tests/test_static_data.py)

1. Запуск scripts/build_static_data.py создаёт ровно 84 отдельных JSON-файла в соответствующих подпапках data/.
2. GameData("data") успешно индексирует все файлы, подтверждает совпадение filename == id и отсутствие дублей.
3. Тест на ошибку при дублировании id или битой ссылке в рецепте выбрасывает ValueError.
4. Все стартовые предметы из state_template.json (wpn_club_simple, arm_cloth_poor, food_berries, food_bread, pot_heal_minor) находятся через game_data.get_item(...).