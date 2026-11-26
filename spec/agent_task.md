# ТЗ — агент по починке проекта first-rpg

**Файл:** agent_tasck.md · **Версия:** 1.0 · **Дата:** 2026-11-26
**Исполнитель:** автономный агент по коду (Claude Code / Cursor / aider / человек), работающий в локальном клоне репозитория на машине владельца.
**Основа:** аудит кода `known_issues.md` (12 проблем) + готовый фикс «боя-призрака» при засаде.

> ТЗ самодостаточно: весь нужный код, команды и критерии — ниже. Ссылки на номера
> строк даны на момент аудита (HEAD = 031354d «fixed dialogs»); если строки
> сместились — ищи по именам функций и фрагментам кода.

---

## 1. Контекст проекта

| Параметр | Значение |
|---|---|
| Репозиторий | https://github.com/Dustowec/first-rpg (текстовая RPG, «LLM Game v2.0») |
| Язык | Python 3.10+, без фреймворков |
| Архитектура | чистые функции `state + command -> new_state + events`; состояние — plain dict |
| Ключевые каталоги | `engine/` (логика), `cli/app.py` (CLI), `data/` (JSON-данные), `tests/` (pytest) |
| Запуск игры | `python main.py` |
| Тесты | `python -m pytest -q` из корня репо |
| Спецификация баланса | `spec/spec_v3.md` |

Инварианты, которые нельзя нарушать:

- Состояние — plain dict с ключами `meta`, `player`, `world`, `map`, `npcs`, `flags`.
  Бой живёт в `world["activeCombat"]`, флаг боя — `world["inCombat"]`.
- Функции ядра чистые: не мутировать входной `state` (deepcopy перед изменением).
- События — `list[dict]` с полем `id`. Тексты — в `data/strings_ru.json`.
  Внимание: id события и ключ строки — не одно и то же (например, событие
  `attack_hit` рендерится через строку `battle_attack_hit`; см. `cli/app.py::event_text`).
- Против кольцевых импортов — локальный импорт внутри функции
  (прецедент: `exploration._start_combat` делает `from engine import combat`).
- Базлайн тестов на момент аудита: **591 passed, 2 skipped**. Правки не должны
  ломать существующие тесты — только добавлять новые.
- Данные (`data/*.json`) — источник баланса; значения не выдумывать, сверять со
  спекой и существующими файлами.

## 2. Правила работы (обязательны)

1. Работать в отдельной ветке: `git checkout -b fix/audit-20261126`.
2. Одна задача — один атомарный коммит. Формат сообщений: `fix(ki-N): суть`
   (фикс засады — `fix(ambush): ...`, косметика данных — `chore(data): ...`).
3. После каждой задачи — полный прогон `python -m pytest -q`. Красные тесты не
   коммитить. Если фикс требует обновить старый тест — обновлять в том же коммите.
4. К каждой задаче добавить регрессионный pytest-тест. Задача без теста не
   считается выполненной (исключения помечены явно).
5. `state_template.json` в корне репо — эталон новой игры. До решения задачи KI-5
   любой прогон тестов может его изменять: эти изменения НЕ коммитить,
   восстанавливать `git checkout -- state_template.json`. После KI-5 churn
   должен исчезнуть — это часть приёмки.
6. Если задача не воспроизводится на текущем коде или требует дизайн-решения —
   не бросать молча: записать в `known_issues.md` (раздел «Вопросы») и идти дальше.
7. Язык коммитов и комментариев — русский; идентификаторы и код — как в
   существующем стиле (англ., snake_case).
8. В конце работы — обновить `known_issues.md`: у исправленных пунктов поставить
   пометку `FIXED (<коммит>)`, у пропущенных — статус и причину.

## 3. Карта работ (порядок обязателен)

| # | Задача | Приоритет | Объём |
|---|---|---|---|
| 0 | Этап 0: подготовка, базлайн | — | S |
| 1 | Фикс засады «бой-призрак» (если не применён) | критично | M |
| 2 | KI-5: side-effect записи шаблона | высокий | M |
| 3 | KI-3: краш при смерти от голода в `start_combat` | высокий | S |
| 4 | KI-1: `_end_round` никогда не вызывается | высокий | M |
| 5 | KI-2: ходы монстра без событий | высокий | S |
| 6 | KI-6: перк «Чутьё кладоискателя» ломает поиск | средний | S |
| 7 | KI-8: `look`/`search`/`wait` в бою — молчаливый no-op | низкий | S |
| 8 | KI-9: смещение шанса засады | низкий | S |
| 9 | KI-4: респавн монстров не работает | средний | M |
| 10 | KI-7: две расходящиеся `advance_time` | средний | L |
| 11 | KI-10: еда в бою | низкий | S |
| 12 | KI-11: мёртвые строки локализации | низкий | S |
| 13 | KI-12: `llm.enabled=true` в шаблоне | низкий | S |
| 14 | Этап 3: финальная верификация и отчёт | — | S |

