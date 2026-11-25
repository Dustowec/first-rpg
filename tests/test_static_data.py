"""Тесты для Блока 1.2: атомарная JSON-база (data_loader, build_static_data)."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_static_data.py"

from engine.data_loader import GameData

# Ожидаемые счётчики файлов по директориям
EXPECTED_COUNTS = {
    "weapons": 13,
    "armor": 9,
    "food": 11,
    "materials": 6,
    "consumables": 12,
    "recipes": 12,
    "repair_kits": 3,
    "spells": 9,
    "skills": 9,
    "monsters": 24,
    "biomes": 9,
    "npcs": 7,
}
EXPECTED_TOTAL = sum(EXPECTED_COUNTS.values())  # 124 (84 + 40)
# +1 для strings_ru.json (не учитывается в подпапках, но считается в общем количестве)

# Стартовые предметы
STARTING_ITEMS = [
    "wpn_club_simple",
    "arm_cloth_poor",
    "food_berries",
    "food_bread",
    "pot_heal_minor",
]

# Правильные buyPrice для материалов
EXPECTED_MATERIAL_PRICES = {
    "junk_rags": 1,
    "junk_stone": 1,
    "junk_scrap_metal": 2,
    "junk_broken_hilt": 2,
    "mat_bone": 2,
    "mat_wolf_eye": 3,
}


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _count_json_files(directory: Path) -> dict[str, int]:
    """Возвращает {dir_name: count} для *.json в directory."""
    counts: dict[str, int] = {}
    for p in directory.rglob("*.json"):
        d = p.parent.name
        counts[d] = counts.get(d, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# 1. Build script
# ---------------------------------------------------------------------------


class TestBuildStaticDataScript:
    def test_script_runs(self):
        result = subprocess.run(
            [sys.executable, str(BUILD_SCRIPT)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, result.stderr

    def test_creates_exactly_84_files(self):
        counts = _count_json_files(DATA_DIR)
        total = sum(counts.values())
        # strings_ru.json считается отдельно (не в подпапке)
        expected_with_strings = EXPECTED_TOTAL + 1
        assert total == expected_with_strings, f"Ожидалось {expected_with_strings}, получено {total}"

    def test_file_count_per_category(self):
        counts = _count_json_files(DATA_DIR)
        for dir_name, expected in EXPECTED_COUNTS.items():
            actual = counts.get(dir_name, 0)
            assert actual == expected, f"{dir_name}: ожидалось {expected}, получено {actual}"


# ---------------------------------------------------------------------------
# 2. GameData loading
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gd():
    """Загружает GameData один раз для всех тестов модуля."""
    return GameData(str(DATA_DIR))


class TestGameDataLoading:
    def test_load_all_files(self, gd: GameData):
        assert len(gd.entities) == EXPECTED_TOTAL

    def test_filename_matches_id(self, gd: GameData):
        for entity_id, entity in gd.entities.items():
            source = entity.get("_source", "")
            stem = Path(source).stem
            assert stem == entity_id, f"Несоответствие: файл={stem}, id={entity_id}"

    def test_no_duplicate_ids(self, gd: GameData):
        ids = list(gd.entities.keys())
        assert len(ids) == len(set(ids)), "Обнаружены дубликаты id"

    def test_items_indexed(self, gd: GameData):
        expected_items = sum(
            EXPECTED_COUNTS[d] for d in ("weapons", "armor", "food", "materials", "consumables", "repair_kits")
        )
        assert len(gd.items) == expected_items, f"Ожидалось {expected_items} items, получено {len(gd.items)}"

    def test_recipes_indexed(self, gd: GameData):
        assert len(gd.recipes) == EXPECTED_COUNTS["recipes"]

    def test_spells_indexed(self, gd: GameData):
        assert len(gd.spells) == EXPECTED_COUNTS["spells"]

    def test_skills_indexed(self, gd: GameData):
        assert len(gd.skills) == EXPECTED_COUNTS["skills"]


# ---------------------------------------------------------------------------
# 3. Reference integrity
# ---------------------------------------------------------------------------


class TestReferenceIntegrity:
    def test_duplicate_id_raises_valueerror(self, tmp_path: Path):
        (tmp_path / "a.json").write_text(json.dumps({"id": "dup", "category": "weapon"}), encoding="utf-8")
        (tmp_path / "b.json").write_text(json.dumps({"id": "dup", "category": "weapon"}), encoding="utf-8")
        with pytest.raises(ValueError):
            GameData(str(tmp_path))

    def test_broken_recipe_reference_raises_valueerror(self, tmp_path: Path):
        # Создаём предмет
        (tmp_path / "item_good.json").write_text(
            json.dumps({"id": "item_good", "category": "weapon", "subCategory": "blunt"}),
            encoding="utf-8",
        )
        # Создаём рецепт с битой ссылкой
        (tmp_path / "rec_bad.json").write_text(
            json.dumps({
                "id": "rec_bad",
                "category": "recipe",
                "requiredSkill": {"id": "melee_heavy", "level": 1},
                "ingredients": [{"itemId": "item_missing", "count": 1}],
                "output": {"itemId": "item_good", "count": 1},
                "station": "any",
            }),
            encoding="utf-8",
        )
        # Создаём навык
        (tmp_path / "skill_ms.json").write_text(
            json.dumps({
                "id": "melee_heavy",
                "category": "skill",
                "name": {"en": "Melee Heavy", "ru": "Тяжёлый бой"},
                "description": {"en": "", "ru": ""},
                "milestones": {},
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            GameData(str(tmp_path))

    def test_broken_skill_reference_raises_valueerror(self, tmp_path: Path):
        (tmp_path / "rec_bad.json").write_text(
            json.dumps({
                "id": "rec_bad",
                "category": "recipe",
                "requiredSkill": {"id": "nonexistent_skill", "level": 1},
                "ingredients": [],
                "output": {"itemId": "x", "count": 1},
                "station": "any",
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            GameData(str(tmp_path))

    def test_valid_references_pass(self, gd: GameData):
        """Реальная data/ должна загружаться без ошибок."""
        assert len(gd.entities) == EXPECTED_TOTAL


# ---------------------------------------------------------------------------
# 4. Starting items
# ---------------------------------------------------------------------------


class TestStartingItems:
    def test_starting_items_available(self, gd: GameData):
        for item_id in STARTING_ITEMS:
            item = gd.get_item(item_id)
            assert item["id"] == item_id, f"Предмет {item_id} не найден"


# ---------------------------------------------------------------------------
# 5. Public API
# ---------------------------------------------------------------------------


class TestGameDataPublicAPI:
    def test_get_returns_entity(self, gd: GameData):
        entity = gd.get("wpn_sword_steel")
        assert entity["id"] == "wpn_sword_steel"

    def test_get_raises_keyerror(self, gd: GameData):
        with pytest.raises(KeyError):
            gd.get("nonexistent_id_xyz")

    def test_get_item_returns_item(self, gd: GameData):
        item = gd.get_item("pot_heal_minor")
        assert item["category"] == "consumable"

    def test_get_recipe_returns_recipe(self, gd: GameData):
        recipe = gd.get_recipe("rec_pot_heal_minor")
        assert recipe["category"] == "recipe"

    def test_get_spell_returns_spell(self, gd: GameData):
        spell = gd.get_spell("spl_fireball")
        assert spell["category"] == "spell"

    def test_get_skill_returns_skill(self, gd: GameData):
        skill = gd.get_skill("melee_heavy")
        assert skill["category"] == "skill"

    def test_list_items_filters_by_category(self, gd: GameData):
        weapons = gd.list_items(category="weapon")
        assert all(w["category"] == "weapon" for w in weapons)
        assert len(weapons) == EXPECTED_COUNTS["weapons"]

    def test_list_items_filters_by_can_find(self, gd: GameData):
        findable = gd.list_items(can_find_only=True)
        assert all(item.get("economy", {}).get("canFind") for item in findable)

    def test_list_items_no_filter(self, gd: GameData):
        all_items = gd.list_items()
        assert len(all_items) == len(gd.items)


# ---------------------------------------------------------------------------
# 6. Bilingual fields
# ---------------------------------------------------------------------------


class TestBilingualFields:
    def test_all_entities_have_en_ru_name(self, gd: GameData):
        for eid, ent in gd.entities.items():
            name = ent.get("name", {})
            assert "en" in name and "ru" in name, f"{eid}: отсутствует name.en/ru"
            assert name["en"], f"{eid}: name.en пустой"
            assert name["ru"], f"{eid}: name.ru пустой"

    def test_all_entities_have_en_ru_description(self, gd: GameData):
        for eid, ent in gd.entities.items():
            desc = ent.get("description", {})
            assert "en" in desc and "ru" in desc, f"{eid}: отсутствует description.en/ru"


# ---------------------------------------------------------------------------
# 7. Economy block
# ---------------------------------------------------------------------------


class TestEconomyBlock:
    def test_all_items_have_economy(self, gd: GameData):
        for eid, item in gd.items.items():
            eco = item.get("economy")
            assert eco is not None, f"{eid}: отсутствует economy"
            assert "buyPrice" in eco
            assert "sellPrice" in eco
            assert "canBuy" in eco
            assert "canFind" in eco

    def test_material_economy_values(self, gd: GameData):
        for mat_id, expected_price in EXPECTED_MATERIAL_PRICES.items():
            item = gd.get_item(mat_id)
            actual = item.get("economy", {}).get("buyPrice")
            assert actual == expected_price, f"{mat_id}: buyPrice={actual}, ожидалось {expected_price}"
