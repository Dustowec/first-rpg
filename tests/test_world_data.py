"""Тесты для Блока 1.3: Атомарная JSON-база (Монстры, Биомы, NPC, строки RU)."""

import json
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

from engine.data_loader import GameData

# Ожидаемые счётчики
EXPECTED_MONSTER_COUNT = 24
EXPECTED_BIOME_COUNT = 9
EXPECTED_NPC_COUNT = 7
EXPECTED_STRINGS_FILE = True


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------


def _count_json_files(directory: Path) -> int:
    """Возвращает количество *.json в directory."""
    return len(list(directory.glob("*.json")))


# ---------------------------------------------------------------------------
# 1. Тесты генерации (количество файлов)
# ---------------------------------------------------------------------------


class TestGenerationCounts:
    def test_monster_count(self):
        monsters_dir = DATA_DIR / "monsters"
        assert monsters_dir.exists(), "Директория data/monsters/ не существует"
        count = _count_json_files(monsters_dir)
        assert count == EXPECTED_MONSTER_COUNT, f"Ожидалось {EXPECTED_MONSTER_COUNT}, получено {count}"

    def test_biome_count(self):
        biomes_dir = DATA_DIR / "biomes"
        assert biomes_dir.exists(), "Директория data/biomes/ не существует"
        count = _count_json_files(biomes_dir)
        assert count == EXPECTED_BIOME_COUNT, f"Ожидалось {EXPECTED_BIOME_COUNT}, получено {count}"

    def test_npc_count(self):
        npcs_dir = DATA_DIR / "npcs"
        assert npcs_dir.exists(), "Директория data/npcs/ не существует"
        count = _count_json_files(npcs_dir)
        assert count == EXPECTED_NPC_COUNT, f"Ожидалось {EXPECTED_NPC_COUNT}, получено {count}"

    def test_strings_file_exists(self):
        strings_path = DATA_DIR / "strings_ru.json"
        assert strings_path.exists(), "Файл data/strings_ru.json не существует"
        with open(strings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict), "strings_ru.json должен содержать словарь"
        assert len(data) > 0, "strings_ru.json должен содержать хотя бы одну строку"


# ---------------------------------------------------------------------------
# 2. Тесты GameData (загрузка новых типов)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gd():
    """Загружает GameData один раз для всех тестов модуля."""
    return GameData(str(DATA_DIR))


class TestGameDataLoading:
    def test_monsters_loaded(self, gd: GameData):
        assert len(gd.monsters) == EXPECTED_MONSTER_COUNT, (
            f"Ожидалось {EXPECTED_MONSTER_COUNT} монстров, получено {len(gd.monsters)}"
        )

    def test_biomes_loaded(self, gd: GameData):
        assert len(gd.biomes) == EXPECTED_BIOME_COUNT, (
            f"Ожидалось {EXPECTED_BIOME_COUNT} биомов, получено {len(gd.biomes)}"
        )

    def test_npcs_loaded(self, gd: GameData):
        assert len(gd.npcs) == EXPECTED_NPC_COUNT, (
            f"Ожидалось {EXPECTED_NPC_COUNT} NPC, получено {len(gd.npcs)}"
        )

    def test_strings_loaded(self, gd: GameData):
        assert isinstance(gd.strings, dict), "strings должен быть словарём"
        assert len(gd.strings) > 0, "strings должен содержать хотя бы одну строку"

    def test_full_integrity(self, gd: GameData):
        """GameData('data') проходит все проверки ссылочной целостности."""
        assert len(gd.entities) > 0, "entities должен быть не пустым"
        assert len(gd.monsters) == EXPECTED_MONSTER_COUNT
        assert len(gd.biomes) == EXPECTED_BIOME_COUNT
        assert len(gd.npcs) == EXPECTED_NPC_COUNT

    def test_monster_filename_matches_id(self, gd: GameData):
        for monster_id, monster in gd.monsters.items():
            source = monster.get("_source", "")
            stem = Path(source).stem
            assert stem == monster_id, f"Несоответствие: файл={stem}, id={monster_id}"

    def test_biome_filename_matches_id(self, gd: GameData):
        for biome_id, biome in gd.biomes.items():
            source = biome.get("_source", "")
            stem = Path(source).stem
            assert stem == biome_id, f"Несоответствие: файл={stem}, id={biome_id}"

    def test_npc_filename_matches_id(self, gd: GameData):
        for npc_id, npc in gd.npcs.items():
            source = npc.get("_source", "")
            stem = Path(source).stem
            assert stem == npc_id, f"Несоответствие: файл={stem}, id={npc_id}"


# ---------------------------------------------------------------------------
# 3. Тесты методов доступа (getter methods)
# ---------------------------------------------------------------------------


