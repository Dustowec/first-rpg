# Известные проблемы (аудит кода)

Дата: 2026-11-26. Охват: `engine/`, `cli/app.py`, `tests/` — с учётом фикса
засады («бой-призрак», делегирование `exploration._start_combat` в
`engine/combat.py`, патч `fix-ambush-combat.patch`). Прогон тестов на момент
аудита: 591 passed, 2 skipped — ни один из пунктов ниже тестами не покрыт.

Метка «воспроизведено» = баг подтверждён запуском кода; «статически» = по
коду с указанием строк.

> ## Статус после работы по `agent_task.md` (ветка `fix/audit-20261126`)
>
> Все 12 пунктов закрыты. Базлайн 591 passed / 2 skipped → **619 passed, 2 skipped**.
> `python scripts/smoke_ambush.py` → `FIX VERIFIED`; сценарий Приложения Б (KI-3)
> проходит без TypeError; `git status` после полного прогона чистый
> (`state_template.json` больше не меняется).
>
> | # | Статус |
> |---|---|
> | KI-1 | FIXED (843fb5b) |
> | KI-2 | FIXED (0a2ed1b) |
> | KI-3 | FIXED (33982bf) |
> | KI-4 | FIXED (3862f4a) |
> | KI-5 | FIXED (4ef87b5) |
> | KI-6 | FIXED (561b876) |
> | KI-7 | FIXED (3862f4a) |
> | KI-8 | FIXED (dedda54) |
> | KI-9 | FIXED (dedda54) |
> | KI-10 | FIXED (80730ed) |
> | KI-11 | FIXED (43f5856) |
> | KI-12 | FIXED (3a27dd8) |
>
> Открытые вопросы к владельцу перечислены в разделе «Вопросы» в конце файла.


---

## Высокая серьёзность

### 1. `_end_round` никогда не вызывается — «замороженный» раунд (воспроизведено) — **FIXED (843fb5b)**
Где: `engine/combat.py:427` (определение), единственный вызов `tick_combat_round_effects`
— внутри него же (`combat.py:434`). Ни `combat_step`, ни `_handle_player_attack`
(`combat.py:701`), ни ветки провала побега (`combat.py:612`), ни cast/use_item
(`combat.py:296, 324`) `_end_round` не зовут.

Следствия:
- `world["activeCombat"]["round"]` навсегда 1 (проверено: 6 ходов — раунд 1).
- Кулдаун «Сокрушения» (`magic.py:884`, = 4) не уменьшается нигде, кроме
  `_end_round` → навык доступен **один раз за весь бой** (проверено:
  `err_skill_on_cooldown` после первого применения).
- Боевые DoT/баффы с `durationInRounds` не тикают и не истекают
  (`tick_combat_round_effects` — мёртвый код в бою): яд от `spl_venom_touch`,
  масло `oil_poison` и т.п. на монстре не работают.
- Реген монстров: `combat.py:361` — `round_num % regenIntervalRounds == 0`;
  при раунде 1: `mob_troll_hill` (интервал 2, `1 % 2 = 1`) не регенерирует
  никогда; `mob_troll_ancient` (интервал 1) — работает случайно.

Фикс-подсказка: в конце каждой ветки, доигравшей раунд, —
`_handle_player_attack` (после `events.extend(monster_events)`), провал побега
и ветки cast/use_item после `_execute_monster_turn` — вызвать
`state = _end_round(state, combat_mob)` и вернуть его. Заодно дать `_end_round`
возвращать события тиков (`state, _ = tick_combat_round_effects(...)` —
события сейчас выбрасываются).

### 2. Ходы монстра не порождают событий — вражеские атаки «молчат» — **FIXED (0a2ed1b)**
Где: `engine/combat.py:334-419` (`_execute_monster_turn`). В `events`
попадают только износ брони, onHitDot и second_wind; события
`monster_attack_hit` / `monster_attack_miss` не эмитятся. Строки
`battle_enemy_attack`, `battle_enemy_miss`, `battle_defeat`,
`battle_loot_found` в `data/strings_ru.json` не задействованы. Игрок видит
урон только по HP-бару в CLI.

Фикс-подсказка: добавить `{"id": "monster_attack_hit", "damage": ...}` /
`{"id": "monster_attack_miss"}` и ветки в `cli/app.py::event_text`
(русская строка уже есть).