Обоснование порядка: сначала чистота репо (KI-5), затем краш (KI-3), затем ядро
боя (KI-1, KI-2), мелкие фиксы, затем связанная пара KI-4 + KI-7 (время/респавн),
в конце — дизайн-решение и косметика.

## 4. Этап 0 — подготовка

```bash
cd <корень репо>
git checkout -b fix/audit-20261126
python -m pytest -q                     # записать результат — базлайн
git checkout -- state_template.json 2>/dev/null || true
grep -n "_CombatGameDataView" engine/exploration.py \
  && echo "ФИКС ЗАСАДЫ УЖЕ ПРИМЕНЁН" \
  || echo "ФИКС ЗАСАДЫ НЕ ПРИМЕНЁН"
```

Если `grep` нашёл `_CombatGameDataView` — задание 1 уже в коде; проверь только
контрольные точки:

- в `engine/inventory.py` четыре замены `player["equipment"].get(...)`
  на `player.get("equipment", {}).get(...)`;
- в `data/strings_ru.json` есть ключи `combat_started`, `combat_fled_success`,
  `combat_fled_failed`;
- в `tests/test_exploration.py::test_ambush_triggers_combat` ожидается событие
  `combat_started` и стоит `assert new_st["world"]["activeCombat"] is not None`.

Всё на месте — сразу переходи к KI-5 (раздел 6).

## 5. Задание 1 — «Бой-призрак» при засаде (только если фикса нет)

**Симптом.** При засаде (`move` → `ambush_triggered`) заглушка `_start_combat` в
`engine/exploration.py` ставила `world["inCombat"] = True`, но не создавала
`world["activeCombat"]`. Игрок навсегда застревал: атака → `err_not_in_combat`,
уход из локации → `err_in_combat`, [4] Отступить → `err_not_in_combat`.

**Причина.** Заглушка не вызывала реальный движок `engine/combat.py::start_combat`
+ несовпадение форматов: exploration работает с плоским dict-view данных,
а combat ждёт объект `GameData` (`get_monster()/get_item()/get_biome()/…`).

Если рядом с репо лежит `fix-ambush-combat.patch` — можно `git apply`
и пропустить до проверки. Ниже те же правки в виде кода (4 файла).

### 5.1. `engine/exploration.py`

Заглушку `_start_combat` (блок с комментарием «start_combat (заглушка…)»,
~строки 306–339) заменить на адаптер + делегирование:

```python
class _CombatGameDataView:
    """Адаптер плоского dict-view (бакеты monsters/armor/weapons/...) под
    интерфейс GameData, которого ждёт engine.combat (get_monster/get_item/...).
    exploration работает с dict-view, а боевка — с GameData-объектом."""

    def __init__(self, view: dict) -> None:
        self._view = view or {}

    def get_monster(self, monster_id: str) -> dict:
        m = _find_monster(self._view, monster_id)
        if m is None:
            raise KeyError(f"Монстр не найден: '{monster_id}'")
        return m

    def get_item(self, item_id: str) -> dict:
        it = _find_item(self._view, item_id)
        if it is None:
            raise KeyError(f"Предмет не найден: '{item_id}'")
        return it

    def get_biome(self, biome_id_or_type: str) -> dict:
        for b in self._view.get("biomes", []):
            if b.get("id") == biome_id_or_type or b.get("biomeType") == biome_id_or_type:
                return b
        raise KeyError(f"Биом не найден: '{biome_id_or_type}'")

    def get_spell(self, spell_id: str) -> dict:
        for s in self._view.get("spells", []):
            if s.get("id") == spell_id:
                return s
        raise KeyError(f"Заклинание не найдено: '{spell_id}'")

    def get_skill(self, skill_id: str) -> dict:
        for s in self._view.get("skills", []):
            if s.get("id") == skill_id:
                return s
        raise KeyError(f"Навык не найден: '{skill_id}'")


def _start_combat(state: dict, game_data: dict | None, is_ambush: bool = False,
                  rng: random.Random | None = None,
                  session_path: str = DEFAULT_SESSION_PATH,
                  template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]:
    """
    Запускает бой через реальный движок engine/combat.py.

    combat.start_combat создаёт world["activeCombat"] (без него CLI-команды
    combat_attack/combat_retreat упираются в err_not_in_combat), масштабирует
    монстра по difficultyMultiplier и при is_ambush сразу делает ход монстра.
    Событие старта — "combat_started" (id реального движка, не "combat_start").
    """
    # Локальный импорт — как с world_time выше: без кольцевых импортов engine.
    from engine import combat

    if game_data is None:
        game_data = _load_game_data()

    # exploration кормит нас плоским dict-view, а combat ждёт GameData-объект.
    if not hasattr(game_data, "get_monster"):
        game_data = _CombatGameDataView(game_data)

    if rng is None:
        rng = random.Random()

    return combat.start_combat(
        state, game_data, is_ambush=is_ambush, rng=rng,
        session_path=session_path, template_path=template_path,
    )
```

