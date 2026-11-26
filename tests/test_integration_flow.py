"""Сквозные интеграционные тесты Блока 5.3 (dispatch_command + рендер CLI)."""

import copy
import json
import random
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from cli import app
from engine.controller import dispatch_command
from engine.data_loader import GameData
from engine.storage import new_game
from scripts.generate_template import generate_template

GD = GameData(str(_root / "data"))
BORIS = "npc_innkeeper_boris"


@pytest.fixture()
def paths(tmp_path):
    template = tmp_path / "state_template.json"
    session = tmp_path / "state_session.json"
    generate_template(template)
    return str(session), str(template)


def _start(paths, seed=20260101):
    session, template = paths
    return new_game(template_path=template, session_path=session, seed=seed)


def _cmd(state, command, paths, rng=None, transport=None):
    session, template = paths
    return dispatch_command(
        state, command, GD, rng=rng if rng is not None else random.Random(20260101),
        session_path=session, template_path=template, llm_transport_fn=transport,
    )


def _ids(events):
    return [e["id"] for e in events]


def _session(paths):
    with open(paths[0], encoding="utf-8") as f:
        return json.load(f)


def _first_exit(state, searchable=True):
    node = app.current_node(state)
    for node_id in node.get("connections", []):
        target = app.node_by_id(state, node_id)
        if not searchable or GD.get_biome(target["type"]).get("canSearch", False):
            return node_id
    return node.get("connections", [None])[0]


def _buff_player(state, level=6, strength=6, skill=6, hp=40):
    player = state["player"]
    player["level"] = level
    player["attributes"]["strength"] = strength
    player["skills"]["melee_heavy"] = skill
    player["resources"]["hp"] = {"current": hp, "max": hp}
    player["unspentPoints"]["attributes"] = 0
    return state


def _put_monster(state, node_id, mob_id="mob_ghoul"):
    node = app.node_by_id(state, node_id)
    mob = GD.get_monster(mob_id)
    node["state"]["monster"] = {"mobId": mob_id, "revealed": False, "hp": mob["hp"], "maxHp": mob["hp"]}
    node["state"]["spawnRolled"] = True
    return state


def _barter_transport(payload, endpoint, timeout):
    reply = {
        "npcReply": "Ладно, за твою рукоять и пару медяков отдам буханку.",
        "mood": "sympathetic",
        "action": {"type": "barter_offer", "giveItemId": "food_bread",
                   "takeItemId": "junk_broken_hilt", "goldDelta": -2},
        "suggestedReplies": ["Согласиться", "Спросить о слухах", "Уйти"],
    }
    return json.dumps({"choices": [{"message": {"content": json.dumps(reply, ensure_ascii=False)}}]}, ensure_ascii=False)


def _fight_to_end(state, paths, rng, limit=80):
    events_all = []
    for _ in range(limit):
        if not state["world"].get("inCombat"):
            break
        state, events = _cmd(state, {"type": "combat_attack"}, paths, rng)
        events_all.extend(events)
        if any(e["id"] == "player_died" for e in events):
            break
    return state, events_all


# --- 1. Выживание, автосейв и смерть от голода ---

def test_survival_autosave_and_starvation_permadeath(paths):
    state = _start(paths)
    rng = random.Random(2)  # сид без засады на первом переходе
    assert state["map"]["currentNodeId"] == "node_00"
    assert _session(paths)["map"]["currentNodeId"] == "node_00"

    target = _first_exit(state)
    state, events = _cmd(state, {"type": "move", "targetNodeId": target}, paths, rng)
    assert "moved_to_node" in _ids(events)
    assert not state["world"]["inCombat"]
    assert _session(paths)["map"]["currentNodeId"] == target

    state, events = _cmd(state, {"type": "search"}, paths, rng)
    assert not any(e.startswith("err_") for e in _ids(events))
    saved = _session(paths)
    assert saved["world"]["stepOfDay"] == state["world"]["stepOfDay"] == 3

    steps_seen = [saved["world"]["stepOfDay"]]
    died = False
    for _ in range(10):
        state, events = _cmd(state, {"type": "wait"}, paths, rng)
        if "player_died" in _ids(events):
            died = True
            assert "session_reset_permadeath" in _ids(events)
            assert any(e.get("reason") == "starvation_morning" for e in events if e["id"] == "player_died")
            break
        steps_seen.append(_session(paths)["world"]["stepOfDay"])

    assert died, "голод должен убить на шаге 7"
    assert steps_seen == [3, 4, 5, 6], "автосейв после каждого шага"
    assert state["world"]["day"] == 1 and state["world"]["stepOfDay"] == 1
    assert state["map"]["currentNodeId"] == "node_00"
    fresh = _session(paths)
    assert fresh["world"]["stepOfDay"] == 1 and fresh["player"]["gold"] == 15