### 3. Краш: смерть от голода при трате AP в `start_combat` (воспроизведено) — **FIXED (33982bf)**
Где: `engine/combat.py:115-127`. `world_time.advance_time` при гибели
возвращает `handle_player_death(...)` — то есть **свежее состояние новой
игры**, а не умершее; флаг `isDead` ставится на выброшенном состоянии, так что
проверка `state.get("flags", {}).get("isDead")` (`combat.py:117`) всегда False
(мёртвый код). Выполнение продолжается на свежем состоянии, где у `node_00`
`monster = None` → `current_node["state"]["monster"]["revealed"] = True`
(`combat.py:124`) → `TypeError: 'NoneType' object does not support item
assignment` (проверено запуском).

Дополнение: событие `player_died` из `advance_time` затирается
`events = [{"id": "combat_started", ...}]` (`combat.py:190`) — контроллер не
увидит смерть и сохранит неконсистентное состояние.

Фикс-подсказка: после `advance_time` проверять
`any(e.get("id") == "player_died" for e in events)` и возвращаться сразу.

### 4. Респавн монстров раз в 5 дней (§ 28.2) — полностью мёртв (статически) — **FIXED (3862f4a)**
Три независимых причины:
- `engine/world_time.py:134`: `node.get("biomeId", "")` — узлы, создаваемые
  `worldgen.generate_region`, ключа `biomeId` не содержат вообще → `continue`
  на каждом узле, респавн не срабатывает никогда.
- `engine/world_time.py:158`: `mob_def.get("stats", {}).get("hp", 10)` — у
  монстров HP лежит верхним уровнем (`"hp": 6`), так что база всегда 10 →
  неверный `maxHp` у респавна.
- `_on_new_day` вызывается только из `world_time.advance_time`
  (бой/крафт/таверна). Перемещение, поиск и ожидание гоняют второй, локальный
  `exploration.advance_time` (`engine/exploration.py:208`), который
  `daysSinceCleared` инкрементирует (`exploration.py:244-247`), но респавна в
  нём нет — зачистка узла «оживает» только если игрок тратит AP через
  combat/crafting/inn.

### 5. `create_initial_state` перезаписывает state_template.json в корне репо (воспроизведено) — **FIXED (4ef87b5)**
Где: `engine/models.py:98, 145-146` — без `template_path_override` функция
пишет файл по умолчанию `state_template.json`. Тесты зовут её без override:
`tests/test_combat.py:32`, `tests/test_storage.py:47` (и далее). После прогона
тестов эталонный шаблон в репо подменяется (проверено по git diff), причём
карта у `create_initial_state` — один узел-деревня **без выходов**
(`models.py`, `_create_village_node`) → если такой шаблон закоммитить, новая
игра стартует в тупиковом мире.

Фикс-подсказка: убрать побочный эффект записи из `create_initial_state`
(запись делать только в `scripts/generate_template.py`); в тестах всегда
передавать `template_path_override=tmp_path/...`.

---

## Средняя серьёзность

### 6. Перк «Чутьё кладоискателя» (scavenging >= 10) портит поиск (воспроизведено) — **FIXED (561b876)**
Где: `engine/exploration.py:657` — `all_items = game_data.get(chosen_cat, [])`
использует сырую категорию (`"junk"`, `"weapon"`), а бакеты dict-view
называются `"materials"`, `"weapons"` → список пуст → `candidates` пуст →
возврат `scavenge_nothing`: ролл потрачен впустую. Fallback тира
(`exploration.py:669`) с той же ошибкой — пуст для junk/weapon.
Фикс: везде `game_data.get(_CAT_MAP.get(chosen_cat, chosen_cat), [])`.

### 7. Две расходящиеся реализации `advance_time` (статически) — **FIXED (3862f4a)**
`engine/exploration.py:208` (move/look/search/wait) и
`engine/world_time.py:175` (combat/crafting/inn) — одна и та же механика
времени с разными правилами:
- смерть: exploration помечает `world.playerDead` и шлёт `player_death`;
  world_time сразу делает permadeath-сброс и возвращает свежее состояние;
- голод: exploration блокирует и HP-, и MP-реген в «голодных окнах»;
  world_time — только HP (`is_hungry_now`), MP восстанавливается всегда;
- события `effect_expired` эмитит только world_time;
- DoT-тик: `exploration.py:289` клампит HP только снизу
  (`max(0, ...)`, без `min(max)`) — положительный `hpDeltaPerTurn` может
  завысить HP выше максимума; world_time клампит оба конца.