В шапке `exploration.py` уже есть `import copy`, `import random` и константы
`DEFAULT_SESSION_PATH` / `DEFAULT_TEMPLATE_PATH`; если чего-то нет — добавить.
`_find_monster` / `_find_item` уже определены в модуле — не дублировать.

### 5.2. `engine/inventory.py`

Четыре места, где экипировка берётся напрямую, укрепить (состояния без
`equipment` падали бы `KeyError` при ударе монстра):

- `get_effective_weapon_stats`: `player["equipment"].get("weapon")`
  → `player.get("equipment", {}).get("weapon")`
- `get_effective_armor_stats`: то же для `"armor"`
- `register_weapon_hit`: то же для `"weapon"`
- `register_armor_hit`: то же для `"armor"`

### 5.3. `data/strings_ru.json`

Добавить три ключа (в конец словаря, не забыть запятую у предыдущего):

```json
  "combat_started": "Бой начинается!",
  "combat_fled_success": "Вы отступили.",
  "combat_fled_failed": "Отступить не вышло — противник бьёт!"
```

### 5.4. `tests/test_exploration.py`

В `test_ambush_triggers_combat` (класс `TestAmbush`):

```python
combat_events = [e for e in events if e["id"] == "combat_started"]   # было "combat_start"
assert len(combat_events) > 0
assert combat_events[0]["isAmbush"] is True
assert new_st["world"]["activeCombat"] is not None                   # новая строка
```

**Проверка задания 1.** Сохранить Приложение А как `scripts/smoke_ambush.py`
в репо и запустить `python scripts/smoke_ambush.py`. Успех — строка
`FIX VERIFIED` в конце вывода. После запуска проверить `git status` — возможные
артефакты (`state_session.json`) удалить.

**Коммит:** `fix(ambush): запуск реального боя при засаде через engine.combat (адаптер dict-view -> GameData)`.

## 6. Задания аудита

Формат карточки: Симптом → Причина → Что сделать → Регресс-тест → Готово когда.

### KI-5. `create_initial_state` портит state_template.json — высокий, объём M

**Симптом.** После любого прогона pytest эталон `state_template.json` в корне
репо меняется (видно в `git diff`). Хуже: карта в записанном состоянии — один
узел-деревня **без выходов**; если такой шаблон закоммитить, новая игра
стартует в тупиковом мире.

**Причина.** `engine/models.py::create_initial_state` (~строки 98, 144–146):
без `template_path_override` функция пишет файл в `DEFAULT_TEMPLATE_PATH`
(корень репо). Тесты зовут её без override (`tests/test_combat.py:32`,
`tests/test_storage.py:47` и другие — найти все по grep `create_initial_state(`).

**Что сделать.**
1. Убрать из `create_initial_state` запись файла (блок `with open(target_path, "w") ...`)
   — функция должна только собирать и возвращать состояние. Писателем шаблона
   остаётся `scripts/generate_template.py` (уже есть в репо).
2. Аргумент `template_path_override` либо удалить, либо оставить как
   «путь для чтения», но запись — только у скрипта. Не ломать вызывающие тесты:
   где тесты читали записанный файл — передавать override с путём в `tmp_path`.