class TestGetterMethods:
    def test_get_monster(self, gd: GameData):
        monster = gd.get_monster("mob_rat_giant")
        assert monster["id"] == "mob_rat_giant"
        assert monster["tier"] == 1
        assert monster["type"] == "beast"

    def test_get_biome_by_id(self, gd: GameData):
        biome = gd.get_biome("biome_village")
        assert biome["id"] == "biome_village"
        assert biome["biomeType"] == "village"

    def test_get_biome_by_type(self, gd: GameData):
        biome = gd.get_biome("village")
        assert biome["biomeType"] == "village"
        assert biome["id"] == "biome_village"

    def test_get_biome_raises_keyerror(self, gd: GameData):
        with pytest.raises(KeyError):
            gd.get_biome("nonexistent_biome_xyz")

    def test_get_npc(self, gd: GameData):
        npc = gd.get_npc("npc_elder_miroslav")
        assert npc["id"] == "npc_elder_miroslav"
        assert npc["role"] == "elder"

    def test_t_function(self, gd: GameData):
        text = gd.t("system_death_message")
        assert isinstance(text, str)
        assert len(text) > 0

    def test_t_function_with_formatting(self, gd: GameData):
        text = gd.t("status_level_up", level=5)
        assert "5" in text

    def test_t_function_raises_keyerror(self, gd: GameData):
        with pytest.raises(KeyError):
            gd.t("nonexistent_string_id_xyz")


# ---------------------------------------------------------------------------
# 4. Тесты данных (конкретные значения)
# ---------------------------------------------------------------------------


class TestDataValues:
    def test_innkeeper_rest_cost(self, gd: GameData):
        npc = gd.get_npc("npc_innkeeper_boris")
        assert npc.get("restCost") == 5, f"restCost должен быть 5, получено {npc.get('restCost')}"
        assert "rest" in npc.get("services", []), "services должен содержать 'rest'"

    def test_monster_tier_distribution(self, gd: GameData):
        tiers = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for monster in gd.monsters.values():
            tier = monster.get("tier")
            if tier in tiers:
                tiers[tier] += 1
        assert tiers[1] == 5, f"Tier 1: ожидалось 5, получено {tiers[1]}"
        assert tiers[2] == 5, f"Tier 2: ожидалось 5, получено {tiers[2]}"
        assert tiers[3] == 5, f"Tier 3: ожидалось 5, получено {tiers[3]}"
        assert tiers[4] == 5, f"Tier 4: ожидалось 5, получено {tiers[4]}"
        assert tiers[5] == 4, f"Tier 5: ожидалось 4, получено {tiers[5]}"

    def test_elite_monster(self, gd: GameData):
        wolf_alpha = gd.get_monster("mob_wolf_alpha")
        assert wolf_alpha.get("isElite") is True, "mob_wolf_alpha должен быть elite"

    def test_boss_monster(self, gd: GameData):
        troll_hill = gd.get_monster("mob_troll_hill")
        assert troll_hill.get("isBoss") is True, "mob_troll_hill должен быть boss"

    def test_special_traits_regengeneration(self, gd: GameData):
        troll_hill = gd.get_monster("mob_troll_hill")
        traits = troll_hill.get("specialTraits", {})
        assert traits.get("regenHp") == 1, "regenHp должен быть 1"
        assert traits.get("regenIntervalRounds") == 2, "regenIntervalRounds должен быть 2"

    def test_special_traits_ignore_armor(self, gd: GameData):
        wraith = gd.get_monster("mob_wraith")
        traits = wraith.get("specialTraits", {})
        assert traits.get("ignoreArmorRatio") == 0.5, "ignoreArmorRatio должен быть 0.5"

    def test_special_traits_dot(self, gd: GameData):
        spider = gd.get_monster("mob_spider_giant")
        traits = spider.get("specialTraits", {})
        dot = traits.get("onHitDot", {})
        assert dot.get("type") == "poison"
        assert dot.get("chance") == 0.25
        assert dot.get("hpDeltaPerTurn") == -1
        assert dot.get("ticks") == 3

    def test_affinities(self, gd: GameData):
        wraith = gd.get_monster("mob_wraith")
        affinities = wraith.get("affinities", {})
        assert affinities.get("slashing") == 0.5, "wraith slashing affinity должен быть 0.5"
        assert affinities.get("piercing") == 0.5, "wraith piercing affinity должен быть 0.5"

    def test_biome_monster_pool_valid(self, gd: GameData):
        """Все monsterPool в биомах содержат валидных монстров."""
        for biome_id, biome in gd.biomes.items():
            for mob_id in biome.get("monsterPool", []):
                assert mob_id in gd.monsters, (
                    f"Биом '{biome_id}' ссылается на отсутствующего монстра: '{mob_id}'"
                )

    def test_npc_trade_stock_valid(self, gd: GameData):
        """Все tradeStock у NPC содержат валидные предметы."""
        for npc_id, npc in gd.npcs.items():
            for item_id in npc.get("tradeStock", []):
                assert item_id in gd.items, (
                    f"NPC '{npc_id}' ссылается на отсутствующий предмет: '{item_id}'"
                )

    def test_monster_loot_table_valid(self, gd: GameData):
        """Все lootTable у монстров содержат валидные предметы."""
        for monster_id, monster in gd.monsters.items():
            for loot_entry in monster.get("lootTable", []):
                item_id = loot_entry.get("itemId")
                assert item_id in gd.items, (
                    f"Монстр '{monster_id}' ссылается на отсутствующий предмет в lootTable: '{item_id}'"
                )

    def test_all_monsters_have_bilingual_names(self, gd: GameData):
        for monster_id, monster in gd.monsters.items():
            name = monster.get("name", {})
            assert "en" in name and "ru" in name, f"{monster_id}: отсутствует name.en/ru"

    def test_all_biomes_have_bilingual_names(self, gd: GameData):
        for biome_id, biome in gd.biomes.items():
            name = biome.get("name", {})
            assert "en" in name and "ru" in name, f"{biome_id}: отсутствует name.en/ru"

    def test_all_npcs_have_bilingual_names(self, gd: GameData):
        for npc_id, npc in gd.npcs.items():
            name = npc.get("name", {})
            assert "en" in name and "ru" in name, f"{npc_id}: отсутствует name.en/ru"


