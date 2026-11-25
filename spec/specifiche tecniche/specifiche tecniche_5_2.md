
ТЗ на разработку — Блок 5.2: Валидатор и исполнитель действий NPC


1. Цель задачи

Реализовать модуль валидации ответов LLM и исполнения разрешённых действий NPC (engine/dialogue.py) согласно §§ 7.1, 26 и 31 спецификации. Модуль является жёстким гейткипером между нейросетью и состоянием мира: он проверяет присутствие NPC, обновляет его настроение (mood) и флаг знакомства (met), фильтрует action.type по индивидуальному белому списку NPC (§ 31.2), проверяет инварианты баланса для бартера, скидок и подсказок, ограничивает сдвиг reputation не более чем на 1 шаг за диалог (§ 31.1) и не тратит AP (§ 7.1).

2. Архитектурные ограничения и структуры данных

• Чистые функции (Pure Functions): Никакого print(), input() и глобального random. Все функции принимают state, не мутируют входной словарь напрямую (работают с глубокой копией) и возвращают (new_state, events).
• Время суток (§ 7.1): Диалоги с NPC и исполнение их действий не продвигают stepOfDay и не тратят AP.
• Белый список действий по каждому NPC (§ 26.2, § 31.2):
	• Глобально допустимые типы: {"none", "open_trade", "discount_10", "barter_offer", "give_hint", "end_dialogue"}.
	• Индивидуальные белые списки (сверяются с полем allowedActions в game_data.npcs[npc_id], с дефолтным маппингом по таблице § 31.2 + "end_dialogue" для возможности прервать разговор):
		• npc_elder_miroslav: {"give_hint", "none", "end_dialogue"}
		• npc_merchant_ganna: {"open_trade", "discount_10", "none", "end_dialogue"}
		• npc_blacksmith_kolm: {"open_trade", "discount_10", "none", "end_dialogue"}
		• npc_innkeeper_boris: {"barter_offer", "discount_10", "give_hint", "none", "end_dialogue"}
		• npc_herbalist_vela: {"open_trade", "discount_10", "give_hint", "none", "end_dialogue"}
		• npc_hunter_rask: {"give_hint", "barter_offer", "discount_10", "none", "end_dialogue"}
		• npc_wanderer_kit: {"barter_offer", "give_hint", "none", "end_dialogue"}
• Хранение отложенного предложения бартера (pendingBarter):
	• Поскольку в § 26.1 модель предлагает бартер ("type": "barter_offer"), а в suggestedReplies игрок может как согласиться, так и отказаться, предложение сохраняется в state["npcs"][npc_id]["pendingBarter"], а фактический обмен выполняется отдельной детерминированной функцией accept_barter_offer(state, npc_id, game_data) (либо сразу при подтверждении игроком в CLI/UI).

3. Структура файлов (создать)
project_root/
├── engine/
│   └── dialogue.py              # Валидатор ответа LLM, исполнитель action и контроль сдвига репутации
└── tests/
    └── test_dialogue.py         # Тесты фильтрации action, barter_offer, discount_10, give_hint и репутации


4. Детальные требования к модулю engine/dialogue.py


А. Пошаговая обработка ответа NPC (process_npc_dialogue, § 26, § 31)

Сигнатура:
def process_npc_dialogue(
    state: dict,
    npc_id: str,
    player_input: str,
    llm_response: dict,
    game_data: GameData,
    rng: random.Random | None = None,
) -> tuple[dict, list[dict]]

(Принимает уже полученный от query_npc_llm словарь llm_response, чтобы сам dialogue.py оставался полностью детерминированным и не зависел от сети).
Логика исполнения:
1. Проверка условий:
	• Если state["world"]["inCombat"] is True -> вернуть (state, [{"id": "err_in_combat"}]).
	• Если not is_npc_present(state, npc_id) -> вернуть (state, [{"id": "err_npc_not_here", "npcId": npc_id}]).
2. Обновление базового состояния NPC:
	• Гарантировать наличие записи state["npcs"][npc_id] с дефолтами {"mood": "neutral", "reputation": "neutral", "met": False}.
	• Установить npc_state["met"] = True.
	• Обновить npc_state["mood"]: если llm_response.get("mood") входит в VALID_MOODS, записать его; при reputation in ("hated", "hostile") принудительно ограничить настроение до "hostile" или "irritated".
3. Эвристика защиты от хамства / попыток взлома диалога (§ 26.2, § 31.1):
	• Если action.type == "end_dialogue" при том, что модель выставила mood in ("hostile", "irritated"), или явное оскорбление: применить сдвиг репутации reputation_delta = -1 (строго соблюдая лимит не более 1 шага за диалог, см. пункт В).
