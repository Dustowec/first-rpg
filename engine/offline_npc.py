"""Офлайн-реплики NPC: приветствия и сценарные ответы без LLM.

Заменяет модель, когда meta.llm.enabled == False или сервер недоступен.
Возвращает тот же контракт § 26.1, поэтому engine/dialogue.py валидирует
ответ как обычно: бартер, скидка и подсказки работают офлайн.
"""

from __future__ import annotations

from typing import Any

OFFLINE_DIALOGUES: dict[str, dict] = {'npc_innkeeper_boris': {'greeting': {'ru': 'Заходи, гость! Очаг тёплый, хлеб свежий. Ночлег — 5 монет.', 'suggestedReplies': ['Есть сломанная рукоять, обменяем на хлеб?', 'Что слышно в округе?', 'Покажи, что есть поесть']}, 'scripts': [{'match': ['рукоят', 'обмен', 'хлеб', 'бартер'], 'ru': 'Вижу, тебя потрепало. Ладно — за твою сломанную рукоять и пару медяков отдам буханку.', 'mood': 'sympathetic', 'action': {'type': 'barter_offer', 'giveItemId': 'food_bread', 'takeItemId': 'junk_broken_hilt', 'goldDelta': -2}, 'suggestedReplies': ['Согласиться на обмен', 'Спросить о слухах', 'Поблагодарить и уйти']}, {'match': ['слух', 'округ', 'новост', 'где', 'расскажи'], 'ru': 'Говорят, у старого кургана логово. Туда без нужды не суйся, парень.', 'mood': 'neutral', 'action': {'type': 'give_hint', 'hintType': 'map'}, 'suggestedReplies': ['Обменяем рукоять на хлеб?', 'Скинешь немного?', 'Уйти']}, {'match': ['скидк', 'дешевл', 'уступ', 'скинешь'], 'ru': 'Для доброго человека — десятая часть с цены долой.', 'mood': 'friendly', 'action': {'type': 'discount_10'}, 'suggestedReplies': ['Покажи, что есть поесть', 'Что слышно в округе?', 'Уйти']}, {'match': ['товар', 'еда', 'поесть', 'купит', 'покажи'], 'ru': 'Хлеб, картошка, сало. Выбирай, кошелёк не резиновый.', 'mood': 'friendly', 'action': {'type': 'open_trade'}, 'suggestedReplies': ['Скинешь немного?', 'Что слышно в округе?', 'Уйти']}]}, 'npc_merchant_ganna': {'greeting': {'ru': 'Товары свежие, цены честные. Смотри, не стесняйся.', 'suggestedReplies': ['Показать товары', 'Скинешь немного?', 'Уйти']}, 'scripts': [{'match': ['скидк', 'дешевл', 'уступ', 'скинешь'], 'ru': 'Ты мне нравишься. Десять процентов скину, только не рассказывай никому.', 'mood': 'friendly', 'action': {'type': 'discount_10'}, 'suggestedReplies': ['Показать товары', 'Уйти']}, {'match': ['товар', 'купит', 'покаж', 'цен', 'зелье'], 'ru': 'Еда, зелья, противоядия. Всё по прейскуранту.', 'mood': 'friendly', 'action': {'type': 'open_trade'}, 'suggestedReplies': ['Скинешь немного?', 'Уйти']}]}, 'npc_blacksmith_kolm': {'greeting': {'ru': 'Молот горячий, руки в саже. Что чинить будем?', 'suggestedReplies': ['Показать товары', 'Скинешь немного?', 'Уйти']}, 'scripts': [{'match': ['скидк', 'дешевл', 'уступ', 'скинешь'], 'ru': 'Ладно, десятку сброшу. Ты человек простой, мне такие по нраву.', 'mood': 'friendly', 'action': {'type': 'discount_10'}, 'suggestedReplies': ['Показать товары', 'Уйти']}, {'match': ['товар', 'оруж', 'брон', 'купит', 'покаж', 'почин', 'чинить'], 'ru': 'Дубины, мечи, латы. Железо честное, работу знаешь.', 'mood': 'neutral', 'action': {'type': 'open_trade'}, 'suggestedReplies': ['Скинешь немного?', 'Уйти']}]}, 'npc_elder_miroslav': {'greeting': {'ru': 'Дороги нынче опасны. Садись, расскажу, что знаю.', 'suggestedReplies': ['Куда идти?', 'Кто слаб к огню?', 'Уйти']}, 'scripts': [{'match': ['слаб', 'огн', 'монстр', 'водит', 'бестиар', 'кто', 'там'], 'ru': 'Нечисть огня боится, а зверь — стали. Запомни это.', 'mood': 'neutral', 'action': {'type': 'give_hint', 'hintType': 'bestiary'}, 'suggestedReplies': ['Куда идти?', 'Уйти']}, {'match': ['куда', 'идти', 'дорог', 'лого', 'карт', 'метк'], 'ru': 'Ступай к кургану, там логово. Но сперва окрепни.', 'mood': 'neutral', 'action': {'type': 'give_hint', 'hintType': 'map'}, 'suggestedReplies': ['Кто слаб к огню?', 'Уйти']}]}, 'npc_herbalist_vela': {'greeting': {'ru': 'Травы сушу, зелья варю. Хвораешь, что ли?', 'suggestedReplies': ['Показать зелья', 'Скинешь немного?', 'Что слышно?', 'Уйти']}, 'scripts': [{'match': ['скидк', 'дешевл', 'уступ', 'скинешь'], 'ru': 'Ты выглядишь скверно. Скину десятую часть, только лечись.', 'mood': 'sympathetic', 'action': {'type': 'discount_10'}, 'suggestedReplies': ['Показать зелья', 'Уйти']}, {'match': ['слух', 'слышн', 'где', 'опасн'], 'ru': 'В болотах тварь ядовитая. Без противоядия туда не ходи.', 'mood': 'neutral', 'action': {'type': 'give_hint', 'hintType': 'bestiary'}, 'suggestedReplies': ['Показать зелья', 'Уйти']}, {'match': ['зель', 'товар', 'купит', 'покаж', 'леч'], 'ru': 'Есть малое лечение, есть побольше. И противоядие припасла.', 'mood': 'friendly', 'action': {'type': 'open_trade'}, 'suggestedReplies': ['Скинешь немного?', 'Что слышно?', 'Уйти']}]}, 'npc_hunter_rask': {'greeting': {'ru': 'Тише. Зверь чуткий. Говори, чего надо.', 'suggestedReplies': ['Обменяем рукоять на противоядие?', 'Куда идти?', 'Уйти']}, 'scripts': [{'match': ['обмен', 'хлам', 'противояд', 'бартер', 'рукоят'], 'ru': 'Рукоять мне на дело пойдёт. Дам за неё противоядие, оно тебе нужнее.', 'mood': 'friendly', 'action': {'type': 'barter_offer', 'giveItemId': 'pot_antidote', 'takeItemId': 'junk_broken_hilt', 'goldDelta': 0}, 'suggestedReplies': ['Согласиться на обмен', 'Куда идти?', 'Уйти']}, {'match': ['куда', 'идти', 'дорог', 'лого', 'карт'], 'ru': 'Тропа к кургану заросла, но пройти можно. Держись правее.', 'mood': 'neutral', 'action': {'type': 'give_hint', 'hintType': 'map'}, 'suggestedReplies': ['Обменяем рукоять на противоядие?', 'Уйти']}]}, 'npc_wanderer_kit': {'greeting': {'ru': 'Хе-хе. Шёл откуда-то, иду куда-то. Поболтаем?', 'suggestedReplies': ['Обменяем рукоять на точило?', 'Что слышно?', 'Уйти']}, 'scripts': [{'match': ['обмен', 'хлам', 'бартер', 'рукоят', 'точил'], 'ru': 'Рукоять? Давай точильный камень, он мне нужнее твоих медяков.', 'mood': 'friendly', 'action': {'type': 'barter_offer', 'giveItemId': 'rep_whetstone', 'takeItemId': 'junk_broken_hilt', 'goldDelta': 0}, 'suggestedReplies': ['Согласиться на обмен', 'Что слышно?', 'Уйти']}, {'match': ['слух', 'слышн', 'где', 'ходит', 'кто'], 'ru': 'Слыхал, мёртвые в руинах огонь не любят. А может, вру.', 'mood': 'neutral', 'action': {'type': 'give_hint', 'hintType': 'bestiary'}, 'suggestedReplies': ['Обменяем рукоять на точило?', 'Уйти']}]}}


