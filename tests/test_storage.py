"""Тесты для Блока 1.1: storage, models, constants."""

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from engine.constants import (
    SCHEMA_VERSION,
    DEFAULT_DIFFICULTY,
    DIFFICULTY_MULTIPLIERS,
    ATTRIBUTES,
    SKILLS,
    ATTR_MIN,
    ATTR_MAX,
    SKILL_MIN,
    SKILL_MAX,
    LEVEL_MIN,
    LEVEL_MAX,
)
from engine.models import create_default_player, create_initial_state, validate_state
from engine.storage import (
    save_state,
    new_game,
    load_state,
    handle_player_death,
)


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Возвращает временную директорию для тестов."""
    return tmp_path


@pytest.fixture
def template_path(tmp_dir: Path) -> str:
    """Создаёт state_template.json во временной директории."""
    state = create_initial_state(seed=20260101, difficulty="normal")
    path = str(tmp_dir / "state_template.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return path


@pytest.fixture
def session_path(tmp_dir: Path) -> str:
    """Возвращает путь для сессии."""
    return str(tmp_dir / "state_session.json")


@pytest.fixture
def valid_state(template_path: str) -> dict:
    """Возвращает валидный state, загруженный из шаблона."""
    with open(template_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. Генерация эталонного state и прохождение validate_state()
# ---------------------------------------------------------------------------


class TestCreateDefaultPlayer:
    def test_player_structure(self):
        player = create_default_player()
        assert player["id"] == "player_default"
        assert player["level"] == 1
        assert player["xp"] == 0
        assert player["gold"] == 15
        assert player["unspentPoints"]["attributes"] == 3
        assert player["unspentPoints"]["skills"] == 0
        assert player["resources"]["hp"]["current"] == 10
        assert player["resources"]["hp"]["max"] == 10
        assert player["resources"]["mp"]["current"] == 2
        assert player["resources"]["mp"]["max"] == 2

    def test_all_attributes_present(self):
        player = create_default_player()
        for attr in ATTRIBUTES:
            assert attr in player["attributes"]
            assert player["attributes"][attr] == 1

    def test_all_skills_present(self):
        player = create_default_player()
        for skill in SKILLS:
            assert skill in player["skills"]
            assert player["skills"][skill] == 0

    def test_equipment(self):
        player = create_default_player()
        assert player["equipment"]["weapon"]["itemId"] == "wpn_club_simple"
        assert player["equipment"]["weapon"]["durability"]["current"] == 15
        assert player["equipment"]["armor"]["itemId"] == "arm_cloth_poor"
        assert player["equipment"]["armor"]["durability"]["current"] == 15

    def test_inventory(self):
        player = create_default_player()
        assert len(player["inventory"]) == 3
        ids = [item["itemId"] for item in player["inventory"]]
        assert "food_berries" in ids
        assert "food_bread" in ids
        assert "pot_heal_minor" in ids


class TestCreateInitialState:
    def test_template_created(self, tmp_dir: Path):
        path = str(tmp_dir / "state_template.json")
        state = create_initial_state(template_path_override=path)
        assert os.path.exists(path)

    def test_state_structure(self):
        state = create_initial_state()
        assert state["schemaVersion"] == SCHEMA_VERSION
        assert state["meta"]["seed"] == 20260101
        assert state["meta"]["region"] == 1
        assert state["meta"]["difficulty"] == DEFAULT_DIFFICULTY
        assert state["meta"]["difficultyMultiplier"] == 1.0
        assert state["meta"]["xpRate"] == 1.0

    def test_validate_passes(self):
        state = create_initial_state()
        validate_state(state)  # не должен выбросить


# ---------------------------------------------------------------------------
# 2. Отказ validate_state() при ошибках
# ---------------------------------------------------------------------------


class TestValidateStateFailures:
    def test_missing_top_level_key(self):
        state = create_initial_state()
        del state["meta"]
        with pytest.raises(ValueError, match="Отсутствует обязательный ключ"):
            validate_state(state)

    def test_wrong_schema_version(self):
        state = create_initial_state()
        state["schemaVersion"] = 2
        with pytest.raises(ValueError, match="Неподдерживаемая версия схемы"):
            validate_state(state)

    def test_attribute_out_of_range_low(self):
        state = create_initial_state()
        state["player"]["attributes"]["strength"] = 0
        with pytest.raises(ValueError, match="вне диапазона"):
            validate_state(state)

    def test_attribute_out_of_range_high(self):
        state = create_initial_state()
        state["player"]["attributes"]["wisdom"] = 11
        with pytest.raises(ValueError, match="вне диапазона"):
            validate_state(state)

    def test_skill_out_of_range(self):
        state = create_initial_state()
        state["player"]["skills"]["melee_heavy"] = 11
        with pytest.raises(ValueError, match="вне диапазона"):
            validate_state(state)

    def test_skill_negative(self):
        state = create_initial_state()
        state["player"]["skills"]["alchemy"] = -1
        with pytest.raises(ValueError, match="вне диапазона"):
            validate_state(state)

    def test_level_too_low(self):
        state = create_initial_state()
        state["player"]["level"] = 0
        with pytest.raises(ValueError, match="вне диапазона"):
            validate_state(state)

    def test_level_too_high(self):
        state = create_initial_state()
        state["player"]["level"] = 21
        with pytest.raises(ValueError, match="вне диапазона"):
            validate_state(state)

    def test_missing_attribute(self):
        state = create_initial_state()
        del state["player"]["attributes"]["agility"]
        with pytest.raises(ValueError, match="Отсутствует атрибут"):
            validate_state(state)

    def test_missing_skill(self):
        state = create_initial_state()
        del state["player"]["skills"]["crafting"]
        with pytest.raises(ValueError, match="Отсутствует навык"):
            validate_state(state)

    def test_invalid_current_node_id(self):
        state = create_initial_state()
        state["map"]["currentNodeId"] = "node_99"
        with pytest.raises(ValueError, match="не найден среди узлов"):
            validate_state(state)


# ---------------------------------------------------------------------------
# 3. Атомарное сохранение и загрузка
# ---------------------------------------------------------------------------


class TestSaveAndLoad:
    def test_save_creates_file(self, valid_state: dict, session_path: str):
        save_state(valid_state, session_path)
        assert os.path.exists(session_path)

    def test_no_tmp_file_remaining(self, valid_state: dict, session_path: str):
        save_state(valid_state, session_path)
        tmp = session_path + ".tmp"
        assert not os.path.exists(tmp)

    def test_json_is_valid(self, valid_state: dict, session_path: str):
        save_state(valid_state, session_path)
        with open(session_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["schemaVersion"] == valid_state["schemaVersion"]
        assert loaded["player"]["gold"] == valid_state["player"]["gold"]

    def test_roundtrip_preserves_data(self, valid_state: dict, session_path: str):
        save_state(valid_state, session_path)
        with open(session_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == valid_state


# ---------------------------------------------------------------------------
# 4. Обработка битого JSON
# ---------------------------------------------------------------------------


class TestCorruptedBackup:
    def test_corrupted_json_triggers_backup(
        self, template_path: str, tmp_dir: Path
    ):
        session_path = str(tmp_dir / "state_session.json")

        # Пишем битый JSON
        with open(session_path, "w", encoding="utf-8") as f:
            f.write("{broken json!!!")

        state, events = load_state(
            session_path=session_path, template_path=template_path
        )

        # Событие бекапа
        assert any(e["id"] == "sys_corrupted_backup" for e in events)

        # Бекап-файл создан
        backup_events = [e for e in events if e["id"] == "sys_corrupted_backup"]
        assert len(backup_events) == 1
        backup_path = backup_events[0]["backupPath"]
        assert os.path.exists(backup_path)

        # Новая игра запущена
        assert state["schemaVersion"] == SCHEMA_VERSION
        assert state["meta"]["seed"] == 20260101

    def test_new_game_when_no_session(
        self, template_path: str, tmp_dir: Path
    ):
        session_path = str(tmp_dir / "state_session.json")
        # Файл не существует
        assert not os.path.exists(session_path)

        state, events = load_state(
            session_path=session_path, template_path=template_path
        )

        assert any(e["id"] == "sys_new_game" for e in events)
        assert state["schemaVersion"] == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# 5. Permadeath — handle_player_death и загрузка isDead
# ---------------------------------------------------------------------------


class TestPermadeath:
    def test_handle_player_death(self, valid_state: dict, session_path: str):
        state, events = handle_player_death(
            valid_state, reason="голод", session_path=session_path
        )

        # События
        assert any(e["id"] == "player_died" for e in events)
        assert any(e["id"] == "sys_permadeath_reset" for e in events)

        # Новый state — чистая игра
        assert state["flags"]["isDead"] is False
        assert state["player"]["level"] == 1

    def test_load_state_with_isdead_triggers_reset(
        self, template_path: str, tmp_dir: Path
    ):
        session_path = str(tmp_dir / "state_session.json")

        # Создаём и сохраняем state с isDead=True
        state = create_initial_state()
        state["flags"]["isDead"] = True
        state["flags"]["deathReason"] = "бой"
        save_state(state, session_path)

        # Загрузка должна сбросить
        fresh_state, events = load_state(
            session_path=session_path, template_path=template_path
        )

        assert any(e["id"] == "sys_permadeath_reset" for e in events)
        assert fresh_state["flags"]["isDead"] is False
        assert fresh_state["flags"]["deathReason"] is None


# ---------------------------------------------------------------------------
# 6. Difficulty multipliers
# ---------------------------------------------------------------------------


class TestDifficultyMultipliers:
    @pytest.mark.parametrize(
        "difficulty,expected",
        [
            ("easy", 0.75),
            ("normal", 1.0),
            ("hard", 1.4),
            ("impossible", 2.0),
        ],
    )
    def test_difficulty_multiplier_applied(
        self, difficulty: str, expected: float, tmp_dir: Path
    ):
        session_path = str(tmp_dir / "state_session.json")
        template_path = str(tmp_dir / "state_template.json")

        # Создаём шаблон
        create_initial_state(template_path_override=template_path)

        state = new_game(
            template_path=template_path,
            session_path=session_path,
            difficulty=difficulty,
        )

        assert state["meta"]["difficulty"] == difficulty
        assert state["meta"]["difficultyMultiplier"] == expected

    def test_custom_seed(self, tmp_dir: Path):
        session_path = str(tmp_dir / "state_session.json")
        template_path = str(tmp_dir / "state_template.json")

        create_initial_state(template_path_override=template_path)

        state = new_game(
            template_path=template_path,
            session_path=session_path,
            seed=12345,
        )

        assert state["meta"]["seed"] == 12345
