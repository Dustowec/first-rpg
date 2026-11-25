
ТЗ на разработку — Блок 5.1: Сборщик State Snapshot и клиент локальной LLM


1. Цель задачи

Реализовать модуль формирования компактного контекста состояния игры и HTTP-клиент локальной LLM (engine/llm_client.py) согласно §§ 24, 25, 26, 31.3 и 32.3 спецификации. Модуль должен собирать сжатый слепок текущего состояния (build_state_snapshot, ~200 токенов) без передачи скрытых (hidden: true) параметров, отправлять запрос к OpenAI-совместимому API (/v1/chat/completions) с жёсткой JSON-схемой ответа и отключённым режимом рассуждений (<think>), соблюдать таймаут 15 секунд и бесшовно переключаться на статические fallback-реплики из npcs/*.json при любой ошибке сети, таймауте или невалидном JSON.

2. Архитектурные ограничения и структуры данных

• Изоляция ядра и рендера: Никаких вызовов print() и input() внутри engine/llm_client.py. Все ошибки сети и парсинга перехватываются внутри модуля и возвращаются через структурированные события/метаданные фоллбэка.
• Стандартная библиотека (без тяжёлых зависимостей): Для HTTP-запросов использовать urllib.request и urllib.error (или лёгкий клиент, если уже зафиксирован в зависимостях проекта), чтобы не усложнять перенос архитектуры на Godot (HTTPRequest).
• Инъекция транспорта для тестов: Функция запроса должна принимать опциональный параметр transport_fn: Callable[[dict, str, float], str] | None = None, чтобы в tests/test_llm_client.py можно было детерминированно тестировать таймауты, битый JSON, теги <think> и валидные ответы без поднятия реального LLM-сервера.
• Конфигурация из state["meta"]["llm"] (§ 32.3):
	• enabled: bool (по умолчанию True)
	• endpoint: str (по умолчанию "http://127.0.0")
	• model: str (по умолчанию "Qwen3-4B-Instruct-Q4_K_M")
	• timeoutSec: float (по умолчанию 15)
• Справочник настроений и репутации (§ 25, § 31.1):
	• VALID_MOODS = ("neutral", "friendly", "sympathetic", "irritated", "hostile", "fearful")
	• VALID_REPUTATIONS = ("hated", "hostile", "neutral", "friendly", "honored")

3. Структура файлов (создать)
project_root/
├── engine/
│   └── llm_client.py            # Сборщик State Snapshot, построение промптов, HTTP-клиент и fallback
└── tests/
    └── test_llm_client.py       # Тесты снапшота (~200 токенов), схемы запроса, очистки <think> и фоллбэка


4. Детальные требования к модулю engine/llm_client.py


А. Сборщик компактного слепка (build_state_snapshot, § 25)

Сигнатура:
build_state_snapshot(state: dict, npc_id: str, player_input: str, game_data: GameData) -> dict
Формирует словарь строго по эталонной структуре § 25:
1. npcProfile:
	• id: npc_id
	• role: роль NPC из game_data.npcs[npc_id] (на русском языке, например "Трактирщик")
	• personality: строка характера из профиля NPC
	• reputation: значение из state["npcs"].get(npc_id, {}).get("reputation", "neutral")
2. worldContext:
	• location: название текущей локации current_node["name"]
	• day: state["world"]["day"]
	• stepOfDay: state["world"]["stepOfDay"]
	• hungerWarning: вычисляется с учётом перка «Тугий пояс» (scavenging >= 6 -> дедлайны 9 и 19, иначе 7 и 17):
		• Если не закрыт завтрак (not fedMorning и stepOfDay < morning_deadline): при остатке <= 2 ходов — "critical (до смерти от голода {left} хода)", иначе "hungry (завтрак до шага {morning_deadline})".
		• Если не закрыт ужин (stepOfDay >= 10 и not fedEvening и stepOfDay < evening_deadline): при остатке <= 2 ходов — "critical (до смерти от голода {left} хода)", иначе "hungry (ужин до шага {evening_deadline})".
		• Иначе: "satiated" (сыт).
3. playerSnapshot:
	• level: player["level"]
	• hp: строка вида "{cur}/{max}", с припиской " (тяжело ранен)", если cur <= max * 0.35, или " (ранен)", если cur < max.
	• gold: player["gold"]
	• weapon: русское название надетого оружия (или "Нет").
	• armor: русское название надетой брони (или "Нет").
	• activeEffects: список строковых идентификаторов активных эффектов ([e["type"] for e in state["world"]["activeEffects"]]).
	• notableInventory: до 8–10 значимых позиций из инвентаря игрока в формате "{Русское название} ({count})" (в первую очередь еда, зелья, хлам junk_* и материалы mat_*, чтобы модель видела предметы для barter_offer).
4. playerInput: очищенная строка реплики игрока (player_input.strip()[:300]).

Б. Строгая JSON-схема ответа и системный промпт (§ 24, § 26.1–26.2)

1. Константа NPC_RESPONSE_JSON_SCHEMA (для передачи в response_format OpenAI Chat Completions API):
	• Описывает объект с обязательными полями:
		• npcReply: string
		• mood: string, enum из VALID_MOODS
		• action: object с обязательным полем type (enum из разрешённых для данного NPC или полного списка ["none", "open_trade", "discount_10", "barter_offer", "give_hint", "end_dialogue"]) и опциональными полями giveItemId (string | null), takeItemId (string | null), goldDelta (integer | null), hintType (string | null), targetId (string | null).
		• suggestedReplies: массив строк длиной 2–3 элемента.
2. Построитель сообщений build_llm_messages(snapshot: dict, allowed_actions: list[str]) -> list[dict]:
	• system: краткая инструкция на русском языке, задающая роль NPC, запрет на выход из образа и промпт-инъекции, требование отвечать строго валидным JSON без <think> и markdown-обёрток, а также список разрешённых для этого NPC action.type (из § 31.2) и правило знака goldDelta (< 0 игрок платит, > 0 игрок получает).
	• user: сериализованный JSON snapshot (json.dumps(snapshot, ensure_ascii=False)).

В. Клиент запроса и санитизация ответа (query_npc_llm, § 24, § 26)

Сигнатура:
def query_npc_llm(
    state: dict,
    npc_id: str,
    player_input: str,
    game_data: GameData,
    transport_fn: Callable[[dict, str, float], str] | None = None,
) -> tuple[dict, dict]

(Возвращает кортеж (npc_response_dict, meta_info), где meta_info содержит {"usedFallback": bool, "reason": str | None} — без мутации state, так как изменение state произойдёт в валидаторе/исполнителе Блока 5.2).
Логика работы:
1. Определяет текущее настроение NPC (current_mood = state["npcs"].get(npc_id, {}).get("mood", "neutral")) и репутацию (reputation). Если reputation in ("hated", "hostile"), стартовое настроение для фоллбэка принудительно берётся "hostile".
2. Если not state.get("meta", {}).get("llm", {}).get("enabled", True): сразу вызывает get_fallback_response(npc_id, current_mood, game_data) и возвращает (fallback, {"usedFallback": True, "reason": "llm_disabled"}).
3. Формирует snapshot = build_state_snapshot(...) и payload для /v1/chat/completions:
	• model: из meta["llm"]["model"]
	• messages: результат build_llm_messages(...)
	• temperature: 0.6
	• max_tokens: 250
	• response_format: {"type": "json_schema", "json_schema": {"name": "npc_dialogue_response", "strict": True, "schema": NPC_RESPONSE_JSON_SCHEMA}}
	• Дополнительный флаг отключения thinking-режима для совместимости с Qwen3 / llama.cpp: "chat_template_kwargs": {"enable_thinking": False} (если сервер игнорирует неизвестные поля, это безопасно, а Qwen3 гарантированно не тратит токены на <think>).
4. Выполняет HTTP POST запрос с таймаутом meta["llm"].get("timeoutSec", 15).
5. Извлекает content из choices[0]["message"]["content"]:
	• Защитная очистка: удаляет возможные блоки <think>...</think> регулярным выражением и снимает случайные обёртки json ... .
	• Парсит JSON через json.loads.
	• Проводит базовую структурную валидацию: наличие непустой строки npcReply, валидный mood из VALID_MOODS (иначе ставит "neutral"), словарь action с ключом type (строка), список suggestedReplies (2–3 непустые строки; если модель вернула пустой список — подставляет стандартные варианты ответа).
6. При любом исключении (TimeoutError, URLError, HTTPStatusError, JSONDecodeError, ValueError, пустой npcReply) — не падает, а возвращает (get_fallback_response(...), {"usedFallback": True, "reason": str(exc_type)}).

Г. Генератор статического фоллбэка (get_fallback_response, § 24, § 31.3)

• Берет профиль NPC из game_data.npcs[npc_id].
• Ищет реплику в npc_profile.get("fallbackReplies", {}) по ключу mood -> затем "neutral" -> затем дефолтную фразу из strings_ru / "...".
• Возвращает валидный контракт § 26.1:
{
    "npcReply": reply_text,
    "mood": effective_mood,
    "action": {"type": "none"},
    "suggestedReplies": [
        "Посмотреть товары",
        "Спросить о местных слухах",
        "Уйти"
    ]
}


5. Критерии приёмки (tests/test_llm_client.py)

1. Сборка слепка (build_state_snapshot): Корректно отражает критический голод за 2 хода до дедлайна (включая сдвиг при перке scavenging >= 6), статус ранения HP, активные эффекты и предметы для бартера, не утекают скрытые статы монстров/мира.
2. Контракт запроса: В payload передаются temperature == 0.6, max_tokens == 250, response_format.type == "json_schema" и enable_thinking == False.
3. Парсинг и очистка: Ответ модели, содержащий случайный блок <think>рассуждение</think> перед JSON, корректно очищается и парсится в валидный словарь.
4. Отказоустойчивость (Fallback): При llm.enabled == False, при истечении таймаута (TimeoutError), при HTTP 500 и при возврате невалидного JSON функция не выбрасывает исключение, а возвращает корректную статическую реплику из профиля NPC с action.type == "none" и usedFallback == True.