def _normalize(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def has_offline_dialogue(npc_id: str) -> bool:
    """Есть ли для NPC набор сценарных реплик."""
    return npc_id in OFFLINE_DIALOGUES


def get_greeting(npc_id: str, game_data: Any) -> dict:
    """Приветствие при входе в диалог (action=none, реплика + варианты)."""
    bundle = OFFLINE_DIALOGUES.get(npc_id)
    if bundle is None:
        from .llm_client import get_fallback_response

        return get_fallback_response(npc_id, "neutral", game_data)
    greeting = bundle["greeting"]
    return {
        "npcReply": greeting["ru"],
        "mood": "neutral",
        "action": {"type": "none"},
        "suggestedReplies": list(greeting["suggestedReplies"]),
    }


def get_offline_response(state: dict, npc_id: str, player_input: str, game_data: Any) -> dict:
    """Подбирает сценарную реплику по фразе игрока (детерминированно)."""
    bundle = OFFLINE_DIALOGUES.get(npc_id)
    if bundle is None:
        from .llm_client import get_fallback_response

        entry = state.get("npcs", {}).get(npc_id, {})
        return get_fallback_response(
            npc_id, entry.get("mood", "neutral"), game_data,
            state_reputation=entry.get("reputation", "neutral"),
        )

    text = _normalize(player_input)
    for script in bundle["scripts"]:
        if any(_normalize(marker) in text for marker in script["match"]):
            return {
                "npcReply": script["ru"],
                "mood": script.get("mood", "neutral"),
                "action": dict(script["action"]),
                "suggestedReplies": list(script["suggestedReplies"]),
            }
    return get_greeting(npc_id, game_data)
