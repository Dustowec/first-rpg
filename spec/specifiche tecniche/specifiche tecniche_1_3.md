
ТЗ на разработку — Блок 1.3: Атомарная JSON-база (Монстры, Биомы, NPC и строки RU)


1. Цель задачи

Дополнить data-driven контент-слой проекта оставшимися игровыми сущностями по принципу «1 файл = 1 сущность»: сгенерировать отдельные JSON-файлы для всех 24 монстров (data/monsters/<id>.json), 9 типов локаций (data/biomes/<id>.json), 7 персонажей NPC (data/npcs/<id>.json), а также файл локализации UI data/strings_ru.json. Расширить scripts/build_static_data.py и engine/data_loader.py с проверкой ссылочной целостности лута, пулов мобов и инвентарей торговцев.

2. Архитектурные ограничения

• Единый принцип «1 файл = 1 сущность»: Имя файла строго <id>.json, уникальность "id" проверяется на уровне всей папки data/.
• Чистое отделение текста от ядра (§33.2): Все шаблоны сообщений интерфейса, журналов и меню складываются в data/strings_ru.json, чтобы движок оперировал только ID событий, а рендер (CLI сейчас, Godot позже) подставлял строки.

3. Структура новых папок и файлов
project_root/
├── data/
│   ├── monsters/            # mob_*.json (24 файла по 5 тирам)
│   ├── biomes/              # biome_*.json (9 типов локаций: village, camp, road, meadow, forest_edge, ruins, deep_forest, swamp, lair)
│   ├── npcs/                # npc_*.json (7 файлов персонажей)
│   └── strings_ru.json      # Словарь строк UI и журналов событий (не entity-файл, загружается отдельно)
├── scripts/
│   └── build_static_data.py # Обновить: добавить генерацию monsters, biomes, npcs и strings_ru.json
├── engine/
│   └── data_loader.py       # Обновить: добавить загрузку monsters, biomes, npcs, strings + проверки ссылок
└── tests/
    └── test_world_data.py   # Тесты бестиария, биомов, NPC и локализации


4. Детальные требования к данным (scripts/build_static_data.py)


А. data/monsters/<id>.json (category: "monster")

Использовать эталонную схему §6. Поле affinities хранит только отличия от 1.0 (если типа урона нет, движок считает множитель 1.0), включая базовую матрицу §5.1 (beast: fire 1.25, slashing 1.25; undead: blunt 1.25, fire 1.25, piercing 0.75, poison 0.0; construct: blunt 1.25, slashing 0.75, piercing 0.75, poison 0.0; insect: fire 1.25, ice 1.25, blunt 0.75; humanoid: {}) плюс индивидуальные оверрайды и спецспособности (specialTraits).
Сгенерировать все 24 монстра из §5.2:
• Tier 1 (tier: 1):
	1. mob_rat_giant (beast, Гигантская крыса): hp: 4, dmg: 1..1 (piercing), def: 0, acc: 40, eva: 3, xp: 12, gold: 0..1, лут: mat_bone (0.15)
	2. mob_wolf_forest (beast, Лесной волк): hp: 6, dmg: 1..2 (slashing), def: 1, acc: 45, eva: 2, xp: 15, gold: 0..2, лут: mat_bone (0.30), mat_wolf_eye (0.10)
	3. mob_boar_wild (beast, Дикий кабан): hp: 9, dmg: 2..3 (piercing), def: 1, acc: 42, eva: 0, xp: 18, gold: 0..1, лут: mat_bone (0.40), food_cured_fatback (0.20)
	4. mob_bandit_scout (humanoid, Разведчик бандитов): hp: 8, dmg: 1..3 (blunt), def: 2, acc: 48, eva: 3, xp: 22, gold: 2..5, лут: junk_rags (0.25), food_bread (0.15)
	5. mob_wolf_alpha (beast, Вожак стаи, isElite: true): hp: 9, dmg: 2..3 (slashing), def: 1, acc: 50, eva: 4, xp: 25, gold: 0..3, лут: mat_bone (0.50), mat_wolf_eye (0.40)
