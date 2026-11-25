"""Патч data/strings_ru.json: строки CLI Блока 5.3 + правка битых текстов.

Запуск: python scripts/patch_strings_ru.py  (идемпотентен)
"""

import json
from pathlib import Path

NEW_STRINGS = {
    "system_death_message": "Вы погибли. Ваш путь окончен.",
    "status_mp_low": "Ваша мана на исходе!",
    "danger_safe": "безопасно",
    "danger_low": "низкая",
    "danger_medium": "средняя",
    "danger_high": "высокая",
    "screen_craft": "--- КРАФТ ---",
    "screen_village": "--- NPC И СЕРВИСЫ ---",
    "screen_creation": "Распределите 3 стартовых очка (не более +2 в характеристику):",
    "journal_moved": "Переход: {name}",
    "journal_monster_seen": "Замечен {enemy}!",
    "journal_look_clear": "Вокруг тихо.",
    "journal_ambush": "Засада! {enemy} нападает!",
    "journal_victory": "Победа! Локация зачищена.",
    "journal_lair_next": "Из логова выходит {enemy}!",
    "journal_gold": "Получено {amount} золота.",
    "journal_item_added": "Получено: {item} ({count})",
    "journal_item_removed": "Потрачено: {item} ({count})",
    "journal_sold": "Продано: {item} за {gold} зол.",
    "journal_barter": "Обмен: {take} -> {give}",
    "journal_barter_offer": "Предложен обмен: {give} за {take} ({gold} зол.)",
    "journal_discount": "Скидка {percent}% на следующую покупку!",
    "journal_hint": "Новая подсказка: {target}",
    "journal_reputation": "Отношение {npc}: {reputation}",
    "journal_action_ignored": "NPC не может этого сделать.",
    "journal_fed": "Вы поели.",
    "journal_rested": "Вы переночевали в харчевне.",
    "journal_crafted": "Создано: {item}",
    "journal_sharpened": "Оружие заточено.",
    "journal_region": "Дальние тропы: регион {region}",
    "journal_death": "Вы погибли...",
    "journal_permadeath": "Сессия сброшена. Новая игра.",
    "journal_llm_fallback": "NPC отвечает заготовленной репликой.",
    "journal_waited": "Прошёл один шаг времени.",
    "err_in_combat": "Сейчас идёт бой.",
    "err_npc_not_here": "Этого NPC здесь нет.",
    "err_no_active_barter": "Нет активного предложения обмена.",
    "err_not_enough_gold": "Не хватает золота.",
    "err_not_enough_items": "Не хватает предметов.",
    "err_unknown_command": "Неизвестная команда.",
    "err_no_monster": "Здесь нет противника.",
    "err_monster_not_revealed": "Сначала осмотритесь.",
    "err_search_depleted": "Здесь больше нечего искать.",
    "err_cannot_search_here": "Здесь нельзя искать.",
    "err_already_looked": "Вы уже осмотрелись здесь.",
    "err_invalid_food": "Это нельзя съесть.",
    "err_lair_not_cleared": "Логово ещё не зачищено.",
    "err_not_in_lair": "Дальние тропы доступны только из логова.",
    "err_item_not_found": "Предмет не найден.",
    "err_npc_refuses_trade": "NPC не желает торговать.",
    "err_station_required": "Нужен станок: деревня или лагерь.",
    "err_missing_ingredients": "Не хватает ингредиентов.",
    "err_skill_too_low": "Навык слишком низок.",
}


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "strings_ru.json"
    strings = json.loads(path.read_text(encoding="utf-8"))
    added = 0
    for key, value in NEW_STRINGS.items():
        if strings.get(key) != value:
            strings[key] = value
            added += 1
    path.write_text(json.dumps(strings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"strings_ru.json: обновлено/добавлено {added} строк, всего {len(strings)}")


if __name__ == "__main__":
    main()