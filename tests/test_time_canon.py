"""Канон времени (§ 7) для часов Блока 4.2: перк, сброс сытости, респавн, permadeath."""

import json
import random
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine import exploration
from engine.controller import dispatch_command, exploration_view
from engine.data_loader import GameData
from engine.storage import new_game
from scripts.generate_template import generate_template

GD = GameData(str(_root / "data"))


@pytest.fixture()
def paths(tmp_path):
    template = tmp_path / "state_template.json"
    session = tmp_path / "state_session.json"
    generate_template(template)
    return str(session), str(template)


def _state(paths, scavenging=0, step=1, fed_morning=False, fed_evening=False,
           day=1, level=1, hp=None):
    session, template = paths
    state = new_game(template_path=template, session_path=session)
    player = state["player"]
    player["skills"]["scavenging"] = scavenging
    player["level"] = level
    player["unspentPoints"]["attributes"] = 0
    if hp is not None:
        player["resources"]["hp"] = {"current": hp, "max": 30}
    state["world"].update({
        "day": day, "stepOfDay": step,
        "fedMorning": fed_morning, "fedEvening": fed_evening,
        "inCombat": False, "activeEffects": [],
    })
    return state


def _wait(state, times=1):
    events = []
    for _ in range(times):
        state, ev = exploration.wait_step(
            state, game_data=exploration_view(GD), rng=random.Random(7)
        )
        events.extend(ev)
    return state, events


def _dead(events):
    return any(e["id"] in ("player_death", "player_died") for e in events)


def test_without_perk_dies_at_step_7(paths):
    state = _state(paths, scavenging=0, step=5)
    state, events = _wait(state)                 # шаг 6
    assert not _dead(events)
    state, events = _wait(state)                 # шаг 7 — дедлайн
    assert _dead(events)
    assert any(e.get("cause") == "starvation_morning" for e in events)


def test_tight_belt_perk_moves_morning_deadline_to_9(paths):
    state = _state(paths, scavenging=6, step=5)
    state, events = _wait(state, 3)              # шаги 6, 7, 8 — живы
    assert not _dead(events)
    assert state["world"]["stepOfDay"] == 8
    state, events = _wait(state)                 # шаг 9 — дедлайн с перком
    assert _dead(events)


def test_tight_belt_perk_moves_evening_deadline_to_19(paths):
    state = _state(paths, scavenging=6, step=16, fed_morning=True)
    state, events = _wait(state, 2)              # шаги 17, 18 — живы
    assert not _dead(events)
    state, events = _wait(state)                 # шаг 19
    assert _dead(events)
    assert any(e.get("cause") == "starvation_evening" for e in events)


def test_fed_flags_reset_on_new_day(paths):
    state = _state(paths, step=20, fed_morning=True, fed_evening=True)
    state, events = _wait(state)
    assert not _dead(events)
    assert state["world"]["day"] == 2
    assert state["world"]["stepOfDay"] == 1
    assert state["world"]["fedMorning"] is False
    assert state["world"]["fedEvening"] is False


def test_second_day_requires_breakfast_again(paths):
    state = _state(paths, step=20, fed_morning=True, fed_evening=True)
    state, _ = _wait(state)                      # день 2, шаг 1
    state, events = _wait(state, 6)              # шаги 2..7
    assert _dead(events), "на второй день завтрак снова обязателен"


def test_regen_block_window_follows_perk(paths):
    # шаг 18 при перке: раньше окно голода кончалось на 16 и реген шёл,
    # теперь окно до 19 — реген заблокирован
    state = _state(paths, scavenging=6, step=17, fed_morning=True, level=3, hp=5)
    state, events = _wait(state)                 # шаг 18, кратно 3
    assert not _dead(events)
    assert state["player"]["resources"]["hp"]["current"] == 5


def test_days_since_cleared_ticks_on_new_day(paths):
    state = _state(paths, step=20, fed_morning=True, fed_evening=True)
    nodes = state["map"]["nodes"]
    nodes[1]["state"]["daysSinceCleared"] = 2
    nodes[2]["state"]["daysSinceCleared"] = None

    new_state, _ = _wait(state)

    # проверяем НОВЫЙ state: часы работают на глубокой копии
    new_nodes = new_state["map"]["nodes"]
    assert new_nodes[1]["state"]["daysSinceCleared"] == 3
    assert new_nodes[2]["state"]["daysSinceCleared"] is None
    # и заодно фиксируем чистоту функции: вход не тронут
    assert nodes[1]["state"]["daysSinceCleared"] == 2


def test_permadeath_from_exploration_clock_via_controller(paths):
    session, template = paths
    state = _state(paths, scavenging=0, step=6)
    state, events = dispatch_command(
        state, {"type": "wait"}, GD, rng=random.Random(7),
        session_path=session, template_path=template,
    )
    ids = [e["id"] for e in events]
    assert "player_died" in ids
    assert "session_reset_permadeath" in ids
    assert state["world"]["day"] == 1 and state["world"]["stepOfDay"] == 1
    with open(session, encoding="utf-8") as f:
        fresh = json.load(f)
    assert fresh["world"]["stepOfDay"] == 1 and fresh["player"]["gold"] == 15