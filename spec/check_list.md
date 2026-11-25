Мы разрабатываем текстовый survival-RPG прототип на Python 3.11+ (без print/input в ядре `engine/`, чистые функции `state + command -> (new_state, events)` под будущий порт на Godot). Я работаю в GigaCode IDE, куда скармливаю атомарные ТЗ по блокам.

### Зафиксированные ответы на §35 спеки (Канон):
1. Респавн монстров: раз в 5 игровых дней в зачищенных диких локациях респавнится 1 обычный монстр (`daysSinceCleared >= 5`).
2. Ночлег у трактирщика Бориса: 5 золота — перематывает время до следующего утра (`stepOfDay = 1, day += 1`), закрывает ужин, тикает реген.
3. Сложность: в `meta` сейва заложен `difficultyMultiplier` (`easy: 0.75`, `normal: 1.0`, `hard: 1.4`, `impossible: 2.0`), масштабирует HP и урон монстров.
4. Смерть (Permadeath): полный сброс `state_session.json` и старт новой игры из `state_template.json`.

### Уже реализовано и покрыто тестами (Фазы 1–3):
- [x] **1.1.** `engine/constants.py`, `engine/models.py`, `engine/storage.py`, `state_template.json` — контракты `state` (`schemaVersion = 1`), валидатор, атомарный сейв через `os.replace`, `handle_player_death()`.
- [x] **1.2–1.3.** `scripts/build_static_data.py`, `engine/data_loader.py` (`GameData`) — принцип «1 сущность = 1 JSON-файл» в папках `data/{weapons,armor,food,materials,consumables,repair_kits,recipes,spells,skills,monsters,biomes,npcs}` + `data/strings_ru.json`. Унифицирован `stats.damage.type`, добавлено оружие Тира 3–4.
- [x] **2.1.** `engine/progression.py` — `calc_max_hp`, `calc_max_mp`, `xp_to_next_level`, `allocate_attribute` (лимит +2 на старте), `allocate_skill`, `grant_xp`, геттеры вех (`has_lunge`, `has_armor_sunder`, `has_tight_belt` и др.).
- [x] **2.2.** `engine/inventory.py` — `add_item`, `remove_item`, `equip_item`, `unequip_item`, `get_effective_weapon_stats`, `get_effective_armor_stats` (штрафы `<30%` и `0`), `register_weapon_hit`, `register_armor_hit`, `repair_at_smith`, `repair_with_kit`.
- [x] **2.3.** `engine/world_time.py` — `advance_time` (шаги 1..20, дедлайны голода 7/17 или 9/19), `eat_food`, `rest_at_inn` (5 монет), тик `activeEffects` и естественного регена HP/MP, респавн 1 монстра раз в 5 дней.
- [x] **3.1–3.4.** `engine/combat_math.py`, `engine/consumables.py`, `engine/magic.py`, `engine/combat.py` — полный боевой автомат (`start_combat`, `combat_step`), засады, инициатива, криты, покрытия (`oil_fire`, `oil_poison`), эликсиры/бомбы, 9 заклинаний (игнор 50% брони), боевые перки, побег (50% без выброса из локации), очередь логова (`lairQueue`) и раздача лута.

### Оставшийся план декомпозиции (Фазы 4–5):
- [ ] **4.1.** Процедурный генератор графа региона (`engine/worldgen.py`): 25 узлов по слоям `depth 0..6`, степени 2..4, плотность спавна `0.20..0.50`, уникальные названия биомов, генерация `state_template.json` (seed `20260101`) и переход в «Дальние тропы» (`region + 1`).
- [ ] **4.2.** Перемещение, стелс («Осмотреться»), засады и «Поиск» (`engine/exploration.py`): переход между узлами за 1 AP, проверка засады (`max(5, 15 - scavenging)`), осмотр за 1 AP, «Поиск» с истощением локации (`searchMax = 3 + danger`) и сдвигами весов по биому.
- [ ] **4.3.** Ремесло: Алхимия и Кузнечное дело (`engine/crafting.py`): проверка станков (деревня/лагерь/поле), порога навыка, крафт за 1 AP с перком «Экономный алхимик» (25% сохранения) и полевая заточка (`crafting 3`).
- [ ] **4.4.** Сервисы деревни, торговля и репутация NPC (`engine/trade.py`): покупка/продажа у NPC с учётом `reputation` (`honored` +5% к продаже, `hated/hostile` блок).
- [ ] **5.1.** Сборщик State Snapshot и клиент локальной LLM (`engine/llm_client.py`): слепок ~200 токенов, OpenAI-совместимый API (`json_schema`, без `<think>`), таймаут 15 сек, фоллбэк.
- [ ] **5.2.** Валидатор и исполнитель действий NPC (`engine/dialogue.py`): фильтрация `action.type` по белому списку, `barter_offer`, `discount_10`, `give_hint`, сдвиг репутации.
- [ ] **5.3.** Главный контроллер и CLI-интерфейс (`cli/app.py`, `main.py`): диспетчер команд с автосейвом после каждого мирового действия, рендер экранов в 1 кнопку (маскировка `hidden: true`) и интеграционные тесты.

Выдай подробное, самодостаточное ТЗ для GigaCode по следующему пункту (начинаем с **4.1**).