def test_error_command_does_not_autosave(paths):
    state = _start(paths)
    before = _session(paths)
    state, events = _cmd(state, {"type": "teleport_to_moon"}, paths)
    assert _ids(events) == ["err_unknown_command"]
    assert _session(paths) == before


# --- 2. Боевой цикл, лут и маскировка скрытых статов ---

def test_combat_cycle_rewards_and_hidden_stats(paths):
    state = _start(paths)
    rng = random.Random(4242)
    target = _first_exit(state)
    state, _ = _cmd(state, {"type": "move", "targetNodeId": target}, paths, rng)
    state = _buff_player(state)
    state = _put_monster(state, target, "mob_ghoul")
    state["world"]["fedMorning"] = True

    state, events = _cmd(state, {"type": "look"}, paths, rng)
    assert app.node_by_id(state, target)["state"]["monster"]["revealed"] is True

    state, events = _cmd(state, {"type": "start_combat"}, paths, rng)
    assert "combat_started" in _ids(events)
    assert state["world"]["inCombat"] is True

    body = app.render_combat_body(state, GD)
    mob = GD.get_monster("mob_ghoul")
    assert "[HP " in body and "#" in body and "Гуль" in body
    # Строка раунда — открытая информация, из проверки скрытых статов её исключаем
    body_without_round = body.replace(f"раунд №{state['world']['activeCombat']['round']}", "")
    for hidden_value in (mob["hp"], mob["acc"], mob["def"], mob["dmg"]["max"]):
        assert str(hidden_value) not in body_without_round, f"утечка скрытого стата {hidden_value}"


    screen = app.render_combat_screen(state, GD)
    assert "БОЙ" in screen and "[1] Ударить" in screen

    state, events = _fight_to_end(state, paths, rng)
    assert "combat_victory" in _ids(events)
    assert "xp_gained" in _ids(events) and "gold_gained" in _ids(events)
    assert state["world"]["inCombat"] is False
    assert state["world"]["killsTotal"] == 1
    assert _session(paths)["world"]["killsTotal"] == 1


def test_retreat_command_routes_to_flee(paths):
    state = _start(paths)
    rng = random.Random(7)
    target = _first_exit(state)
    state, _ = _cmd(state, {"type": "move", "targetNodeId": target}, paths, rng)
    state = _buff_player(state)
    state = _put_monster(state, target, "mob_ghoul")
    state["world"]["fedMorning"] = True
    state, _ = _cmd(state, {"type": "look"}, paths, rng)
    state, _ = _cmd(state, {"type": "start_combat"}, paths, rng)
    fled = False
    for _ in range(20):
        state, events = _cmd(state, {"type": "combat_retreat"}, paths, rng)
        assert "err_unknown_command" not in _ids(events)
        if "combat_fled_success" in _ids(events):
            fled = True
            break
    assert fled and state["world"]["inCombat"] is False


def test_eat_blocked_in_combat(paths):
    """KI-10: еда в бою запрещена — err_in_combat, HP не меняется."""
    state = _start(paths)
    rng = random.Random(3)
    target = _first_exit(state)
    state, _ = _cmd(state, {"type": "move", "targetNodeId": target}, paths, rng)
    state = _put_monster(state, target, "mob_ghoul")
    state = _buff_player(state)
    state["world"]["fedMorning"] = True
    state, _ = _cmd(state, {"type": "look"}, paths, rng)
    state, _ = _cmd(state, {"type": "start_combat"}, paths, rng)
    assert state["world"]["inCombat"] is True

    hp_before = state["player"]["resources"]["hp"]["current"]
    inv_before = [(e["itemId"], e["count"]) for e in state["player"]["inventory"]]
    state, events = _cmd(state, {"type": "eat", "itemId": "food_bread"}, paths, rng)

    assert _ids(events) == ["err_in_combat"]
    assert state["player"]["resources"]["hp"]["current"] == hp_before
    assert [(e["itemId"], e["count"]) for e in state["player"]["inventory"]] == inv_before


# --- 3. Деревня: диалог с LLM-моком, бартер, еда, ночлег ---

