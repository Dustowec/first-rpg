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


def _death_reason(events):
    """Причина гибели: world_time отдаёт reason, старый формат exploration — cause."""
    for e in events:
        if e["id"] in ("player_death", "player_died"):
            return e.get("reason") or e.get("cause")
    return None


def test_without_perk_dies_at_step_7(paths):
    state = _state(paths, scavenging=0, step=5)
    state, events = _wait(state)                 # шаг 6
    assert not _dead(events)
    state, events = _wait(state)                 # шаг 7 — дедлайн
    assert _dead(events)
    assert _death_reason(events) == "starvation_morning"


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
    assert _death_reason(events) == "starvation_evening"


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
    # Узел 1 заселяем и «зачищаем»: только зачищенные узлы тикают (KI-4)
    nodes[1]["state"]["monster"] = None
    nodes[1]["state"]["spawnRolled"] = True
    nodes[1]["state"]["daysSinceCleared"] = 2
    nodes[2]["state"]["daysSinceCleared"] = None

    new_state, _ = _wait(state)

    # проверяем НОВЫЙ state: часы работают на глубокой копии
    new_nodes = new_state["map"]["nodes"]
    assert new_nodes[1]["state"]["daysSinceCleared"] == 3
    # узлы, где счётчик не инициализирован (None), не тикают от None
    assert new_nodes[2]["state"]["daysSinceCleared"] != 3
    # и заодно фиксируем чистоту функции: вход не тронут
    assert nodes[1]["state"]["daysSinceCleared"] == 2


# ---------------------------------------------------------------------------
# KI-4 / KI-7: респавн при смене дня и единые правила времени
# ---------------------------------------------------------------------------

MOB_HP = {mid: GD.get_monster(mid)["hp"]
          for mid in ("mob_rat_giant", "mob_bandit_scout", "mob_wolf_forest")}


def test_respawn_uses_node_type_and_top_level_hp(paths):
    """KI-4: узлы worldgen без biomeId респавнятся, maxHp = data/{mob}.hp."""
    state = _state(paths, step=20, fed_morning=True, fed_evening=True)
    nodes = state["map"]["nodes"]
    # Дикий узел в формате worldgen: тип биома в ключе "type", biomeId отсутствует
    wild = next(nd for nd in nodes if nd["id"] != "node_00")
    assert "biomeId" not in wild
    wild["state"]["monster"] = None
    wild["state"]["spawnRolled"] = True
    wild["state"]["daysSinceCleared"] = 4

    new_state, events = _wait(state)

    respawned = [e for e in events if e["id"] == "monster_respawned"]
    assert respawned, f"респавн не сработал: {[e['id'] for e in events]}"
    assert respawned[0]["nodeId"] == wild["id"]

    node = next(nd for nd in new_state["map"]["nodes"] if nd["id"] == wild["id"])
    monster = node["state"]["monster"]
    assert monster["mobId"] == respawned[0]["mobId"]
    assert monster["maxHp"] == MOB_HP[monster["mobId"]], "maxHp должен браться из data/*.json"


def test_respawn_triggers_from_move(paths):
    """KI-4: смена дня через move (exploration) тоже респавнит монстров."""
    state = _state(paths, step=20, fed_morning=True, fed_evening=True)
    nodes = state["map"]["nodes"]
    current = next(nd for nd in nodes if nd["id"] == state["map"]["currentNodeId"])
    target_id = current["connections"][0]
    wild = next(nd for nd in nodes if nd["id"] == target_id)
    wild["state"]["monster"] = None
    wild["state"]["spawnRolled"] = True
    wild["state"]["daysSinceCleared"] = 4
    wild["state"]["visited"] = True

    new_state, events = exploration.move_to_node(
        state, target_id, game_data=exploration_view(GD), rng=random.Random(7),
        session_path=paths[0], template_path=paths[1],
    )
    ids = [e["id"] for e in events]
    assert "moved_to_node" in ids
    assert "monster_respawned" in ids, f"move не респавнит: {ids}"


def test_single_clock_for_combat_and_exploration(paths):
    """KI-7: world_time и exploration.advance_time дают одинаковый результат."""
    from engine import world_time

    base = _state(paths, step=3, fed_morning=True, fed_evening=True)
    base["player"]["resources"]["hp"] = {"current": 5, "max": 10}
    base["player"]["resources"]["mp"] = {"current": 0, "max": 5}
    base["world"]["activeEffects"] = [{"type": "poison", "hpDeltaPerTurn": -1, "ticksLeft": 2}]

    via_world, ev_world = world_time.advance_time(base, steps=2, game_data=GD)
    via_expl, ev_expl = exploration.advance_time(
        base, steps=2, gd=exploration_view(GD), rng=random.Random(7),
    )

    assert via_world["world"] == via_expl["world"]
    assert via_world["player"] == via_expl["player"]
    assert [e["id"] for e in ev_world] == [e["id"] for e in ev_expl]


def test_mp_regen_blocked_in_hunger_window(paths):
    """KI-7: голодное окно блокирует MP-реген так же, как HP (раньше — только HP)."""
    state = _state(paths, step=4, fed_morning=False, fed_evening=True)
    state["player"]["resources"]["mp"] = {"current": 0, "max": 5}
    state["player"]["resources"]["hp"] = {"current": 5, "max": 10}

    from engine import world_time

    new_state, _ = world_time.advance_time(state, steps=1, game_data=GD)
    # шаг 5 — кратно 5 (MP-реген), но окно голода (5 < 7, не завтракали)
    assert new_state["world"]["stepOfDay"] == 5
    assert new_state["player"]["resources"]["mp"]["current"] == 0
    assert new_state["player"]["resources"]["hp"]["current"] == 5


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