Рекомендация: оставить одну реализацию (world_time) и переиспользовать её из
exploration — иначе правила «плывут» в зависимости от того, каким действием
потрачен AP.

---

## Низкая серьёзность / косметика

### 8. `look` / `search` / `wait` в бою — молчаливый no-op (статически) — **FIXED (dedda54)**
`engine/exploration.py:492, 571, 705` — `return st, []`: ни события, ни
`err_in_combat`; CLI просто ничего не показывает. Для сравнения, `move` шлёт
`err_in_combat` (`exploration.py:403`).

### 9. Смещение шанса засады (статически) — **FIXED (dedda54)**
`engine/exploration.py:464` — `rng.randint(0, 100) <= ambush_chance`:
101 исход, реальный шанс `(c+1)/101` (при 15 заявленных — 15,8%).

### 10. Еда не блокируется в бою (статически) — **FIXED (80730ed)**
`engine/controller.py:99` — команда `eat` в бою проходит в
`world_time.eat_food` без проверки `inCombat`: бесплатный отхил HP прямо в
бою. Возможно осознанный дизайн, но в спецификацию боя не вписывается.

### 11. Неиспользуемые строки локализации (косметика) — **FIXED (43f5856)**
`battle_start`, `battle_defeat`, `battle_loot_found` и др. в
`data/strings_ru.json` не соответствуют ни одному событию движка — следствие
п.2 и несоответствия имён событий заглушек/движка (`combat_start` vs
`combat_started` — последняя добавлена фиксом засады).

### 12. LLM включён в шаблоне по умолчанию (инфо) — **FIXED (3a27dd8)**
`state_template.json`: `llm.enabled: true`, endpoint `127.0.0.1:8080`,
таймаут 15 с. Fallback на офлайн-реплики есть, но каждый диалог к
недоступному эндпоинту ждёт таймаут. Для «из коробки» разумнее `false`.

---

## Контекст: что уже починено

«Бой-призрак» при засаде (заглушка `_start_combat` в
`engine/exploration.py`: флаг `inCombat` без `activeCombat`) — исправлен
делегированием в реальный `engine/combat.py::start_combat` + адаптер
`_CombatGameDataView` (dict-view exploration ↔ GameData-объект combat).
Прогон: 591 passed, 2 skipped. Патч: `fix-ambush-combat.patch` (файл приложен
отдельно).

## Методика

Статический разбор `engine/` и `cli/app.py` + четыре воспроизводимых
эксперимента: (1) раунд/кулдаун замирают после 6 ходов; (2) TypeError при
гибели от голода в `start_combat` (шаг 6 → дедлайн 7, `fedMorning=False`);
(3) перк «Чутьё кладоискателя» съедает поиск на дороге; (4) `git diff`
после прогона отдельных тест-файлов — `state_template.json` меняется от
`tests/test_combat.py` и `tests/test_storage.py`.



## Вопросы (требуют решения владельца)

1. **KI-10 — еда в бою.** Сделана блокировка (`err_in_combat`), как предписано ТЗ
   («безопаснее для баланса»). Если это был осознанный дизайн (еда как боевое
   действие) — вернуть ветку и описать её в спеке §7.
2. **KI-7 — голод и MP.** Реген MP теперь тоже блокируется в голодных окнах
   (раньше `world_time` восстанавливал MP всегда). Решение выровняло две
   реализации, но меняет баланс. Если MP-реген должен идти и при голоде — снять
   `and not hungry` у регена MP в `engine/world_time.py` и обновить
   `test_mp_regen_blocked_in_hunger_window`.
3. **KI-1 — реген тролля.** Реген считается по «прожитым» раундам: при засаде
   (монстр ходит первым) его первый ход — это прожитый раунд 1, поэтому
   `mob_troll_hill` (интервал 2) регенерирует на 2-м и 4-м своём ходе. Если
   реген должен привязываться только к отображаемому номеру раунда — убрать
   поправку `isAmbush` в `_execute_monster_turn`.
4. **KI-4 — кто считается «зачищенным».** Тикает только узел с
   `spawnRolled=True` и `monster=None`; в нетронутых узлах счётчик остаётся
   `None`. Если респавн нужен и там — снять условие `spawnRolled is True`.
5. **KI-5.** `create_initial_state` не пишет файл без явного
   `template_path_override` (запись по override оставлена для совместимости
   тестов). Эталон новой игры пишет только `scripts/generate_template.py`
   (там карта полноценная, а не один узел).