3. Прогнать grep по всем вызовам и убедиться, что ничего не потеряло шаблон.

**Регресс-тест.** Хэш/содержимое `state_template.json` не меняется после
`pytest tests/test_combat.py tests/test_storage.py` (или изнутри теста: файл до /
файл после `create_initial_state`).

**Готово когда.** Полный `python -m pytest -q` не меняет `git status` по
шаблону.

### KI-3. Краш при смерти от голода в `start_combat` — высокий, объём S

**Симптом.** `TypeError: 'NoneType' object does not support item assignment`
при старте обычного (не засадного) боя, если игрок умирает от голода при трате
AP. Воспроизведено на: `stepOfDay=6`, `fedMorning=False` (дедлайн еды — шаг 7).

**Причина.** `engine/combat.py:115-124`: `world_time.advance_time` при гибели
возвращает свежее состояние (результат `handle_player_death` — перма-сброс), у
которого в `node_00` нет монстра. Проверка `state.get("flags", {}).get("isDead")`
(строка 117) всегда False (флаг ставится на выброшенном состоянии — мёртвый
код). Выполнение продолжается и делает
`current_node["state"]["monster"]["revealed"] = True` → TypeError.
Дополнительно событие `player_died` затирается на ~строке 190
(`events = [{"id": "combat_started", ...}]`) — контроллер не увидит смерть.

**Что сделать.** После `advance_time(...)` проверять события и выходить сразу:

```python
if any(e.get("id") == "player_died" for e in events):
    return state, events
```

(вместо/в дополнение к мёртвой проверке `isDead`). Затем проверить остальные
места, где `advance_time` вызывается внутри боевых веток (`flee`, `cast`,
`use_item`), — та же проблема возможна и там.

**Регресс-тест.** State как в Приложении А, но `fedMorning=False`,
`stepOfDay=6`, монстр `revealed=True` в **текущем** узле (`currentNodeId`
указывает на него); `start_combat(..., is_ambush=False)`.
Ожидание: нет исключения; в `events` есть `player_died`; `world["inCombat"]`
не ставится.

**Готово когда.** Тест зелёный; сценарий из Приложения Б проходит.

### KI-1. `_end_round` никогда не вызывается — высокий, объём M

**Симптом (воспроизведено).** Раунды «заморожены»: `activeCombat["round"]`
всегда 1 (6 ходов подряд). Кулдаун «Сокрушения» (`engine/magic.py:884`,
значение 4) не уменьшается — навык доступен один раз за весь бой. Боевые
DoT/баффы с `durationInRounds` не тикают и не истекают (яд `spl_venom_touch`,
масло `oil_poison` на монстре не работают). Реген монстров
(`combat.py:361`, `round_num % regenIntervalRounds == 0`) не работает:
`mob_troll_hill` (интервал 2) не регенерирует никогда, `mob_troll_ancient`
(интервал 1) — «случайно».

**Причина.** `_end_round` (`engine/combat.py:427`) определён, но его никто не
вызывает; единственный вызов `tick_combat_round_effects` — внутри него же.
Внутри `_end_round` события тиков выбрасываются (`state, _ = ...`, строка 434).

**Что сделать.**
1. Завершать раунд во всех ветках, доигравших раунд: `_handle_player_attack`
   (после хода монстра, ~строка 701), провал побега (~строка 612), `cast`
   и `use_item` (~строки 296, 324): `state, ev = _end_round(state, combat_mob)`
   и добавить `ev` в `events`.
2. Сменить сигнатуру `_end_round` на `-> tuple[dict, list[dict]]`: возвращать
   события `tick_combat_round_effects` (иначе игрок не видит тики).
3. Убедиться, что `activeCombat["round"]` инкрементируется именно в `_end_round`
   (и только там).
4. Смерть монстра от DoT (`combat.py:441`) — обрабатывать как обычную победу
   (лут/XP/`combat_victory`), а не «в следующем шаге».
5. При завершении боя (победа/поражение/побег) снимать боевые эффекты, чтобы
   тики не утекали в мир.

**Инварианты для теста.** N завершённых раундов → `round` увеличился на N;
кулдаун уменьшается на 1 за раунд и возвращается к 0; DoT наносит урон раз в
раунд; при победе боевые эффекты сняты; реген тролля срабатывает на каждом
чётном раунде.

**Готово когда.** Тесты на инварианты зелёные; в живой игре кулдаун «Сокрушения»
перезаряжается за 4 раунда, DoT тикает, реген тролля работает.