• Tier 2 (tier: 2):
6. mob_scarecrow_animated (construct, Ожившее пугало): hp: 12, dmg: 2..3 (slashing), def: 4, acc: 45, eva: -2, xp: 45, gold: 0..2, лут: junk_rags (0.60), junk_stone (0.20), affinities: как construct, но fire: 1.5
7. mob_spider_giant (insect, Гигантский паук): hp: 12, dmg: 2..4 (piercing), def: 1, acc: 50, eva: 10, xp: 50, gold: 0..3, лут: junk_rags (0.40), specialTraits: {"onHitDot": {"type": "poison", "chance": 0.25, "hpDeltaPerTurn": -1, "ticks": 3}}
8. mob_ghoul (undead, Гуль): hp: 16, dmg: 2..4 (slashing), def: 2, acc: 48, eva: 2, xp: 55, gold: 2..6, лут: junk_broken_hilt (0.20)
9. mob_bandit_rogue (humanoid, Разбойник): hp: 14, dmg: 2..5 (slashing), def: 3, acc: 52, eva: 6, xp: 60, gold: 4..10, лут: junk_scrap_metal (0.25), food_dried_fish (0.15)
10. mob_bear_black (beast, Чёрный медведь, isElite: true): hp: 18, dmg: 3..5 (blunt), def: 3, acc: 50, eva: 0, xp: 70, gold: 0..2, лут: mat_bone (0.60), food_cured_fatback (0.30)
• Tier 3 (tier: 3):
11. mob_skeleton_warrior (undead, Скелет-воин): hp: 20, dmg: 3..5 (slashing), def: 4, acc: 58, eva: 5, xp: 95, gold: 3..12, лут: junk_scrap_metal (0.30), junk_broken_hilt (0.30)
12. mob_swamp_hag (humanoid, Болотная карга): hp: 18, dmg: 3..6 (poison), def: 2, acc: 62, eva: 8, xp: 120, gold: 8..20, лут: food_red_mushroom (0.40), pot_antidote (0.10), specialTraits: {"ignoreArmorRatio": 0.5}
13. mob_bandit_chief (humanoid, Главарь бандитов, isElite: true): hp: 24, dmg: 4..7 (slashing), def: 5, acc: 60, eva: 3, xp: 130, gold: 15..35, лут: wpn_sword_regular (0.10), food_bread (0.30)
14. mob_statue_guard (construct, Каменный страж): hp: 30, dmg: 4..6 (blunt), def: 7, acc: 55, eva: -5, xp: 150, gold: 0..0, лут: junk_stone (0.70)
15. mob_troll_hill (beast, Холмовой тролль, isBoss: true): hp: 26, dmg: 4..6 (blunt), def: 5, acc: 55, eva: 0, xp: 165, gold: 5..15, лут: mat_bone (0.80), specialTraits: {"regenHp": 1, "regenIntervalRounds": 2}
• Tier 4 (tier: 4):
16. mob_wraith (undead, Призрак): hp: 28, dmg: 5..8 (arcane), def: 3, acc: 68, eva: 12, xp: 200, gold: 10..25, affinities: как undead, но slashing: 0.5, piercing: 0.5, specialTraits: {"ignoreArmorRatio": 0.5}
17. mob_griffin_forest (beast, Лесной грифон): hp: 32, dmg: 5..8 (slashing), def: 4, acc: 66, eva: 10, xp: 210, gold: 0..5, лут: mat_bone (0.70)
18. mob_ogre (humanoid, Огр, isBoss: true): hp: 38, dmg: 6..9 (blunt), def: 6, acc: 62, eva: 0, xp: 230, gold: 10..30, лут: []
19. mob_flesh_amalgam (undead, Голод из плоти): hp: 40, dmg: 6..8 (blunt), def: 6, acc: 60, eva: -3, xp: 240, gold: 0..0, лут: []
20. mob_ataman (humanoid, Атаман «Косой», isElite: true): hp: 34, dmg: 5..8 (slashing), def: 7, acc: 65, eva: 5, xp: 260, gold: 40..70, лут: wpn_sword_fine (0.15)
• Tier 5 (tier: 5):
21. mob_wyvern (beast, Царь-гад): hp: 48, dmg: 7..11 (piercing), def: 7, acc: 72, eva: 9, xp: 230, gold: 20..50, лут: []
22. mob_knight_black (humanoid, Чёрный рыцарь): hp: 50, dmg: 7..10 (slashing), def: 9, acc: 72, eva: 3, xp: 280, gold: 60..100, лут: arm_plate_regular (0.10)
23. mob_lich_lesser (undead, Младший лич): hp: 45, dmg: 7..11 (arcane), def: 6, acc: 75, eva: 8, xp: 300, gold: 30..80, specialTraits: {"ignoreArmorRatio": 0.5}
24. mob_troll_ancient (beast, Древний тролль, isBoss: true): hp: 55, dmg: 8..12 (blunt), def: 8, acc: 70, eva: 0, xp: 330, gold: 20..60, specialTraits: {"regenHp": 2, "regenIntervalRounds": 1}

Б. data/biomes/<id>.json (category: "biome")

