
ТЗ на разработку — Блок 2.1: Прогрессия персонажа, атрибуты, навыки и реестр вех


1. Цель задачи

Реализовать чистый, не зависящий от UI модуль прогрессии персонажа (engine/progression.py), который рассчитывает производные параметры (MaxHP, MaxMP, xpToNextLevel), управляет распределением очков атрибутов (на старте и при повышении уровня), начисляет опыт и обрабатывает Level-Up, а также предоставляет удобный интерфейс проверки открытых вех (перков 3/6/10 уровней навыков) для остальных систем движка.

2. Архитектурные ограничения

• Чистые функции / предсказуемая мутация: Функции принимают state: dict (и при необходимости game_data: GameData), не используют print() / input() и возвращают (new_state, events) или вычисленные значения.
• Соблюдение капов: Уровень строго 1..20, атрибуты строго 1..10, навыки строго 0..10. Любая попытка нарушить лимиты возвращает событие ошибки или выбрасывает ValueError в низкоуровневых расчётах.

3. Структура файлов (создать / обновить)

Показать код
Скачать диаграмму в формате SVG
project_root/
├── engine/
│   ├── __init__.py
│   └── progression.py       # Расчёт ресурсов, XP, распределение очков, реестр вех
└── tests/
    └── test_progression.py  # Юнит-тесты формул прогрессии, стартовых лимитов, левел-апа и перков


4. Детальные требования к модулю engine/progression.py


А. Формулы расчёта производных параметров (§1, §9.2, §10.2)

1. calc_max_hp(level: int, constitution: int) -> int:
	• Формула: 10 + (level - 1) * 2 + (constitution - 1) * 2
	• Проверка граничных точек: level=1, con=1 -> 10; level=20, con=1 -> 48; level=20, con=10 -> 66.
2. calc_max_mp(level: int, wisdom: int) -> int:
	• Формула: 2 + (level - 1) * 1 + (wisdom - 1) * 2
	• Проверка граничных точек: level=1, wis=1 -> 2; level=20, wis=1 -> 21; level=20, wis=10 -> 39.
3. xp_to_next_level(level: int) -> int | None:
	• Если level >= 20: возвращает None (достигнут жёсткий кап 20).
	• Иначе: round(50 * (level ** 1.35)) (в Python использовать стандартный round(), проверить: level=1 -> 50, level=2 -> 127, level=10 -> 1119, level=19 -> 2662).
4. sync_derived_resources(player: dict, restore_delta: bool = True) -> None:
	• Пересчитывает new_max_hp = calc_max_hp(...) и new_max_mp = calc_max_mp(...).
	• Если restore_delta == True (например, при повышении constitution или wisdom или Level-Up): увеличивает hp.current на разницу max(0, new_max_hp - old_max_hp) и аналогично для mp.current, затем клампит current в [0, new_max].

Б. Распределение стартовых атрибутов и прокачка (§9.1, §10.1)

1. allocate_attribute(state: dict, attr_id: str, is_creation: bool = False) -> tuple[dict, list[dict]]:
	• Работает с копией state (copy.deepcopy).
	• Проверяет, что attr_id входит в ATTRIBUTES (strength, agility, constitution, intelligence, wisdom) и player["unspentPoints"]["attributes"] >= 1. Если нет — возвращает (state, [{"id": "err_no_attribute_points"}]).
	• Проверяет жёсткий кап 10 (current_val < 10).
	• Правило создания персонажа (is_creation == True или player["level"] == 1 при стартовом распределении): в один атрибут нельзя вложить более +2 очков сверх базовой единицы (то есть current_val < 3). При попытке поднять выше 3 на 1-м уровне при создании возвращать событие {"id": "err_creation_attr_cap", "attr": attr_id, "max": 3}.
	• Списывает 1 очко из unspentPoints.attributes, увеличивает атрибут на +1, вызывает sync_derived_resources(player, restore_delta=True) (ретроактивный прирост +2 HP за constitution и +2 MP за wisdom).
	• Возвращает (new_state, [{"id": "attr_increased", "attr": attr_id, "value": new_val}]).