### KI-2. Ходы монстра «молчат» — высокий, объём S

**Симптом.** Ходы монстра не порождают событий: урон игрок видит только по
HP-бару. Строки `battle_enemy_attack` / `battle_enemy_miss` в
`data/strings_ru.json` не задействованы.

**Причина.** `_execute_monster_turn` (`engine/combat.py:334-419`) эмитит только
износ бруни, onHitDot и second_wind; `monster_attack_hit`/`monster_attack_miss`
не существует.

**Что сделать.**
1. В `_execute_monster_turn` при попадании монстра добавлять событие
   `{"id": "battle_enemy_attack", "enemy": <имя монстра>, "damage": N}`, при
   промахе — `{"id": "battle_enemy_miss", "enemy": <имя>}` (формат полей — по
   образцу `attack_hit`; строка-плейсхолдеры: `"{enemy} атакует вас и наносит
   {damage} урона."`).
2. В `cli/app.py::event_text` добавить две ветки рендера по образцу
   `attack_hit` (строки 141-145).

**Регресс-тест.** После хода монстра в `events` есть `battle_enemy_attack`
(или `battle_enemy_miss`) с полями `enemy`/`damage`.

**Готово когда.** В CLI-игре видно «<Монстр> атакует вас и наносит N урона.».

### KI-6. Перк «Чутьё кладоискателя» ломает поиск — средний, объём S

**Симптом.** При `scavenging >= 10` перк (§22.3) обязан с шансом 2% добавлять
редкие предметы, но его срабатывание возвращает `scavenge_nothing` — ролл
потрачен впустую.

**Причина.** `engine/exploration.py:657` — `all_items = game_data.get(chosen_cat, [])`:
сырая категория (`"junk"`, `"weapon"`) вместо ключа бакета (`"materials"`,
`"weapons"`). Маппинг `_CAT_MAP` есть на строке 648, но в этой ветке не
используется. Fallback тира (строка 669) — та же ошибка.

**Что сделать.** В обоих местах (657 и 669) заменить на
`game_data.get(_CAT_MAP.get(chosen_cat, chosen_cat), [])`.

**Регресс-тест.** 1) `scavenging=10`, RNG с монотонной последовательностью
(чтобы «выпал» 2%-й шанс) — найден предмет, а не `scavenge_nothing`;
2) категория `weapon` при `danger=0` (запасной вариант) — кандидаты не пустые.

**Готово когда.** Оба теста зелёные.

### KI-8. `look`/`search`/`wait` в бою — молчаливый no-op — низкий, объём S

**Симптом.** В бою `look` (~строка 492), `search` (~571) и `wait` (~705)
возвращают `st, []` — ни события, ни ошибки; в CLI ничего не происходит.
Для сравнения: `move` шлёт `err_in_combat` (~строка 403).

**Что сделать.** В этих трёх функциях при `world["inCombat"]` вернуть событие
`err_in_combat` (id тот же, что у `move`; строка в `strings_ru.json` есть).

**Регресс-тест.** В бою `look`/`search`/`wait` → в `events` ровно
`err_in_combat`, состояние не меняется.

### KI-9. Смещение шанса засады — низкий, объём S

**Симптом.** `engine/exploration.py:464`: `rng.randint(0, 100) <= ambush_chance`
— 101 исход, реальный шанс `(c+1)/101` (заявленные 15% → 15,8%).

**Что сделать.** Заменить на `rng.randint(1, 100) <= ambush_chance`
(или `rng.random() * 100 < ambush_chance`). Прогнать
`test_high_scavenging_reduces_ambush` — инвариант «при scavenging=10 шанс <= 5%»
должен выполняться; если тест упал — согласовать формулу с ассертом теста
(ассерт менять нельзя, формулу — нужно).

**Готово когда.** Существующий тест зелёный, формула даёт ровно заявленный шанс.

### KI-4. Респавн монстров не работает — средний, объём M

**Симптом.** Респавн монстров (по спеке §28.2 — медленный, раз в несколько
дней) полностью мёртв. Три независимые причины:

1. `engine/world_time.py:134` — `node.get("biomeId", "")`: узлы, создаваемые
   `worldgen.generate_region`, ключа `biomeId` не содержат — у них тип биома в
   ключе `"type"` (`engine/worldgen.py:313`, `nd["type"] = biome_type`) → `continue`
   на каждом узле, респавн не срабатывает никогда.
