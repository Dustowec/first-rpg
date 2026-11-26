# Известные проблемы (повторный аудит после v0.2.0)

Дата повторного аудита: 2026-11-26 (после применения `agent_task.md`, ветка
`fix/audit-20261126`, HEAD `dabdf57`, тег `v0.2.0`). Дата закрытия R-1..R-7:
2026-11-26 (см. «Статус после фиксов» ниже).

Первичный аудит (12 пунктов) — см. историю файла; ниже его верификация + новые
находки. Прогон тестов на момент повторного аудита: **619 passed, 2 skipped**
(было 591/2). `git status` после полного прогона чист (`state_template.json`
больше не «плавает» — KI-5 подтверждён). `python scripts/smoke_ambush.py` →
`FIX VERIFIED`.

Метка «воспроизведено» = баг подтверждён запуском кода; «статически» = по коду.

> ## Статус после фиксов R-1..R-7
>
> Все 7 пунктов повторного аудита закрыты. Базлайн 619/2 → **630 passed, 2
> skipped** (+11 регресс-тестов, `tests/test_reatudit_fixes.py`). Сквозной
> сценарий через `dispatch_command` (start_combat → combat_spell → combat_item
> → attack → победа) отрабатывает без крашей, журнал рендерится по-русски без
> сырых id и плейсхолдеров. `python scripts/smoke_ambush.py` → `FIX VERIFIED`.
>
> | # | Статус |
> |---|---|
> | R-1 | FIXED — реген только в `_end_round`, событие не затирается |
> | R-2 | FIXED — cast/use_item доигрывают раунд (round, кулдаун, тики) |
> | R-3 | FIXED — onHitDot пишется в актуальное состояние, яд тикает по игроку |
> | R-4 | FIXED — формат-агностичный урон + write-back по mobId |
> | R-5 | FIXED — `battle_victory` без плейсхолдеров |
> | R-6 | FIXED — строки для monster_onhit_dot / effect_expired / monster_effect_expired / sys_permadeath_reset |
> | R-7 | FIXED — мёртвый ключ `combat_started` удалён |

---

## Часть 1. Статус 12 пунктов первого аудита (проверено повторно, динамически)

| # | Проблема | Статус | Как проверено |
|---|---|---|---|
| KI-1 | `_end_round` не вызывался, раунды/кулдауны/DoT заморожены | **FIXED** (843fb5b) + закрыт остаток R-2 | attack/flee/ambush/cast/use_item доигрывают раунд; тесты `test_reatudit_fixes.py` |
| KI-2 | ходы монстра «молчали» | **FIXED** (0a2ed1b) | события `battle_enemy_attack/miss` эмитятся и рендерятся в журнале |
| KI-3 | краш при смерти от голода в `start_combat` | **FIXED** (33982bf) | сценарий (шаг 6, `fedMorning=False`) → нет TypeError, `player_died` в events, `inCombat` не ставится |
| KI-4 | респавн монстров мёртв | **FIXED** (3862f4a) | узел с `daysSinceCleared=4`: после смены дня (через `wait`!) — респавн `mob_wolf_forest`, `maxHp=6` (= hp в данных) |
| KI-5 | `create_initial_state` портил шаблон | **FIXED** (4ef87b5) | полный pytest → `git status` чист; шаблон в репо: 25 узлов |
| KI-6 | перк «Чутьё кладоискателя» портил поиск | **FIXED** (561b876) | scavenging=10, 2000 роллов: 1770 находок / 230 честных «ничего» |
| KI-7 | две расходящиеся `advance_time` | **FIXED** (3862f4a) | exploration делегирует в world_time (проверено транзитивно: респавн сработал через `wait`) |
| KI-8 | `look`/`search`/`wait` в бою — no-op | **FIXED** (dedda54) | все три → `err_in_combat` |
| KI-9 | смещение шанса засады | **FIXED** (dedda54) | `randint(1,100)`: 200k роллов → 15,04% при заявленных 15% |
| KI-10 | еда в бою | **FIXED** (80730ed) | `dispatch_command(eat)` в бою → `err_in_combat` |
| KI-11 | мёртвые строки локализации | **FIXED** (43f5856), хвосты R-5/R-6/R-7 закрыты | журнал без сырых id и `{...}` |
| KI-12 | LLM включён в шаблоне | **FIXED** (3a27dd8) | `state_template.json`: `llm.enabled=false`, узлов 25 |

---

## Часть 2. Новые проблемы повторного аудита (все закрыты)

### R-1. Двойной реген монстра — высокая → **FIXED**
Реген удалён из `_execute_monster_turn` (осталось единственное место —
`_end_round`); затирающий `events = []` в `_execute_monster_turn` удалён —
каждое применение регена сопровождается событием. В `_end_round` ссылки
`active_combat`/`combat_mob` обновляются после `tick_combat_round_effects`
(deepcopy) — реген читает/пишет актуального монстра, а не отброшенную копию.
Регресс: `TestR1SingleRegen` — HP монстра за 4 раунда в точности равен
(старт − урон атак + задокументированный реген).

### R-2. Ветки `cast`/`use_item` не доигрывали раунд — высокая → **FIXED**
Обе ветки `combat_step` повторяют паттерн attack-ветки: после хода монстра —
проверка `player_died`/`activeCombat is None`, затем `_end_round` (тики,
кулдауны, реген). Регресс: `TestR2CastUseItemEndRound` — round растёт на 3 за
3 каста/зелья; `crushingCooldown` тикает и через use_item-раунд.

