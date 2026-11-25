
ТЗ на разработку — Блок 1.1: Каркас проекта, контракты state и менеджер сохранений


1. Цель задачи

Создать базовую архитектуру проекта текстового survival-RPG прототипа на Python 3.11+ (без сторонних тяжёлых зависимостей, только стандартная библиотека json, os, copy, datetime, pathlib, typing + pytest для тестов), определить контракты данных состояния игры (state) и реализовать отказоустойчивый атомарный менеджер сохранений с поддержкой перманентной смерти (permadeath) и настроек сложности.

2. Архитектурные ограничения (обязательно)

• Разделение логики и UI: Модули ядра (engine/) не должны содержать вызовов print() или input(). Все функции возвращают обновлённое состояние и структурированные события (ID событий и параметры), чтобы позже игру можно было легко портировать на Godot (§34 спеки).
• Совместимость со схемой: Версия схемы состояния строго schemaVersion = 1.

3. Структура проекта (создать файлы)

project_root/
├── data/                    # Папка для статических JSON-баз (пока пустая + .gitkeep)
├── engine/
│   ├── __init__.py
│   ├── constants.py         # Константы прогрессии, сложности, имён файлов
│   ├── models.py            # Фабрики, типизация (TypedDict / dataclasses) и валидатор state
│   └── storage.py           # Загрузка, атомарное сохранение, бекап, permadeath-сброс
├── cli/
│   └── __init__.py
├── tests/
│   └── test_storage.py      # Юнит-тесты для блока 1.1
├── state_template.json      # Стартовый шаблон новой игры (фикстура)
└── main.py                  # Заглушка точки входа


4. Детальные требования к модулям


А. engine/constants.py

Зафиксировать константы:
• SCHEMA_VERSION = 1
• DEFAULT_SESSION_PATH = "state_session.json"
• DEFAULT_TEMPLATE_PATH = "state_template.json"
• Капы и стартовые границы персонажа:
	• LEVEL_MIN = 1, LEVEL_MAX = 20
	• ATTR_MIN = 1, ATTR_MAX = 10
	• SKILL_MIN = 0, SKILL_MAX = 10
	• STARTING_UNSPENT_ATTR_POINTS = 3
	• MAX_START_ATTR_BONUS = 2 (на 1-м уровне атрибут не выше 3)
• Настройки сложности (DIFFICULTY_MULTIPLIERS):
	• "easy": 0.75
	• "normal": 1.0 (по умолчанию)
	• "hard": 1.4
	• "impossible": 2.0
• Списки канонических ключей:
	• ATTRIBUTES = ("strength", "agility", "constitution", "intelligence", "wisdom")
	• SKILLS = ("melee_heavy", "melee_light", "armor_mastery", "pyromancy", "restoration", "hexes", "alchemy", "crafting", "scavenging")

Б. engine/models.py и state_template.json

1. Реализовать функцию create_default_player() -> dict, возвращающую эталонный профиль игрока 1-го уровня:
{
  "id": "player_default",
  "level": 1,
  "xp": 0,
  "gold": 15,
  "unspentPoints": { "attributes": 3, "skills": 0 },
  "resources": {
    "hp": { "current": 10, "max": 10 },
    "mp": { "current": 2, "max": 2 }
  },
  "attributes": {
    "strength": 1, "agility": 1, "constitution": 1, "intelligence": 1, "wisdom": 1
  },
  "skills": {
    "melee_heavy": 0, "melee_light": 0, "armor_mastery": 0,
    "pyromancy": 0, "restoration": 0, "hexes": 0,
    "alchemy": 0, "crafting": 0, "scavenging": 0
  },
  "equipment": {
    "weapon": { "itemId": "wpn_club_simple", "durability": { "current": 15, "max": 15 } },
    "armor": { "itemId": "arm_cloth_poor", "durability": { "current": 15, "max": 15 } }
  },
  "inventory": [
    { "itemId": "food_berries", "count": 2 },
    { "itemId": "food_bread", "count": 1 },
    { "itemId": "pot_heal_minor", "count": 1 }
  ]
}