2. `engine/world_time.py:158` — `mob_def.get("stats", {}).get("hp", 10)`: HP у
   монстров лежит верхним уровнем (`"hp": 6` в `data/monsters/*.json`) → база
   всегда 10 → неверный `maxHp` у респавна.
3. `_on_new_day` вызывается только из `world_time.advance_time` (бой/крафт/
   таверна). Exploration-действия (move/search/wait) гоняют второй, локальный
   `exploration.advance_time` (`exploration.py:208`), который
   `daysSinceCleared` инкрементирует (`exploration.py:244-247`), но респавна не
   делает — узел «оживает» только если AP потрачен через combat/crafting/inn.

**Что сделать.**
1. В `world_time` брать тип биома из реального ключа: `node.get("type", "")`.
2. Базовое HP монстра — верхним уровнем: `mob_def.get("hp", 10)`.
3. Респавн обязан срабатывать независимо от того, каким действием потрачен AP.
   Проще всего после KI-7 (единая `advance_time`); если KI-7 не делается —
   вызвать `_on_new_day` (или вынесенную общую функцию респавна) и из
   `exploration.advance_time` при смене дня.

**Регресс-тест.** Узел: `daysSinceCleared >= порога` (см. код `_on_new_day`),
`monster = None` → после смены дня в узле есть монстр; `maxHp` совпадает с
`data/monsters/<id>.json`.

**Готово когда.** Тест зелёный; респавн работает при любом способе смены дня.

### KI-7. Две расходящиеся `advance_time` — средний, объём L

**Симптом.** `exploration.advance_time` (`engine/exploration.py:208`, действия
move/look/search/wait) и `world_time.advance_time` (`engine/world_time.py:175`,
combat/crafting/inn) — одна механика с разными правилами:
- смерть: exploration помечает `world.playerDead` и шлёт `player_death`;
  world_time сразу делает перма-сброс и возвращает свежее состояние;
- голод: exploration блокирует и HP-, и MP-реген в «голодных окнах»; world_time —
  только HP, MP восстанавливается всегда;
- `effect_expired` эмитит только world_time;
- DoT-тик `exploration.py:289` клампит HP только снизу (`max(0, ...)`) —
  положительный `hpDeltaPerTurn` может завысить HP выше максимума; world_time
  клампит оба конца.

**Что сделать (два допустимых варианта).**
- **Полный (рекомендуется):** единая точка истины — `world_time.advance_time`;
  exploration-версия удаляется и делегирует (мёртвый state/`player_death`
  приводится к общему формату; `cli/app.py` уже обрабатывает `player_died`).
- **Минимальный (если полный рефакторинг кажется рискованным):** выровнять
  правила exploration-версии под world_time: MP-реген блокируется в голодных
  окнах; DoT клампит HP с обеих сторон (`min(max_hp, max(0, ...))`); события
  `effect_expired` эмитятся так же; поведение смерти — одинаковое в обеих.

**Регресс-тест.** Одинаковое состояние + одинаковый вход → одинаковые
HP/MP/события у обеих функций (пары инвариантов на каждый пункт расхождений).

**Готово когда.** Парность зелёная или осталась одна реализация.

### KI-10. Еда в бою — низкий, объём S (дизайн-решение)

**Симптом.** `engine/controller.py:99` — команда `eat` в бою проходит в
`world_time.eat_food` без проверки `inCombat`: бесплатный отхил HP прямо в бою.

**Что сделать.** По умолчанию блокировать: в eat-ветке контроллера проверка
`world.get("inCombat")` → событие `err_in_combat` (строка уже есть). Если
считаешь это осознанным дизайном — пометить в `known_issues.md` как вопрос
владельца и всё равно сделать блокировку (безопаснее для баланса: еда не
сочетается с механикой AP/боя по спеке §7).

**Регресс-тест.** В бою `eat` → `err_in_combat`, HP не изменился.

### KI-11. Мёртвые строки локализации — низкий, объём S

**Симптом.** `battle_start`, `battle_defeat`, `battle_loot_found` и др. в
`data/strings_ru.json` не соответствуют ни одному событию (следствие KI-2 и
расхождения id заглушек и движка: `combat_start` vs `combat_started`).