2. allocate_skill(state: dict, skill_id: str) -> tuple[dict, list[dict]]:
	• Проверяет наличие skill_id в SKILLS, наличие unspentPoints.skills >= 1 и кап < 10.
	• Списывает 1 очко навыков, увеличивает player["skills"][skill_id] на +1.
	• Проверяет, достигнута ли веха (new_val in (3, 6, 10)): если да, добавляет дополнительное событие {"id": "perk_unlocked", "skill": skill_id, "level": new_val}.
	• Возвращает (new_state, events).

В. Начисление опыта и Level-Up (§10, §29.4)

1. grant_xp(state: dict, base_xp: int) -> tuple[dict, list[dict]]:
	• Если player["level"] >= 20: опыт не начисляется (кап), возвращает (state, []).
	• Учитывает настраиваемый множитель из state["meta"].get("xpRate", 1.0): gained = round(base_xp * xp_rate).
	• Прибавляет gained к player["xp"], генерирует событие {"id": "xp_gained", "amount": gained}.
	• В цикле while player["level"] < 20:
		• Сравнивает player["xp"] с req = xp_to_next_level(player["level"]).
		• Если player["xp"] >= req:
			• Вычитает req из player["xp"].
			• Повышает player["level"] += 1.
			• Начисляет +1 к unspentPoints.attributes и +1 к unspentPoints.skills.
			• Вызывает sync_derived_resources(player, restore_delta=True) (безусловные +2 MaxHP и +1 MaxMP + восстановление этой разницы).
			• Добавляет событие {"id": "level_up", "level": player["level"]}.
		• Если достигнут 20-й уровень (player["level"] == 20), обнуляет остаток player["xp"] = 0.
	• Возвращает (new_state, events).

Г. Реестр и проверка вех (Перков §22)

Реализовать чистые хелперы для проверки открытых вех игрока (используются в бою, магии, ремесле и поиске):
• has_milestone(player: dict, skill_id: str, milestone_level: int) -> bool: возвращает player["skills"].get(skill_id, 0) >= milestone_level.
• Конкретные семантические флаги-геттеры (чтобы не размазывать магические числа 3, 6, 10 по всему коду):
	• Боевые (melee_heavy): has_stunning_blow (3), has_armor_sunder (6), has_crushing_strike (10)
	• Боевые (melee_light): has_lunge (3), has_long_reach (6), has_deadly_precision (10)
	• Броня (armor_mastery): has_armor_comfort (3), has_tempering (6), has_unbreakable (10)
	• Пиромантия (pyromancy): has_intense_heat (3), has_concentration (6), has_elemental_breakthrough (10)
	• Восстановление (restoration): has_frugality (3), has_sturdy_barrier (6), has_second_wind (10)
	• Порча (hexes): has_caustic_toxins (3), has_withering (6), has_soul_harvest (10)
	• Выживание (alchemy): has_herbalist (3), has_thrifty_alchemist (6), has_double_dose (10)
	• Выживание (crafting): has_field_sharpening (3), has_repair_master (6), has_reinforcement (10)
	• Выживание (scavenging): has_keen_eye (3), has_tight_belt (6), has_treasure_sense (10)

5. Критерии приёмки (tests/test_progression.py)

1. Проверка таблицы xp_to_next_level для уровней 1, 2, 10, 19 и возврата None на уровне 20.
2. Проверка ретроактивного пересчёта MaxHP и MaxMP при повышении constitution и wisdom на любом уровне.
3. Проверка стартового ограничения +2 на атрибут при is_creation=True (нельзя поднять стат выше 3, но можно распределить 3 + 2 + 1 или 2 + 2 + 2).
4. Проверка мульти-левелапа за один большой пакет XP (например, +200 XP на 1-м уровне сразу поднимает до 3-го уровня с правильным остатком XP и +2 очками атрибутов/навыков) и остановки на капе 20 уровня.
5. Проверка срабатывания события perk_unlocked ровно на 3, 6 и 10 уровнях навыка.
