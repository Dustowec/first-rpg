"""Загрузчик атомарной JSON-базы данных игрового контента."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class GameData:
    """Рекурсивный загрузчик и индексатор data/**/*.json.

    Проверяет:
    - Уникальность каждого "id" во всей базе.
    - Совпадение имени файла с полем "id" (path.stem == entity["id"]).
    - Ссылочную целостность: все itemId в recipes существуют в items;
      все requiredSkill.id в recipes и spells существуют в skills.
    """

    def __init__(self, data_dir: str) -> None:
        self._data_dir = Path(data_dir)
        self.entities: dict[str, dict[str, Any]] = {}
        self.items: dict[str, dict[str, Any]] = {}
        self.recipes: dict[str, dict[str, Any]] = {}
        self.spells: dict[str, dict[str, Any]] = {}
        self.skills: dict[str, dict[str, Any]] = {}
        self.monsters: dict[str, dict[str, Any]] = {}
        self.biomes: dict[str, dict[str, Any]] = {}
        self.npcs: dict[str, dict[str, Any]] = {}
        self.strings: dict[str, str] = {}
        self._load_all()

    # ------------------------------------------------------------------
    # Загрузка
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        json_files = sorted(self._data_dir.rglob("*.json"))
        if not json_files:
            raise ValueError(f"JSON-файлы не найдены в {self._data_dir}")

        # Особый случай: strings_ru.json (не entity, а flat dict)
        strings_path = self._data_dir / "strings_ru.json"
        if strings_path.exists():
            with open(strings_path, "r", encoding="utf-8") as f:
                self.strings = json.load(f)
            if not isinstance(self.strings, dict):
                raise ValueError("strings_ru.json должен содержать словарь")

        # 1. Загрузка всех JSON entity-файлов
        for path in json_files:
            # Пропускаем strings_ru.json — он уже загружен
            if path.name == "strings_ru.json":
                continue

            with open(path, "r", encoding="utf-8") as f:
                entity = json.load(f)

            entity_id = entity.get("id")
            if entity_id is None:
                raise ValueError(f"Отсутствует 'id' в файле: {path}")

            # 2. Проверка file.stem == entity["id"]
            if path.stem != entity_id:
                raise ValueError(
                    f"Имя файла не совпадает с id: файл={path.stem}, id={entity_id}"
                )

            # 3. Проверка уникальности id
            if entity_id in self.entities:
                raise ValueError(
                    f"Дубликат id: '{entity_id}' (файлы: {self.entities[entity_id].get('_source', '')}, {path})"
                )

            # Добавляем метаданные о источнике
            entity["_source"] = str(path)
            self.entities[entity_id] = entity

            # Индексация по типам
            category = entity.get("category")
            if category == "weapon" or category in ("food", "consumable", "armor", "material", "junk", "repair_kit"):
                self.items[entity_id] = entity
            elif category == "recipe":
                self.recipes[entity_id] = entity
            elif category == "spell":
                self.spells[entity_id] = entity
            elif category == "skill":
                self.skills[entity_id] = entity
            elif category == "monster":
                self.monsters[entity_id] = entity
            elif category == "biome":
                self.biomes[entity_id] = entity
            elif category == "npc":
                self.npcs[entity_id] = entity

        # 4. Проверка ссылочной целостности
        self._check_references()

    def _check_references(self) -> None:
        """Проверяет ссылочную целостность между сущностями."""
        # Проверяем itemId в recipes
        for recipe_id, recipe in self.recipes.items():
            components = recipe.get("ingredients", [])
            for comp in components:
                item_id = comp.get("itemId")
                if item_id and item_id not in self.items:
                    raise ValueError(
                        f"Рецепт '{recipe_id}' ссылается на отсутствующий itemId: '{item_id}'"
                    )

            # Проверяем requiredSkill.id
            required_skill = recipe.get("requiredSkill")
            if required_skill:
                skill_id = required_skill.get("id")
                if skill_id and skill_id not in self.skills:
                    raise ValueError(
                        f"Рецепт '{recipe_id}' ссылается на отсутствующий requiredSkill.id: '{skill_id}'"
                    )

        # Проверяем requiredSkill.id в spells
        for spell_id, spell in self.spells.items():
            required_skill = spell.get("requiredSkill")
            if required_skill:
                skill_id = required_skill.get("id")
                if skill_id and skill_id not in self.skills:
                    raise ValueError(
                        f"Заклинание '{spell_id}' ссылается на отсутствующий requiredSkill.id: '{skill_id}'"
                    )

        # Проверяем lootTable[].itemId у монстров
        for monster_id, monster in self.monsters.items():
            loot_table = monster.get("lootTable", [])
            for loot_entry in loot_table:
                item_id = loot_entry.get("itemId")
                if item_id and item_id not in self.items:
                    raise ValueError(
                        f"Монстр '{monster_id}' ссылается на отсутствующий itemId в lootTable: '{item_id}'"
                    )

        # Проверяем monsterPool[] в биомах
        for biome_id, biome in self.biomes.items():
            monster_pool = biome.get("monsterPool", [])
            for mob_id in monster_pool:
                if mob_id not in self.monsters:
                    raise ValueError(
                        f"Биом '{biome_id}' ссылается на отсутствующий monsterPool: '{mob_id}'"
                    )

        # Проверяем tradeStock[] у NPC
        for npc_id, npc in self.npcs.items():
            trade_stock = npc.get("tradeStock", [])
            for item_id in trade_stock:
                if item_id not in self.items:
                    raise ValueError(
                        f"NPC '{npc_id}' ссылается на отсутствующий tradeStock: '{item_id}'"
                    )

    # ------------------------------------------------------------------
    # Публичные методы доступа
    # ------------------------------------------------------------------

    def get(self, entity_id: str) -> dict[str, Any]:
        """Возвращает сущность по id или выбрасывает KeyError."""
        return self.entities[entity_id]

    def get_item(self, item_id: str) -> dict[str, Any]:
        """Возвращает предмет по id или выбрасывает KeyError."""
        return self.items[item_id]

    def get_recipe(self, recipe_id: str) -> dict[str, Any]:
        """Возвращает рецепт по id или выбрасывает KeyError."""
        return self.recipes[recipe_id]

    def get_spell(self, spell_id: str) -> dict[str, Any]:
        """Возвращает заклинание по id или выбрасывает KeyError."""
        return self.spells[spell_id]

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        """Возвращает навык по id или выбрасывает KeyError."""
        return self.skills[skill_id]

    def list_items(
        self,
        category: str | None = None,
        can_find_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Возвращает список предметов с опциональной фильтрацией.

        Args:
            category: Фильтр по category (например, "weapon", "food").
            can_find_only: Если True, возвращает только предметы с canFind=True.
        """
        result = []
        for item in self.items.values():
            if category is not None and item.get("category") != category:
                continue
            if can_find_only and not item.get("economy", {}).get("canFind", False):
                continue
            result.append(item)
        return result

    # ------------------------------------------------------------------
    # Новые методы доступа для monsters, biomes, npcs, strings
    # ------------------------------------------------------------------

    def get_monster(self, monster_id: str) -> dict[str, Any]:
        """Возвращает монстра по id или выбрасывает KeyError."""
        return self.monsters[monster_id]

    def get_biome(self, biome_id_or_type: str) -> dict[str, Any]:
        """Возвращает биом по id или biomeType или выбрасывает KeyError."""
        # Сначала пытаемся найти по id
        if biome_id_or_type in self.biomes:
            return self.biomes[biome_id_or_type]
        # Затем по biomeType
        for biome in self.biomes.values():
            if biome.get("biomeType") == biome_id_or_type:
                return biome
        raise KeyError(
            f"Биом не найден: '{biome_id_or_type}' (не найден по id или biomeType)"
        )

    def get_npc(self, npc_id: str) -> dict[str, Any]:
        """Возвращает NPC по id или выбрасывает KeyError."""
        return self.npcs[npc_id]

    def t(self, string_id: str, **kwargs) -> str:
        """Форматирует строку из strings_ru.json с подстановкой переменных.

        Args:
            string_id: ID строки в strings_ru.json.
            **kwargs: Переменные для форматирования (например, level=5).

        Returns:
            Отформатированная строка.

        Raises:
            KeyError: Если string_id не найден в strings_ru.json.
        """
        text = self.strings.get(string_id)
        if text is None:
            raise KeyError(f"Строка не найдена: '{string_id}'")
        if kwargs:
            text = text.format(**kwargs)
        return text