**Что сделать.** ПОСЛЕ KI-2: собрать список реально эмитимых id (grep по
`engine/` и `cli/`), вычесть ключи, используемые напрямую и через
`event_text` → неиспользуемые либо удалить, либо задействовать
(`battle_defeat` — кандидат на экран смерти, `battle_loot_found` — на лут
после победы). Минимум: удалить явно мёртвый `battle_start` (дубль
`combat_started`).

**Готово когда.** В `strings_ru.json` нет ключей, на которые нет ни события, ни
ветки `event_text`, ни прямого вызова `t()`.

### KI-12. LLM включён в шаблоне по умолчанию — низкий, объём S

**Что сделать.** В `state_template.json` (корень репо) `meta.llm.enabled`
`true` → `false`: эндпоинт `127.0.0.1:8080` недоступен «из коробки», а каждый
диалог ждёт таймаут 15 с. Это осознанное изменение данных — закоммитить
`chore(data): llm off by default`. Сверить с `scripts/generate_template.py`
(если он генерирует шаблон с `enabled: true` — поправить и его). Проверить,
что `tests/test_static_data.py` не ассертит `enabled=true`. README уже
упоминает опциональность LLM — трогать не обязательно.

**Готово когда.** Новая игра стартует без обращений к эндпоинту.

## 7. Этап 3 — финальная верификация и отчёт

1. `python -m pytest -q` — все тесты зелёные (базлайн + новые).
2. `python scripts/smoke_ambush.py` — заканчивается `FIX VERIFIED`.
3. Сценарий Приложения Б (KI-3) — проходит без TypeError.
4. Ручной smoke (опционально): `python main.py` → новая игра → походить до
   первой засады: бой открывается, атака/отступление работают, ходы монстра
   видны в журнале.
5. `git status --short` — только ожидаемые файлы; после прогона тестов
   `state_template.json` не «плавает».
6. Обновить `known_issues.md`: пометки `FIXED (<коммит>)` / статусы пропущенных.
7. Сводка: `git log --oneline main..HEAD` + список незакрытых вопросов.

## 8. Definition of Done

| Требование | Отметка |
|---|---|
| Фикс засады применён (или уже был), smoke-скрипт зелёный | ☐ |
| KI-5: pytest не меняет state_template.json | ☐ |
| KI-3: смерть от голода в start_combat не крашит, `player_died` в events | ☐ |
| KI-1: раунды растут, кулдауны тикают, DoT и реген работают | ☐ |
| KI-2: ходы монстра видны в журнале CLI | ☐ |
| KI-6: перк кладоискателя не съедает ролл поиска | ☐ |
| KI-8: look/search/wait в бою дают `err_in_combat` | ☐ |
| KI-9: шанс засады соответствует заявленному | ☐ |
| KI-4: респавн монстров срабатывает (в т.ч. через exploration) | ☐ |
| KI-7: правила времени едины (или задокументировано решение) | ☐ |
| KI-10: еда в бою заблокирована (или вопрос владельца зафиксирован) | ☐ |
| KI-11: мёртвых строк локализации нет | ☐ |
| KI-12: llm.enabled=false в шаблоне | ☐ |
| Все тесты зелёные; новые регресс-тесты добавлены | ☐ |
| known_issues.md обновлён пометками FIXED | ☐ |
| Отчёт: список коммитов и остатков | ☐ |

---

## Приложение А. Smoke-скрипт проверки засады

Сохранить как `scripts/smoke_ambush.py` в репо и запустить
`python scripts/smoke_ambush.py`.