4. Валидация и исполнение action (§ 26.2):
	• Извлечь action = llm_response.get("action") or {"type": "none"}.
	• Проверить action_type in allowed_actions_for_npc. Если действия нет в белом списке данного NPC -> молча проигнорировать действие (свести к "none") и записать событие {"id": "dialogue_action_ignored", "reason": "not_allowed_for_npc", "actionType": action_type}.
	• Выполнить одно из разрешённых действий:
		• "none": никаких игровых изменений.
		• "open_trade": если reputation in ("hated", "hostile") -> игнорировать (err_npc_refuses_trade), иначе сгенерировать событие {"id": "dialogue_open_trade", "npcId": npc_id}.
		• "discount_10" (§ 26.2):
			• Условие допуска: npc_state["mood"] in ("friendly", "sympathetic") И npc_state["reputation"] not in ("hated", "hostile").
			• Если условие выполнено: установить npc_state["tempDiscount10"] = True и добавить событие {"id": "dialogue_discount_granted", "npcId": npc_id, "discountPercent": 10}.
			• Иначе: отклонить с событием {"id": "dialogue_action_ignored", "reason": "discount_conditions_not_met"}.
		• "barter_offer" (§ 26.2, § 31.1):
			• Условие допуска: npc_state["reputation"] not in ("hated", "hostile").
			• Валидация параметров предложения (giveItemId, takeItemId, goldDelta):
				• give_item = game_data.get_item(give_item_id) существует, не является квестовым/запрещённым, его цена economy.buyPrice <= 15 (ограничение § 26.2: «дешёвого предмета tier 1, цена до 15 зол.»).
				• take_item = game_data.get_item(take_item_id) существует и имеет category in ("junk", "material") (хлам/материалы § 26.2), и у игрока в инвентаре есть минимум 1 ед. takeItemId.
				• gold_delta = int(action.get("goldDelta") or 0): проверка адекватности (-15 <= gold_delta <= 10) и наличия золота у игрока, если gold_delta < 0 (player["gold"] >= abs(gold_delta)).
			• Если валидация прошла: сохранить npc_state["pendingBarter"] = {"giveItemId": give_item_id, "takeItemId": take_item_id, "goldDelta": gold_delta} и добавить событие {"id": "dialogue_barter_offered", "npcId": npc_id, "offer": npc_state["pendingBarter"]}.
			• Если модель выдумала несуществующий ID, дорогой меч или предмет, которого нет у игрока: очистить pendingBarter и добавить {"id": "dialogue_action_ignored", "reason": "invalid_barter_params"}.
		• "give_hint" (§ 26.2):
			• Выбирает либо нераскрытую точку интереса на карте (например, путь в сторону логова lair или ближайший неизученный узел с danger >= 2, записывая её ID в state["flags"].setdefault("revealedHints", [])), либо добавляет запись о слабости случайного монстра региона в state["flags"].setdefault("bestiaryUnlocked", []).
			• Генерирует событие {"id": "dialogue_hint_given", "npcId": npc_id, "hintType": ..., "targetId": ...}.
		• "end_dialogue":
			• Очищает npc_state["pendingBarter"] = None и добавляет событие {"id": "dialogue_ended", "npcId": npc_id}.
5. Возвращает (new_state, events), где первым событием всегда идёт:
{
    "id": "npc_spoke",
    "npcId": npc_id,
    "npcReply": llm_response["npcReply"],
    "mood": npc_state["mood"],
    "suggestedReplies": llm_response.get("suggestedReplies", [])
}


Б. Подтверждение бартера (accept_barter_offer, § 26.1, § 31.1)

Сигнатура:
accept_barter_offer(state: dict, npc_id: str, game_data: GameData) -> tuple[dict, list[dict]]
1. Проверяет is_npc_present(state, npc_id) и наличие активного offer = state["npcs"][npc_id].get("pendingBarter"). Если предложения нет -> err_no_active_barter.
2. Повторно проверяет, что у игрока всё ещё есть 1 ед. offer["takeItemId"] и хватает золота, если offer["goldDelta"] < 0.
3. Выполняет атомарный обмен:
	• Списывает 1 ед. offer["takeItemId"] через remove_item.
	• Корректирует player["gold"] += offer["goldDelta"].
	• Выдаёт 1 ед. offer["giveItemId"] через add_item.
	• Сбрасывает npc_state["pendingBarter"] = None.
4. Увеличивает счётчик успешных бартеров npc_state["barterCount"] = npc_state.get("barterCount", 0) + 1. Согласно § 31.1 («три удачных бартера +1»): если barterCount % 3 == 0, сдвигает репутацию на +1 (с учётом лимита диалога).
5. Возвращает (new_state, [{"id": "barter_completed", "npcId": npc_id, "offer": offer}]).

В. Контроль лимита сдвига репутации за диалог (apply_dialogue_reputation_shift, § 31.1)

• В npc_state хранится dialogueRepDeltaThisSession: int (сбрасывается в 0 при входе/выходе из диалога функцией reset_dialogue_session(state, npc_id)).
• Правило § 31.1: «клампится движком: не больше 1 шага за диалог» (исключение: прямое нападение −2, которое в мирном диалоге недоступно).
• Любой вызов apply_dialogue_reputation_shift(state, npc_id, delta) внутри диалога проверяет, чтобы суммарный сдвиг за текущий диалог оставался в диапазоне [-1, +1], и делегирует изменение в shift_reputation из блока 4.4.

5. Критерии приёмки (tests/test_dialogue.py)

1. Фильтрация по белому списку: Если npc_elder_miroslav возвращает "action": {"type": "open_trade"} или "barter_offer", движок игнорирует действие (dialogue_action_ignored) и не меняет инвентарь/золото.
2. Условия discount_10: Скидка устанавливается (tempDiscount10 = True) только при mood in ("friendly", "sympathetic") и reputation not in ("hated", "hostile"); при mood == "irritated" или reputation == "hostile" скидка отклоняется.
3. Валидация и исполнение barter_offer: Эталонный пример § 26.1 (Борис меняет food_bread на junk_broken_hilt + goldDelta: -2) успешно проходит валидацию и исполняется через accept_barter_offer; попытка обменять предмет дороже 15 золота или предмет, которого нет у игрока, блокируется.
4. Три бартера и кап репутации: После 3 успешных бартеров репутация поднимается на +1 шаг, но повторные триггеры в рамках одного диалога не позволяют поднять или опустить её более чем на 1 уровень за сессию диалога.
5. Подсказки (give_hint): Корректно добавляют запись в flags["revealedHints"] или flags["bestiaryUnlocked"] без траты AP.