def test_village_dialogue_barter_eat_and_inn(paths):
    state = _start(paths)
    rng = random.Random(11)
    state["player"]["inventory"].append({"itemId": "junk_broken_hilt", "count": 1})

    state, _ = _cmd(state, {"type": "open_dialogue", "npcId": BORIS}, paths, rng)
    state, events = _cmd(state, {"type": "talk_npc", "npcId": BORIS, "playerInput": "Есть сломанная рукоять"},
                         paths, rng, transport=_barter_transport)
    assert _ids(events)[0] == "npc_spoke"
    assert "dialogue_barter_offered" in _ids(events)
    assert "llm_fallback_used" not in _ids(events)
    assert state["npcs"][BORIS]["mood"] == "sympathetic"

    state, events = _cmd(state, {"type": "accept_barter", "npcId": BORIS}, paths, rng)
    assert "barter_completed" in _ids(events)
    assert state["player"]["gold"] == 13
    assert {"itemId": "food_bread", "count": 1} in state["player"]["inventory"]
    assert all(e["itemId"] != "junk_broken_hilt" for e in state["player"]["inventory"])

    state, events = _cmd(state, {"type": "eat", "itemId": "food_bread"}, paths, rng)
    assert "hunger_satisfied" in _ids(events)
    assert state["world"]["fedMorning"] is True

    state, events = _cmd(state, {"type": "inn_rest"}, paths, rng)
    assert "inn_rested" in _ids(events)
    assert state["world"]["day"] == 2 and state["world"]["stepOfDay"] == 1
    assert state["player"]["gold"] == 8
    saved = _session(paths)
    assert saved["world"]["day"] == 2 and saved["player"]["gold"] == 8


def test_talk_npc_uses_fallback_when_llm_disabled(paths):
    state = _start(paths)
    state["meta"]["llm"]["enabled"] = False
    state, events = _cmd(state, {"type": "talk_npc", "npcId": BORIS, "playerInput": "Привет"}, paths)
    assert _ids(events)[0] == "npc_spoke"
    assert "llm_fallback_used" in _ids(events)
    assert state["npcs"][BORIS]["met"] is True


def test_dialogue_screen_shows_offer_and_replies(paths):
    state = _start(paths)
    state["player"]["inventory"].append({"itemId": "junk_broken_hilt", "count": 1})
    state, _ = _cmd(state, {"type": "talk_npc", "npcId": BORIS, "playerInput": "Меняемся?"},
                    paths, transport=_barter_transport)
    state["npcs"][BORIS]["lastSuggestedReplies"] = ["Согласиться", "Уйти"]
    screen = app.render_dialogue_screen(state, BORIS, GD)
    assert "Борис" in screen and "Хлеб" in screen and "Сломанная рукоять" in screen
    assert "[5] Принять обмен" in screen and "[0] Закончить разговор" in screen


# --- 4. Логово и переход в «Дальние тропы» ---

def test_lair_clear_and_travel_to_next_region(paths):
    state = _start(paths)
    rng = random.Random(99)
    lair = next(n for n in state["map"]["nodes"] if n["type"] == "lair")
    state["map"]["currentNodeId"] = lair["id"]
    lair["state"]["visited"] = True
    lair["state"]["spawnRolled"] = True
    rat = GD.get_monster("mob_rat_giant")
    queue = [{"mobId": "mob_rat_giant", "revealed": False, "hp": rat["hp"], "maxHp": rat["hp"]} for _ in range(3)]
    lair["state"]["lairQueue"] = queue
    lair["state"]["lairQueueIndex"] = 0
    lair["state"]["monster"] = copy.deepcopy(queue[0])
    lair["state"]["monster"]["revealed"] = True
    state = _buff_player(state, level=10, strength=8, skill=8, hp=60)
    state["world"]["fedMorning"] = True
    state["world"]["fedEvening"] = True

    state, events = _cmd(state, {"type": "start_combat"}, paths, rng)
    assert state["world"]["inCombat"] is True
    state, events = _fight_to_end(state, paths, rng, limit=120)
    assert _ids(events).count("lair_next_monster") == 2
    assert "combat_victory" in _ids(events)
    assert state["world"]["killsTotal"] == 3

    state, events = _cmd(state, {"type": "travel_next_region"}, paths, rng)
    assert "region_changed" in _ids(events)
    assert state["meta"]["region"] == 2
    assert len(state["map"]["nodes"]) == 25
    assert state["map"]["currentNodeId"] == "node_00"
    assert _session(paths)["meta"]["region"] == 2


def test_travel_blocked_before_lair_cleared(paths):
    state = _start(paths)
    state, events = _cmd(state, {"type": "travel_next_region"}, paths)
    assert _ids(events) == ["err_not_in_lair"]

# --- 5. Рендер и защита от неверного ввода ---

def test_status_line_format(paths):
    state = _start(paths)
    line = app.render_status_line(state, GD)
    assert line.startswith("ДЕНЬ 1 · ШАГ 1/20 · HP 10/10 · MP 2/2 · ЗОЛОТО 15 · [")
    assert "завтрак: поесть до шага 7!" in line