```python
"""Verify ambush -> real combat -> attack & flee work end-to-end."""
import copy
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.exploration import move_to_node, _load_game_data
from engine.combat import combat_step
from engine.data_loader import GameData
from engine.worldgen import generate_region

ROOT = Path(__file__).parent.parent
gd_flat = _load_game_data(str(ROOT / "data"))
GD = GameData(str(ROOT / "data"))

map_data = generate_region(20260101, 1, gd_flat)

st = {
    "schemaVersion": 1,
    "meta": {"seed": 20260101, "region": 1, "difficultyMultiplier": 1.0,
             "llm": {"enabled": False}},
    "player": {
        "level": 1, "xp": 0, "gold": 15,
        "attributes": {"strength": 1, "agility": 1, "constitution": 1,
                       "intelligence": 1, "wisdom": 1},
        "skills": {k: 0 for k in ("melee_heavy", "melee_light", "armor_mastery",
                                   "pyromancy", "restoration", "hexes", "alchemy",
                                   "crafting", "scavenging")},
        "resources": {"hp": {"current": 10, "max": 10}, "mp": {"current": 2, "max": 2}},
        "inventory": [],
        "equipment": {
            "weapon": {"itemId": "wpn_club_simple",
                       "durability": {"current": 15, "max": 15}},
            "armor": {"itemId": "arm_cloth_poor",
                      "durability": {"current": 15, "max": 15}},
        },
    },
    "world": {"day": 1, "stepOfDay": 1, "fedMorning": True, "fedEvening": True,
              "inCombat": False, "activeCombat": None, "activeEffects": [],
              "killsTotal": 0, "locationsVisited": 1},
    "map": map_data, "npcs": {}, "flags": {},
}

cur = next(nd for nd in map_data["nodes"] if nd["connections"])
target_id = cur["connections"][0]
for nd in st["map"]["nodes"]:
    if nd["id"] == target_id:
        nd["state"]["spawnRolled"] = True
        nd["state"]["monster"] = {"mobId": "mob_wolf_forest", "revealed": False,
                                  "hp": 6, "maxHp": 6}
        break
st["map"]["currentNodeId"] = cur["id"]

for seed in range(500):
    st2 = copy.deepcopy(st)
    new_st, events = move_to_node(st2, target_id, rng=random.Random(seed),
                                  game_data=gd_flat)
    if any(e["id"] == "ambush_triggered" for e in events):
        break

print("events after move:", [e["id"] for e in events])
print("inCombat     =", new_st["world"]["inCombat"])
print("activeCombat =", (new_st["world"].get("activeCombat") or {}).get("monster", {}).get("mobId"))
assert new_st["world"]["activeCombat"] is not None, "FIX FAILED: no activeCombat"

# 1) Атака работает
st_at, ev_at = combat_step(new_st, {"type": "attack"}, GD)
print("attack ->", [e["id"] for e in ev_at])
assert not any(e["id"] == "err_not_in_combat" for e in ev_at), "attack still broken"

# 2) Отступление работает: долбим flee, пока не получится
st_cur = new_st
for attempt in range(50):
    st_cur, ev_flee = combat_step(st_cur, {"type": "flee"}, GD)
    ids = [e["id"] for e in ev_flee]
    print(f"flee #{attempt} ->", ids)
    if "combat_fled_success" in ids:
        assert st_cur["world"]["inCombat"] is False
        assert st_cur["world"]["activeCombat"] is None
        print("OK: вышел из боя")
        break
else:
    raise AssertionError("flee never succeeded in 50 attempts (chance 50%)")

print("\nFIX VERIFIED: ambush -> real combat -> attack works, retreat works.")
```

Ожидаемый хвост вывода: `FIX VERIFIED: ambush -> real combat -> attack works, retreat works.`
После запуска проверить `git status` и удалить артефакты (например,
`state_session.json`), если появились.

## Приложение Б. Воспроизведение KI-3 (смерть от голода в start_combat)

Взять конструкцию состояния из Приложения А и заменить финальную часть
(цикл `move_to_node` не нужен — бой стартуем прямо в текущем узле):

```python
st["world"]["fedMorning"] = False      # не ел утром
st["world"]["stepOfDay"] = 6           # дедлайн еды — шаг 7
for nd in st["map"]["nodes"]:
    if nd["id"] == target_id:
        nd["state"]["spawnRolled"] = True
        nd["state"]["monster"] = {"mobId": "mob_wolf_forest", "revealed": True,
                                  "hp": 6, "maxHp": 6}
        break
st["map"]["currentNodeId"] = target_id   # ВАЖНО: монстр — в ТЕКУЩЕМ узле

# пути — во временную папку, чтобы не мусорить репо:
import tempfile
tmp = tempfile.mkdtemp()

new_st, events = start_combat(
    st, GD, is_ambush=False, rng=random.Random(1),
    session_path=f"{tmp}/session.json", template_path=f"{tmp}/template.json",
)
```

(импорт: `from engine.combat import start_combat`; `GD` — объект `GameData`,
не dict-view).

- **До фикса:** `TypeError: 'NoneType' object does not support item assignment`
  (`current_node["state"]["monster"]["revealed"] = True` на свежем
  после-смерти состоянии, где монстра нет).
- **После фикса:** исключения нет; в `events` есть `player_died`;
  `world["inCombat"]` не ставится.