### R-3. Яд монстра (onHitDot) не применялся к игроку — высокая → **FIXED**
После `register_armor_hit` (возвращает новый deepcopy) ссылки
`world`/`player`/`combat_mob` обновляются — запись onHitDot попадает в
актуальное состояние, яд тикает по игроку в `_end_round`. Регресс:
`TestR3OnHitDot` — эффект записан (poison, −1/ход), счётчик тикает.

### R-4. `KeyError: 'resources'` при уроне заклинаний/бомб — высокая → **FIXED**
Два публичных хелпера в `engine/consumables.py`:
- `apply_damage_to_monster(monster, damage)` — урон в любом формате HP;
- `monster_hp_value(monster)` — чтение текущего HP.

Все 6 мест записи урона переведены на хелпер (4 в `magic.py`: огонь/лёд/
гексы/вампиризм; 2 в `consumables.py`: бомба и покрытие `oil_fire`).
Write-back: `_sync_combat_monster(state, target_monster)` в `combat.py`
переносит монстра-цель (урон + наложенные эффекты) в `activeCombat` по
`mobId` после `cast_spell`/`use_consumable`/`process_weapon_coating_on_hit`
(они делают deepcopy и пишут в переданную ссылку). Дополнительно: события
убивающего удара (attack_hit/spell_cast/bomb_hit/monster_dot_tick) больше не
выбрасываются при переходе в `_on_monster_defeated` — журнал видит удар.
Регресс: `TestR4SpellBombDamage` — урон и burn переносятся в состояние;
бомба убивает с `combat_victory`.

### R-5. Строка победы с сырыми плейсхолдерами — косметика → **FIXED**
`battle_victory` в `data/strings_ru.json`: «Победа! Локация зачищена.»
(XP/золото приходят отдельными событиями `xp_gained`/`gold_gained` со своими
строками). Регресс: `TestJournalStrings.test_battle_victory_without_placeholders`.

### R-6. Сырые id событий в журнале — косметика → **FIXED**
В `cli/app.py::event_text` добавлены ветки: `monster_onhit_dot` («Вас
отравили!»), `effect_expired` («Действие эффекта истекло.»),
`monster_effect_expired` («Эффект на враге закончился.») и
`sys_permadeath_reset` (строка `journal_permadeath`). Регресс:
`TestJournalStrings.test_reaudit_event_ids_rendered`.

### R-7. Мёртвый ключ `combat_started` — косметика → **FIXED**
Ключ удалён из `data/strings_ru.json` (рендер события `combat_started`
идёт через `battle_start` с подстановкой имени врага). Регресс:
`TestJournalStrings.test_dead_combat_started_key_removed`.

### Прочее (не баги, зафиксировано для порядка)

- После прогона pytest в корне репо появляется `state_session.json` — он в
  `.gitignore` (строка 3), `git status` не грязнится. Приемлемо.
- `combat_started` несёт поле `enemy` — удобно, не является проблемой.

---

## Часть 3. Вопросы, требующие решения владельца

1. **KI-10 — еда в бою.** Блокировка сделана. Если еда как боевое действие —
   вернуть ветку и описать в спеке §7.
Ответ: сделано верно, по спеке.
2. **KI-7 — голод и MP.** MP-реген блокируется в голодных окнах. Если MP
   должен восстанавливаться и при голоде — снять `and not hungry` у MP-регена
   в `engine/world_time.py`.
Ответ: сделано верно.
3. **KI-4 — «зачищенные» узлы.** Респавн тикает только при
   `spawnRolled=True` и `monster=None`; в нетронутых узлах счётчик остаётся
   `None`. Нужен ли респавн и там — решить и снять условие.
Ответ: сделано верно. Респавн в нетронутых узлах не нужен.
4. ~~**R-1/R-4 — чей формат монстра каноничен?**~~ Закрыто фиксом R-4:
   канон — плоский `hp`/`maxHp` (реальный бой); все записи урона идут через
   `apply_damage_to_monster`, чтение — через `monster_hp_value`, оба формата
   поддерживаются.
Ответ: плоский.

Вопрос 3 из прошлой итерации (реген тролля при засаде) снят фиксом R-1:
реген теперь тикает только в `_end_round` по завершённым раундам, поправка
`isAmbush` удалена вместе со старым блоком регена.

---

## Часть 4. Методика повторного аудита

`git fetch` + сброс клона на `dabdf57`; чтение полного диффа
`031354d..dabdf57` (23 файла, +2362/−374) по движку, CLI и данным; полный
прогон pytest (619/2, `git status` чист после прогона); динамические
эксперименты:

1. тролль: 4 атаки — рост `round`, HP-диффы против лога урона → двойной реген (R-1);
2. 3×`use_item` — `round` замер (R-2);
3. паук: 20 срабатываний onHitDot → эффект в состоянии 0 раз (R-3);
4. `cast spl_spark` / `use_item bmb_fire` в реальном бою → KeyError (R-4);
5. голодная смерть в `start_combat` (KI-3), респавн через `wait` (KI-4),
   перк кладоискателя — 2000 роллов (KI-6), `err_in_combat` для
   look/search/wait/eat (KI-8/KI-10), 200k роллов засады (KI-9);
6. рендер строк журнала для боевых событий (R-5/R-6).

Старая версия (`031354d`) сверялась по `git show` для отделения
пре-существующих багов (R-4) от занесённых фиксами (R-1, R-2, R-3).

Верификация фиксов R-1..R-7: воспроизведение всех четырёх динамических
сценариев до фиксов («ВОСПРОИЗВЕДЕНО» × 4) и после («не подтвердилось» × 4,
`scripts/repro_reatudit.py` на машине аудитора); полный pytest 630/2;
сквозной сценарий `dispatch_command` (start_combat → combat_spell →
combat_item → attack → победа) с контролем журнала CLI.