9 отдельных файлов (biome_village, biome_camp, biome_road, biome_meadow, biome_forest_edge, biome_ruins, biome_deep_forest, biome_swamp, biome_lair), где "biomeType" соответствует типам из §30 ("village", "camp", "road", "meadow", "forest_edge", "ruins", "deep_forest", "swamp", "lair"), а "id" = "biome_<biomeType>":
• Содержит: pSpawn (вероятность спавна), canSearch (bool), searchWeightShifts (сдвиги весов поиска из §30.1, например для road: {"junk": 10, "nothing": -10}, для meadow: {"food": 10, "nothing": -10}), preferredItems (опционально, например ["food_mushrooms"] для deep_forest, ["food_moss", "food_red_mushroom"] для swamp), monsterPool (список ID мобов из §30.1), services (для village и camp), namePool (adjectives и nouns для генератора названий §30.2).

В. data/npcs/<id>.json (category: "npc")

7 отдельных файлов по §31:
1. npc_elder_miroslav (Староста Мирон, locationType: "village"): actionWhitelist: ["give_hint", "none"]
2. npc_merchant_ganna (Торговка Ганна, locationType: "village"): actionWhitelist: ["open_trade", "none"], продаёт еду (food_berries, food_cabbage, food_bread, food_dried_fish, food_cured_fatback), базовые зелья (pot_heal_minor, pot_antidote, pot_mana_minor), скупает всё (buysAll: true).
3. npc_blacksmith_kolm (Кузнец Колм, locationType: "village"): actionWhitelist: ["open_trade", "none"], services: ["repair", "workbench"], продаёт оружие и броню (включая Тиры 1–3) и rep_smith_kit.
4. npc_innkeeper_boris (Трактирщик Борис, locationType: "village"): actionWhitelist: ["barter_offer", "give_hint", "none"], services: ["rest"], restCost: 5 (зафиксированный ночлег за 5 монет!), продаёт готовую еду (food_bread, food_boiled_potatoes, food_cured_fatback).
5. npc_herbalist_vela (Травница Вела, locationType: "village"): actionWhitelist: ["open_trade", "give_hint", "none"], services: ["campfire"], продаёт зелья (pot_heal_minor, pot_heal_regular, pot_heal_greater, pot_mana_minor, pot_mana_regular, pot_antidote) и рецепты алхимии.
6. npc_hunter_rask (Охотник Раск, locationType: "camp"): actionWhitelist: ["give_hint", "barter_offer", "none"], продаёт покрытия и расходники (oil_poison, oil_fire, elx_accuracy).
7. npc_wanderer_kit (Бродяга Кит, locationType: "camp"): actionWhitelist: ["barter_offer", "give_hint", "none"], продаёт случайные редкости (bmb_fire, elx_berserk, elx_ironskin, rep_whetstone, rep_patch_kit).
У каждого NPC заложены: id, category: "npc", role, locationType, name (en/ru), personality (ru), initialReputation: "neutral", actionWhitelist, services, tradeStock (список itemId), и словарь fallbackReplies по всем 6 значениям mood (neutral, friendly, sympathetic, irritated, hostile, fearful).

Г. data/strings_ru.json

Словарь русских строк для UI и системных событий (минимум базовый набор ключей: системные события загрузки/смерти/автосейва, статусы голода, заголовки экранов CLI, названия характеристик/навыков, сообщения боя/поиска/отдыха/ремонта).

5. Обновление engine/data_loader.py

• Добавить загрузку monsters, biomes, npcs (как отдельных JSON-файлов с проверкой file.stem == data["id"] и глобальной уникальности id), а также загрузку strings_ru.json в self.strings: dict[str, str].
• Добавить проверки ссылочной целостности при загрузке:
	1. Все lootTable[].itemId у монстров существуют в items.
	2. Все monsterPool[] в биомах существуют в monsters.
	3. Все tradeStock[] у NPC существуют в items.
• Добавить методы доступа: get_monster(id), get_biome(biome_type_or_id), get_npc(id), t(string_id: str, **kwargs) -> str (форматирование строки из strings_ru.json).

6. Критерии приёмки (tests/test_world_data.py)

1. scripts/build_static_data.py генерирует все 24 файла монстров, 9 биомов, 7 NPC и strings_ru.json (итого 84 + 40 = 124 сущности в подпапках data/).
2. GameData("data") проходит все проверки ссылочной целостности (ни одной битой ссылки на предметы или мобов).
3. У Бориса (npc_innkeeper_boris) зафиксирован restCost == 5 и услуга "rest".
4. Тест на битую ссылку в monsterPool биома или lootTable монстра вызывает ValueError.