1. (Примечание: слоты weapon и armor в equipment могут также принимать None, если предмет снят).
2. Реализовать функцию create_initial_state(seed: int = 20260101, difficulty: str = "normal") -> dict и сохранить её результат в state_template.json:
{
  "schemaVersion": 1,
  "meta": {
    "seed": 20260101,
    "region": 1,
    "difficulty": "normal",
    "difficultyMultiplier": 1.0,
    "xpRate": 1.0,
    "llm": {
      "enabled": true,
      "endpoint": "http://127.0.0",
      "model": "Qwen3-4B-Instruct-Q4_K_M",
      "timeoutSec": 15
    }
  },
  "player": "<результат create_default_player()>",
  "world": {
    "day": 1,
    "stepOfDay": 1,
    "fedMorning": false,
    "fedEvening": false,
    "inCombat": false,
    "activeEffects": [],
    "killsTotal": 0,
    "locationsVisited": 1
  },
  "map": {
    "currentNodeId": "node_00",
    "nodes": [
      {
        "id": "node_00",
        "type": "village",
        "name": "Приграничная деревня",
        "danger": 0,
        "depth": 0,
        "connections": [],
        "state": {
          "visited": true,
          "lookUsed": false,
          "searchCount": 0,
          "searchMax": 0,
          "searchDepleted": true,
          "spawnRolled": true,
          "monster": null,
          "daysSinceCleared": 0
        }
      }
    ]
  },
  "npcs": {
    "npc_elder_miroslav": { "mood": "neutral", "reputation": "neutral", "met": false },
    "npc_merchant_ganna": { "mood": "neutral", "reputation": "neutral", "met": false },
    "npc_blacksmith_kolm": { "mood": "neutral", "reputation": "neutral", "met": false },
    "npc_innkeeper_boris": { "mood": "neutral", "reputation": "neutral", "met": false },
    "npc_herbalist_vela": { "mood": "neutral", "reputation": "neutral", "met": false }
  },
  "flags": {
    "introShown": false,
    "isDead": false,
    "deathReason": null
  }
}

1. (Важно: в node.state сразу закладываем поле "daysSinceCleared": 0 под правило респавна 1 монстра раз в 5 дней).
2. Реализовать функцию validate_state(state: dict) -> None:
	• Проверяет наличие верхнеуровневых ключей: schemaVersion, meta, player, world, map, npcs, flags.
	• Проверяет state["schemaVersion"] == 1.
	• Проверяет наличие всех 5 атрибутов (значения в диапазоне 1..10) и всех 9 навыков (значения в диапазоне 0..10).
	• Проверяет 1 <= player["level"] <= 20.
	• Проверяет, что map["currentNodeId"] существует среди id в map["nodes"].
	• При любом нарушении выбрасывает ValueError с понятным описанием.

В. engine/storage.py

1. save_state(state: dict, path: str = DEFAULT_SESSION_PATH) -> None:
	• Перед записью вызывает validate_state(state).
	• Атомарная запись: пишет JSON (ensure_ascii=False, indent=2) во временный файл f"{path}.tmp", делает flush() + os.fsync(), затем атомарно заменяет целевой файл через os.replace(tmp_path, path).
2. new_game(template_path: str = DEFAULT_TEMPLATE_PATH, session_path: str = DEFAULT_SESSION_PATH, difficulty: str = "normal", seed: int | None = None) -> dict:
	• Загружает template_path (если шаблона нет на диске — генерирует через create_initial_state()).
	• Применяет выбранную сложность (difficulty и соответствующий difficultyMultiplier) и seed (если передан).
	• Сохраняет новый сейв в session_path через save_state и возвращает state.
3. load_state(session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]:
	• Возвращает кортеж (state, events) (без print!).
	• Если session_path не существует → вызывает new_game(...) и возвращает событие {"id": "sys_new_game"}.
	• Если session_path существует → читает JSON, прогоняет validate_state(state).
	• Если state["flags"].get("isDead") is True → полный сброс (permadeath): удаляет session_path, стартует new_game(...) и добавляет событие {"id": "sys_permadeath_reset"}.
	• Если файл повреждён (ошибка парсинга JSON или ValueError от validate_state) → переименовывает битый файл в state_backup_ГГГГММДД-ЧЧММ.json, запускает new_game(...) и возвращает событие {"id": "sys_corrupted_backup", "backupPath": ...}.
4. handle_player_death(state: dict, reason: str, session_path: str = DEFAULT_SESSION_PATH, template_path: str = DEFAULT_TEMPLATE_PATH) -> tuple[dict, list[dict]]:
	• Помечает state["flags"]["isDead"] = True, state["flags"]["deathReason"] = reason.
	• Выполняет полный сброс сессии: удаляет session_path (если существует), создаёт чистое состояние через new_game(template_path, session_path) и возвращает (fresh_state, [{"id": "player_died", "reason": reason}, {"id": "sys_permadeath_reset"}]).

5. Критерии приёмки (tests/test_storage.py)

Написать и прогнать тесты через pytest:
1. Генерация эталонного state и прохождение validate_state().
2. Отказ validate_state() при неверной schemaVersion, выходе атрибута за 1..10, навыка за 0..10 или несуществующем currentNodeId.
3. Атомарное сохранение и последующая корректная загрузка state_session.json (временный .tmp файл не остаётся).
4. Обработка битого JSON: создание state_backup_ГГГГММДД-ЧЧММ.json, отсутствие исключения наружу и автоматический старт новой игры.
5. Срабатывание handle_player_death() и загрузка сейва с isDead == True → полный сброс сессии в состояние новой игры.
6. Корректная установка difficultyMultiplier (0.75 / 1.0 / 1.4 / 2.0).