# ---------------------------------------------------------------------------
# 5. Тесты ссылочной целостности (битые ссылки)
# ---------------------------------------------------------------------------


class TestReferenceIntegrity:
    def test_broken_monster_loot_raises_valueerror(self, tmp_path: Path):
        """Битая ссылка в lootTable монстра вызывает ValueError."""
        # Создаём монстра с битой ссылкой
        (tmp_path / "mob_bad.json").write_text(
            json.dumps({
                "id": "mob_bad",
                "category": "monster",
                "tier": 1,
                "type": "beast",
                "name": {"en": "Bad", "ru": "Плохой"},
                "hp": 5,
                "dmg": {"min": 1, "max": 2, "type": "blunt"},
                "def": 0,
                "acc": 40,
                "eva": 0,
                "xp": 10,
                "gold": {"min": 0, "max": 1},
                "lootTable": [{"itemId": "item_missing", "chance": 0.5}],
                "affinities": {},
                "specialTraits": {},
                "isElite": False,
                "isBoss": False,
            }),
            encoding="utf-8",
        )
        # Создаём минимальный предмет для items
        (tmp_path / "item_dummy.json").write_text(
            json.dumps({
                "id": "item_dummy",
                "category": "weapon",
                "subCategory": "blunt",
                "name": {"en": "Dummy", "ru": "Дамми"},
                "description": {"en": "", "ru": ""},
                "economy": {"buyPrice": 1, "sellPrice": 0, "canBuy": False, "canFind": False},
                "stats": {},
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            GameData(str(tmp_path))

    def test_broken_biome_pool_raises_valueerror(self, tmp_path: Path):
        """Битая ссылка в monsterPool биома вызывает ValueError."""
        # Создаём биом с битой ссылкой
        (tmp_path / "biome_bad.json").write_text(
            json.dumps({
                "id": "biome_bad",
                "category": "biome",
                "biomeType": "test",
                "name": {"en": "Bad", "ru": "Плохой"},
                "description": {"en": "", "ru": ""},
                "pSpawn": 0.1,
                "canSearch": True,
                "searchWeightShifts": {},
                "preferredItems": [],
                "monsterPool": ["mob_missing"],
                "services": [],
                "namePool": {"adjectives": {"en": [], "ru": []}, "nouns": {"en": [], "ru": []}},
            }),
            encoding="utf-8",
        )
        # Создаём минимального монстра
        (tmp_path / "mob_dummy.json").write_text(
            json.dumps({
                "id": "mob_dummy",
                "category": "monster",
                "tier": 1,
                "type": "beast",
                "name": {"en": "Dummy", "ru": "Дамми"},
                "hp": 5,
                "dmg": {"min": 1, "max": 2, "type": "blunt"},
                "def": 0,
                "acc": 40,
                "eva": 0,
                "xp": 10,
                "gold": {"min": 0, "max": 1},
                "lootTable": [],
                "affinities": {},
                "specialTraits": {},
                "isElite": False,
                "isBoss": False,
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            GameData(str(tmp_path))

    def test_broken_npc_trade_stock_raises_valueerror(self, tmp_path: Path):
        """Битая ссылка в tradeStock NPC вызывает ValueError."""
        # Создаём NPC с битой ссылкой
        (tmp_path / "npc_bad.json").write_text(
            json.dumps({
                "id": "npc_bad",
                "category": "npc",
                "role": "merchant",
                "locationType": "village",
                "name": {"en": "Bad", "ru": "Плохой"},
                "description": {"en": "", "ru": ""},
                "initialReputation": "neutral",
                "actionWhitelist": ["none"],
                "services": [],
                "tradeStock": ["item_missing"],
                "restCost": None,
                "personality": {"ru": ""},
                "fallbackReplies": {},
            }),
            encoding="utf-8",
        )
        # Создаём минимальный предмет
        (tmp_path / "item_dummy.json").write_text(
            json.dumps({
                "id": "item_dummy",
                "category": "weapon",
                "subCategory": "blunt",
                "name": {"en": "Dummy", "ru": "Дамми"},
                "description": {"en": "", "ru": ""},
                "economy": {"buyPrice": 1, "sellPrice": 0, "canBuy": False, "canFind": False},
                "stats": {},
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            GameData(str(tmp_path))
