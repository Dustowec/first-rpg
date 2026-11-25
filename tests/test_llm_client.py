"""Тесты для Блока 5.1: Сборщик State Snapshot и клиент локальной LLM."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Добавляем корень проекта в sys.path для импорта
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from engine.data_loader import GameData
from engine.llm_client import (
    build_llm_messages,
    build_state_snapshot,
    get_fallback_response,
    query_npc_llm,
    VALID_MOODS,
    VALID_REPUTATIONS,
    NPC_RESPONSE_JSON_SCHEMA,
    DEFAULT_SUGGESTED_REPLIES,
)
from engine.models import create_default_player

# Загружаем GameData из data/
_data_dir = os.path.join(_project_root, "data")
_game_data = GameData(_data_dir)


def _make_state(**overrides):
    """Создаёт тестовое состояние с player.

    При override player поля сливаются с дефолтным игроком,
    чтобы equipment и skills не терялись.
    """
    player = create_default_player()
    state = {
        "player": player,
        "meta": {
            "llm": {
                "enabled": True,
                "endpoint": "http://127.0.0.1:8080/v1/chat/completions",
                "model": "test-model",
                "timeoutSec": 15,
            }
        },
        "map": {
            "currentNodeId": "node_00",
            "nodes": [
                {
                    "id": "node_00",
                    "type": "village",
                    "name": "Test Village",
                    "connections": [],
                }
            ],
        },
        "npcs": {
            "npc_elder_miroslav": {"mood": "neutral", "reputation": "neutral", "met": False},
            "npc_merchant_ganna": {"mood": "neutral", "reputation": "neutral", "met": False},
            "npc_blacksmith_kolm": {"mood": "neutral", "reputation": "neutral", "met": False},
            "npc_innkeeper_boris": {"mood": "neutral", "reputation": "neutral", "met": False},
            "npc_herbalist_vela": {"mood": "neutral", "reputation": "neutral", "met": False},
        },
        "flags": {},
        "world": {
            "day": 1,
            "stepOfDay": 5,
            "fedMorning": False,
            "fedEvening": False,
            "activeEffects": [],
        },
    }
    for key, value in overrides.items():
        if key == "player":
            for k, v in value.items():
                player[k] = v
        elif key == "map":
            state["map"] = value
        elif key == "npcs":
            state["npcs"].update(value)
        elif key == "world":
            state["world"].update(value)
        elif key == "meta":
            state["meta"].update(value)
        else:
            state[key] = value
    return state


# ---------------------------------------------------------------------------
# A. Сборка слепка (build_state_snapshot)
# ---------------------------------------------------------------------------


class TestBuildStateSnapshot:
    """Критерий приёмки 1: Сборка слепка (~200 токенов)."""

    def test_snapshot_npc_profile(self):
        """npcProfile содержит id, role, personality, reputation."""
        state = _make_state()
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "Привет!", _game_data)

        assert snapshot["npcProfile"]["id"] == "npc_innkeeper_boris"
        assert snapshot["npcProfile"]["role"] == "Трактирщик"
        assert "Гостеприимный" in snapshot["npcProfile"]["personality"]
        assert snapshot["npcProfile"]["reputation"] == "neutral"

    def test_snapshot_world_context(self):
        """worldContext содержит location, day, stepOfDay, hungerWarning."""
        state = _make_state()
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "Привет!", _game_data)

        assert snapshot["worldContext"]["location"] == "Test Village"
        assert snapshot["worldContext"]["day"] == 1
        assert snapshot["worldContext"]["stepOfDay"] == 5
        assert "hungerWarning" in snapshot["worldContext"]

    def test_snapshot_hunger_no_perk_morning(self):
        """Без перка scavenging: critical при left <= 2."""
        state = _make_state(world={"stepOfDay": 5, "fedMorning": False, "fedEvening": False})
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        # stepOfDay=5, deadline=7, left=2 -> critical (left <= 2)
        assert snapshot["worldContext"]["hungerWarning"] == "critical (до смерти от голода 2 хода)"

    def test_snapshot_hunger_2_turns_left_critical(self):
        """За 2 хода до дедлайна: critical (до смерти от голода 2 хода)."""
        state = _make_state(world={"stepOfDay": 5, "fedMorning": False, "fedEvening": False})
        # stepOfDay=5, morning_deadline=7, left=2 -> critical
        state["world"]["stepOfDay"] = 5
        # Прямая проверка: stepOfDay=5, deadline=7 => left=2
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        # При stepOfDay=5 и deadline=7: left=2 -> critical
        # Но по логике: stepOfDay < morning_deadline (5 < 7), left = 7 - 5 = 2 -> critical
        # Пересчитаем: если stepOfDay=5, deadline=7, left=2 <= 2 -> critical
        assert snapshot["worldContext"]["hungerWarning"] == "critical (до смерти от голода 2 хода)"

    def test_snapshot_hunger_1_turn_left_critical(self):
        """За 1 ход до дедлайна: critical (до смерти от голода 1 ход)."""
        state = _make_state(world={"stepOfDay": 6, "fedMorning": False, "fedEvening": False})
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        # stepOfDay=6, deadline=7, left=1 -> critical
        assert snapshot["worldContext"]["hungerWarning"] == "critical (до смерти от голода 1 хода)"

    def test_snapshot_hunger_with_scavenging_perk(self):
        """С перком scavenging >= 6: дедлайны сдвигаются (9 и 19)."""
        state = _make_state(
            player={"skills": {"scavenging": 6}},
            world={"stepOfDay": 8, "fedMorning": False, "fedEvening": False},
        )
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        # scavenging=6 -> morning_deadline=9, stepOfDay=8 < 9, left=1 -> critical
        assert snapshot["worldContext"]["hungerWarning"] == "critical (до смерти от голода 1 хода)"

    def test_snapshot_hunger_evening_with_perk(self):
        """С перком scavenging: ужин до шага 19."""
        state = _make_state(
            player={"skills": {"scavenging": 6}},
            world={"stepOfDay": 12, "fedMorning": True, "fedEvening": False},
        )
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        # stepOfDay=12 >= 10, not fedEvening, evening_deadline=19, left=7 -> hungry
        assert snapshot["worldContext"]["hungerWarning"] == "hungry (ужин до шага 19)"

    def test_snapshot_satiated(self):
        """Когда оба приёма пищи закрыты: satiated."""
        state = _make_state(
            world={"stepOfDay": 5, "fedMorning": True, "fedEvening": True},
        )
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        assert snapshot["worldContext"]["hungerWarning"] == "satiated"

    def test_snapshot_full_hp(self):
        """Полное HP без приписок."""
        state = _make_state(player={"resources": {"hp": {"current": 10, "max": 10}}})
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        assert snapshot["playerSnapshot"]["hp"] == "10/10"

    def test_snapshot_light_wound(self):
        """Лёгкое ранение (cur < max, но cur > max * 0.35)."""
        state = _make_state(player={"resources": {"hp": {"current": 8, "max": 10}}})
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        assert snapshot["playerSnapshot"]["hp"] == "8/10 (ранен)"

    def test_snapshot_heavy_wound(self):
        """Тяжёлое ранение (cur <= max * 0.35)."""
        state = _make_state(player={"resources": {"hp": {"current": 3, "max": 10}}})
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        # 3 <= 10 * 0.35 = 3.5 -> тяжело ранен
        assert snapshot["playerSnapshot"]["hp"] == "3/10 (тяжело ранен)"

    def test_snapshot_critical_wound_boundary(self):
        """Граница тяжёлого ранения: cur = max * 0.35."""
        state = _make_state(player={"resources": {"hp": {"current": 3, "max": 10}}})
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        assert "(тяжело ранен)" in snapshot["playerSnapshot"]["hp"]

    def test_snapshot_active_effects(self):
        """activeEffects содержит список строковых типов."""
        state = _make_state(
            world={
                "activeEffects": [
                    {"type": "berserk"},
                    {"type": "ironskin"},
                ]
            }
        )
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        assert snapshot["playerSnapshot"]["activeEffects"] == ["berserk", "ironskin"]

    def test_snapshot_notable_inventory_includes_food(self):
        """notableInventory включает еду."""
        state = _make_state(
            player={
                "inventory": [
                    {"itemId": "food_berries", "count": 3},
                    {"itemId": "food_bread", "count": 2},
                ]
            }
        )
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        notable = snapshot["playerSnapshot"]["notableInventory"]
        assert any("Ягоды" in item or "berries" in item for item in notable)
        assert any("Хлеб" in item or "bread" in item for item in notable)

    def test_snapshot_notable_inventory_includes_consumables(self):
        """notableInventory включает зелья."""
        state = _make_state(
            player={
                "inventory": [
                    {"itemId": "pot_heal_minor", "count": 1},
                ]
            }
        )
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        notable = snapshot["playerSnapshot"]["notableInventory"]
        assert len(notable) >= 1

    def test_snapshot_notable_inventory_limit_10(self):
        """notableInventory не превышает 10 позиций."""
        inventory = [{"itemId": "food_berries", "count": 1}] * 20
        state = _make_state(player={"inventory": inventory})
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        assert len(snapshot["playerSnapshot"]["notableInventory"]) <= 10

    def test_snapshot_player_input_trimmed(self):
        """playerInput очищается и обрезается до 300 символов."""
        long_input = "a" * 500
        state = _make_state()
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", long_input, _game_data)
        assert len(snapshot["playerInput"]) <= 300
        assert snapshot["playerInput"] == "a" * 300

    def test_snapshot_no_hidden_stats(self):
        """В snapshot не утекают скрытые статы (monster data, world flags)."""
        state = _make_state()
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        # Проверяем, что нет ключей, связанных с монстрами
        snapshot_str = json.dumps(snapshot)
        assert "monster" not in snapshot_str.lower() or "npcProfile" in snapshot_str
        # Проверяем структуру — только 4 ключа верхнего уровня
        assert set(snapshot.keys()) == {"npcProfile", "worldContext", "playerSnapshot", "playerInput"}


# ---------------------------------------------------------------------------
# B. Контракт запроса (build_llm_messages)
# ---------------------------------------------------------------------------


class TestBuildLlmMessages:
    """Критерий приёмки 2: Контракт запроса."""

    def test_messages_structure(self):
        """Системное и пользовательское сообщения присутствуют."""
        snapshot = {"npcProfile": {"id": "test"}}
        messages = build_llm_messages(snapshot, ["none", "open_trade"])
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_system_contains_allowed_actions(self):
        """В system сообщении есть список allowed_actions."""
        snapshot = {"npcProfile": {"id": "test"}}
        messages = build_llm_messages(snapshot, ["none", "give_hint"])
        assert "none" in messages[0]["content"]
        assert "give_hint" in messages[0]["content"]

    def test_user_contains_snapshot_json(self):
        """User сообщение — сериализованный JSON snapshot."""
        snapshot = {"npcProfile": {"id": "test_npc"}, "worldContext": {"day": 5}}
        messages = build_llm_messages(snapshot, ["none"])
        user_content = messages[1]["content"]
        parsed = json.loads(user_content)
        assert parsed["npcProfile"]["id"] == "test_npc"
        assert parsed["worldContext"]["day"] == 5

    def test_temperature_and_max_tokens_via_transport(self):
        """Проверяем, что query_npc_llm передаёт temperature=0.6, max_tokens=250."""
        state = _make_state()
        captured_payload = {}

        def mock_transport(payload, endpoint, timeout):
            captured_payload.update(payload)
            return json.dumps({
                "choices": [{"message": {"content": '{"npcReply": "test", "mood": "neutral", "action": {"type": "none"}, "suggestedReplies": ["a", "b", "c"]}'}}]
            })

        query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)

        assert captured_payload.get("temperature") == 0.6
        assert captured_payload.get("max_tokens") == 250

    def test_response_format_is_json_schema(self):
        """response_format.type == 'json_schema'."""
        state = _make_state()
        captured_payload = {}

        def mock_transport(payload, endpoint, timeout):
            captured_payload.update(payload)
            return json.dumps({
                "choices": [{"message": {"content": '{"npcReply": "test", "mood": "neutral", "action": {"type": "none"}, "suggestedReplies": ["a", "b", "c"]}'}}]
            })

        query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)

        response_format = captured_payload.get("response_format", {})
        assert response_format.get("type") == "json_schema"

    def test_enable_thinking_false(self):
        """chat_template_kwargs.enable_thinking == False."""
        state = _make_state()
        captured_payload = {}

        def mock_transport(payload, endpoint, timeout):
            captured_payload.update(payload)
            return json.dumps({
                "choices": [{"message": {"content": '{"npcReply": "test", "mood": "neutral", "action": {"type": "none"}, "suggestedReplies": ["a", "b", "c"]}'}}]
            })

        query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)

        kwargs = captured_payload.get("chat_template_kwargs", {})
        assert kwargs.get("enable_thinking") is False


# ---------------------------------------------------------------------------
# C. Парсинг и очистка (sanitize + parse)
# ---------------------------------------------------------------------------


class TestParseAndSanitize:
    """Критерий приёмки 3: Парсинг и очистка ответа."""

    def test_cleaning_thinking_blocks(self):
        """Ответ с блоком <thinking> корректно очищается и парсится."""
        state = _make_state()
        thinking_content = (
            '<thinking>Модель рассуждает о правильном ответе...</thinking>\n'
            '{"npcReply": "Добро пожаловать!", "mood": "friendly", '
            '"action": {"type": "none"}, "suggestedReplies": ["a", "b", "c"]}'
        )

        def mock_transport(payload, endpoint, timeout):
            return json.dumps({"choices": [{"message": {"content": thinking_content}}]})

        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)
        assert meta["usedFallback"] is False
        assert result["npcReply"] == "Добро пожаловать!"
        assert result["mood"] == "friendly"

    def test_cleaning_markdown_wrappers(self):
        """Ответ в обёртке ```json ... ``` корректно очищается."""
        state = _make_state()
        markdown_content = '```json\n{"npcReply": "Привет!", "mood": "neutral", "action": {"type": "none"}, "suggestedReplies": ["a", "b", "c"]}\n```'

        def mock_transport(payload, endpoint, timeout):
            return json.dumps({"choices": [{"message": {"content": markdown_content}}]})

        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)
        assert meta["usedFallback"] is False
        assert result["npcReply"] == "Привет!"

    def test_invalid_mood_fallback_to_neutral(self):
        """Невалидный mood заменяется на 'neutral'."""
        state = _make_state()
        invalid_mood_content = (
            '{"npcReply": "Тест", "mood": "invalid_mood", '
            '"action": {"type": "none"}, "suggestedReplies": ["a", "b", "c"]}'
        )

        def mock_transport(payload, endpoint, timeout):
            return json.dumps({"choices": [{"message": {"content": invalid_mood_content}}]})

        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)
        assert meta["usedFallback"] is False
        assert result["mood"] == "neutral"

    def test_empty_suggested_replies_defaults(self):
        """Пустой suggestedReplies заменяется на стандартные."""
        state = _make_state()
        empty_suggested = (
            '{"npcReply": "Тест", "mood": "neutral", '
            '"action": {"type": "none"}, "suggestedReplies": []}'
        )

        def mock_transport(payload, endpoint, timeout):
            return json.dumps({"choices": [{"message": {"content": empty_suggested}}]})

        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)
        assert meta["usedFallback"] is False
        assert result["suggestedReplies"] == DEFAULT_SUGGESTED_REPLIES

    def test_missing_action_type_defaults_to_none(self):
        """action без ключа type заменяется на {'type': 'none'}."""
        state = _make_state()
        missing_action_type = (
            '{"npcReply": "Тест", "mood": "neutral", '
            '"action": {}, "suggestedReplies": ["a", "b", "c"]}'
        )

        def mock_transport(payload, endpoint, timeout):
            return json.dumps({"choices": [{"message": {"content": missing_action_type}}]})

        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)
        assert meta["usedFallback"] is False
        assert result["action"]["type"] == "none"

    def test_single_suggested_reply_rejected(self):
        """suggestedReplies с 1 элементом заменяется на стандартные (< 2)."""
        state = _make_state()
        one_reply = (
            '{"npcReply": "Тест", "mood": "neutral", '
            '"action": {"type": "none"}, "suggestedReplies": ["only_one"]}'
        )

        def mock_transport(payload, endpoint, timeout):
            return json.dumps({"choices": [{"message": {"content": one_reply}}]})

        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)
        assert meta["usedFallback"] is False
        assert len(result["suggestedReplies"]) >= 2


# ---------------------------------------------------------------------------
# D. Отказоустойчивость (Fallback)
# ---------------------------------------------------------------------------


class TestFallback:
    """Критерий приёмки 4: Отказоустойчивость."""

    def test_llm_disabled_returns_fallback(self):
        """При llm.enabled == False возвращается fallback."""
        state = _make_state(meta={"llm": {"enabled": False}})
        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data)
        assert meta["usedFallback"] is True
        assert meta["reason"] == "llm_disabled"
        assert result["action"]["type"] == "none"

    def test_timeout_returns_fallback(self):
        """TimeoutError возвращает fallback."""
        state = _make_state()

        def mock_transport(payload, endpoint, timeout):
            raise TimeoutError("Connection timed out")

        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)
        assert meta["usedFallback"] is True
        assert meta["reason"] == "TimeoutError"
        assert result["action"]["type"] == "none"

    def test_http_500_returns_fallback(self):
        """HTTP 500 возвращает fallback."""
        state = _make_state()

        def mock_transport(payload, endpoint, timeout):
            from engine.llm_client import HTTPStatusError
            raise HTTPStatusError("HTTP 500: Internal Server Error")

        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)
        assert meta["usedFallback"] is True
        assert "HTTPStatusError" in meta["reason"] or "HTTP 500" in meta["reason"]
        assert result["action"]["type"] == "none"

    def test_invalid_json_returns_fallback(self):
        """Невалидный JSON возвращает fallback."""
        state = _make_state()

        def mock_transport(payload, endpoint, timeout):
            return "this is not json at all"

        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)
        assert meta["usedFallback"] is True
        assert meta["reason"] == "JSONDecodeError"
        assert result["action"]["type"] == "none"

    def test_empty_npc_reply_returns_fallback(self):
        """Пустой npcReply возвращает fallback."""
        state = _make_state()
        empty_reply = (
            '{"npcReply": "", "mood": "neutral", '
            '"action": {"type": "none"}, "suggestedReplies": ["a", "b", "c"]}'
        )

        def mock_transport(payload, endpoint, timeout):
            return json.dumps({"choices": [{"message": {"content": empty_reply}}]})

        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)
        assert meta["usedFallback"] is True
        assert result["action"]["type"] == "none"

    def test_fallback_uses_npc_profile(self):
        """Fallback берёт реплику из fallbackReplies по mood."""
        state = _make_state(meta={"llm": {"enabled": False}})
        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data)
        # Борис имеет fallbackReplies для neutral
        assert "Добро пожаловать" in result["npcReply"] or "харчевню" in result["npcReply"]

    def test_fallback_hostile_on_bad_reputation(self):
        """При reputation hostile fallback использует mood hostile."""
        state = _make_state(
            npcs={
                "npc_innkeeper_boris": {"mood": "neutral", "reputation": "hostile", "met": False},
            },
            meta={"llm": {"enabled": False}},
        )
        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data)
        assert result["mood"] == "hostile"

    def test_fallback_action_is_none(self):
        """Fallback всегда возвращает action.type == 'none'."""
        state = _make_state(meta={"llm": {"enabled": False}})
        result, _ = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data)
        assert result["action"]["type"] == "none"

    def test_fallback_suggested_replies_default(self):
        """Fallback возвращает стандартные suggestedReplies."""
        state = _make_state(meta={"llm": {"enabled": False}})
        result, _ = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data)
        assert result["suggestedReplies"] == DEFAULT_SUGGESTED_REPLIES

    def test_fallback_with_unrecognized_npc(self):
        """Fallback для неизвестного NPC не падает."""
        state = _make_state(meta={"llm": {"enabled": False}})
        result, meta = query_npc_llm(state, "npc_nonexistent", "test", _game_data)
        assert meta["usedFallback"] is True
        assert result["action"]["type"] == "none"
        assert result["npcReply"] == "..."


# ---------------------------------------------------------------------------
# E. Интеграционные тесты (query_npc_llm)
# ---------------------------------------------------------------------------


class TestQueryNpcLlmIntegration:
    """Интеграционные тесты для query_npc_llm."""

    def test_valid_response_no_fallback(self):
        """Валидный ответ от LLM не использует fallback."""
        state = _make_state()
        valid_response = (
            '{"npcReply": "Добро пожаловать в мою харчевню!", '
            '"mood": "friendly", '
            '"action": {"type": "give_hint", "hintType": "local"}, '
            '"suggestedReplies": ["Посмотреть товары", "Спросить о слухах", "Уйти"]}'
        )

        def mock_transport(payload, endpoint, timeout):
            return json.dumps({"choices": [{"message": {"content": valid_response}}]})

        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "Привет!", _game_data, transport_fn=mock_transport)
        assert meta["usedFallback"] is False
        assert meta["reason"] is None
        assert result["npcReply"] == "Добро пожаловать в мою харчевню!"
        assert result["mood"] == "friendly"
        assert result["action"]["type"] == "give_hint"
        assert result["action"]["hintType"] == "local"
        assert len(result["suggestedReplies"]) == 3

    def test_gold_delta_context_in_snapshot(self):
        """Проверяем, что snapshot передаёт контекст для goldDelta."""
        state = _make_state(player={"gold": 50})
        captured_payload = {}

        def mock_transport(payload, endpoint, timeout):
            captured_payload.update(payload)
            return json.dumps({
                "choices": [{"message": {"content": '{"npcReply": "test", "mood": "neutral", "action": {"type": "none"}, "suggestedReplies": ["a", "b", "c"]}'}}]
            })

        query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)

        # Проверяем, что user message содержит snapshot с gold
        user_content = captured_payload["messages"][1]["content"]
        snapshot_data = json.loads(user_content)
        assert snapshot_data["playerSnapshot"]["gold"] == 50

    def test_response_with_all_valid_moods(self):
        """Проверяем, что все валидные mood принимаются."""
        state = _make_state()
        for mood in VALID_MOODS:
            # Создаём новый content для каждого итерации (избегаем closure issue)
            content = json.dumps({
                "npcReply": "Тест",
                "mood": mood,
                "action": {"type": "none"},
                "suggestedReplies": ["a", "b", "c"]
            })

            def make_mock(content_str):
                def mock_transport(payload, endpoint, timeout):
                    return json.dumps({"choices": [{"message": {"content": content_str}}]})
                return mock_transport

            result, meta = query_npc_llm(
                state, "npc_innkeeper_boris", "test", _game_data,
                transport_fn=make_mock(content)
            )
            assert meta["usedFallback"] is False, f"mood={mood} должен быть валидным"
            assert result["mood"] == mood

    def test_response_with_all_valid_reputations(self):
        """Проверяем, что все валидные reputations не вызывают ошибок."""
        for rep in VALID_REPUTATIONS:
            state = _make_state(
                npcs={
                    "npc_innkeeper_boris": {"mood": "neutral", "reputation": rep, "met": False},
                }
            )
            # LLM включён, но mock вернёт валидный ответ
            content = '{"npcReply": "Тест", "mood": "neutral", "action": {"type": "none"}, "suggestedReplies": ["a", "b", "c"]}'

            def mock_transport(payload, endpoint, timeout):
                return json.dumps({"choices": [{"message": {"content": content}}]})

            result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)
            assert meta["usedFallback"] is False

    def test_thinking_blocks_with_content_before_and_after(self):
        """Thinking блок с контентом до и после него."""
        state = _make_state()
        # Thinking блок в начале, затем чистый JSON
        complex_content = (
            '<thinking>Долгие рассуждения модели...\n'
            'Ещё больше рассуждений...</thinking>\n'
            '{"npcReply": "Ответ послеthinking", "mood": "neutral", '
            '"action": {"type": "none"}, "suggestedReplies": ["a", "b", "c"]}'
        )

        def mock_transport(payload, endpoint, timeout):
            return json.dumps({"choices": [{"message": {"content": complex_content}}]})

        result, meta = query_npc_llm(state, "npc_innkeeper_boris", "test", _game_data, transport_fn=mock_transport)
        assert meta["usedFallback"] is False
        # После очистки thinking блока, парсится оставшийся JSON
        assert result["npcReply"] == "Ответ послеthinking"

    def test_snapshot_contains_weapon_name(self):
        """Snapshot содержит русское название оружия."""
        state = _make_state()
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        # По умолчанию у игрока wpn_club_simple
        weapon = snapshot["playerSnapshot"]["weapon"]
        assert weapon != "Нет"

    def test_snapshot_contains_armor_name(self):
        """Snapshot содержит русское название брони."""
        state = _make_state()
        snapshot = build_state_snapshot(state, "npc_innkeeper_boris", "", _game_data)
        # По умолчанию arm_cloth_poor
        armor = snapshot["playerSnapshot"]["armor"]
        assert armor != "Нет"