def test_hp_bar_scale():
    assert app.hp_bar(6, 10) == "[HP ######----]"
    assert app.hp_bar(0, 10) == "[HP ----------]"
    assert app.hp_bar(10, 10) == "[HP ##########]"
    assert app.hp_bar(1, 3) == "[HP ###-------]"


def test_inventory_hides_hidden_item_stats(paths):
    state = _start(paths)
    state["player"]["inventory"] = [{"itemId": "food_berries", "count": 2}]
    screen = app.render_inventory_screen(state, GD)
    assert "Ягоды (2)" in screen
    assert "hpRestore" not in screen and "+1 HP" not in screen


def test_explore_menu_commands_are_routable(paths):
    state = _start(paths)
    for item in app.build_explore_menu(state, GD):
        command = item.get("command")
        if command:
            _, events = _cmd(state, command, paths)
            assert "err_unknown_command" not in _ids(events)


def test_run_cli_handles_invalid_input_and_quit(paths):
    state = _start(paths)
    session, template = paths
    inputs = iter(["0", "xyz", "77", "0", "9"])
    output = []
    final = app.run_cli(
        state, GD, session_path=session, template_path=template, rng=random.Random(5),
        input_fn=lambda prompt: next(inputs), output_fn=output.append,
    )
    text = "\n".join(output)
    assert "Введите номер действия" in text or "Неверный ввод" in text
    assert "До свидания" in text
    assert final["map"]["currentNodeId"] == "node_00"


def test_run_cli_moves_and_autosaves(paths):
    state = _start(paths)
    session, template = paths
    target = _first_exit(state, searchable=False)
    inputs = iter(["0", "0", "1", "0", "9"])
    output = []
    final = app.run_cli(
        state, GD, session_path=session, template_path=template, rng=random.Random(2),
        input_fn=lambda prompt: next(inputs), output_fn=output.append,
    )
    assert final["map"]["currentNodeId"] == target
    assert _session(paths)["map"]["currentNodeId"] == target


def test_run_cli_leaves_creation_screen_when_points_spent(paths):
    state = _start(paths)
    session, template = paths
    # три очка: сила, сила, ловкость -> экран должен закрыться сам
    inputs = iter(["1", "1", "2", "0", "9"])
    output = []
    final = app.run_cli(
        state, GD, session_path=session, template_path=template, rng=random.Random(2),
        input_fn=lambda prompt: next(inputs), output_fn=output.append,
    )
    assert final["player"]["unspentPoints"]["attributes"] == 0
    assert final["player"]["attributes"]["strength"] == 3
    assert final["player"]["attributes"]["agility"] == 2
    text = "\n".join(output)
    assert "Распределите 3 стартовых очка" in text          # экран был
    assert "[1] Осмотреться (1 AP)" in text                 # и сменился на исследование
    assert "err_no_attribute_points" not in text


def test_creation_menu_hides_maxed_attributes(paths):
    state = _start(paths)
    state["player"]["attributes"]["strength"] = 3
    menu = app.build_creation_menu(state, GD)
    labels = " ".join(item["label"] for item in menu)
    assert "Сила" not in labels
    assert all(item.get("command", {}).get("attribute") != "strength" for item in menu)

def test_heal_stale_session_rebuilds_dead_save(tmp_path):
    from main import ensure_template, heal_stale_session

    template = str(tmp_path / "state_template.json")
    session = str(tmp_path / "state_session.json")

    # имитация бага: шаблон на 1 узел, из него создана сессия
    stale = {
        "schemaVersion": 1,
        "map": {
            "currentNodeId": "node_00",
            "nodes": [{"id": "node_00", "type": "village", "connections": [], "state": {}}],
        },
    }
    with open(template, "w", encoding="utf-8") as f:
        json.dump(stale, f)
    with open(session, "w", encoding="utf-8") as f:
        json.dump(stale, f)

    ensure_template(template)                      # шаблон стал 25 узлов
    assert heal_stale_session(session, template) is True

    state = new_game(template_path=template, session_path=session)
    village = app.node_by_id(state, "node_00")
    assert len(village["connections"]) == 3        # выходить есть куда


def test_heal_keeps_live_session(tmp_path):
    from main import heal_stale_session
    from engine.storage import save_state

    template = tmp_path / "state_template.json"
    session = tmp_path / "state_session.json"
    generate_template(template)
    state = new_game(template_path=str(template), session_path=str(session))
    state["player"]["gold"] = 777
    save_state(state, str(session))

    assert heal_stale_session(str(session), str(template)) is False
    with open(session, encoding="utf-8") as f:
        assert json.load(f)["player"]["gold"] == 777