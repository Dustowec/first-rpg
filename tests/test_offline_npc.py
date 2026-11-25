"""Офлайн-реплики NPC: приветствие, сценарии, бартер/скидка/подсказки без LLM."""

import random
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from engine.controller import dispatch_command
from engine.data_loader import GameData
from engine.offline_npc import OFFLINE_DIALOGUES, get_greeting, has_offline_dialogue
from engine.storage import new_game
from scripts.generate_template import generate_template

GD = GameData(str(_root / "data"))


@pytest.fixture()
def paths(tmp_path):
    template = tmp_path / "t.json"
    session = tmp_path / "s.json"
    generate_template(template)
    return str(session), str(template)


def _start(paths, llm=False):
    session, template = paths
    state = new_game(template_path=template, session_path=session)
    state["meta"]["llm"]["enabled"] = llm
    state["player"]["inventory"] = [{"itemId": "junk_broken_hilt", "count": 1}]
    return state


def _cmd(state, command, paths):
    session, template = paths
    return dispatch_command(state, command, GD, rng=random.Random(3),
                            session_path=session, template_path=template)


def test_all_seven_npcs_have_scripts():
    assert set(OFFLINE_DIALOGUES) == set(GD.npcs)
    for npc_id in GD.npcs:
        assert has_offline_dialogue(npc_id)
        assert OFFLINE_DIALOGUES[npc_id]["greeting"]["suggestedReplies"]


def test_open_dialogue_emits_greeting_with_replies(paths):
    state = _start(paths)
    state, events = _cmd(state, {"type": "open_dialogue", "npcId": "npc_innkeeper_boris"}, paths)
    spoke = next(e for e in events if e["id"] == "npc_spoke")
    assert spoke["npcReply"]
    assert len(spoke["suggestedReplies"]) >= 2


def test_offline_barter_works_without_llm(paths):
    state = _start(paths)
    state, events = _cmd(state, {"type": "talk_npc", "npcId": "npc_innkeeper_boris",
                                 "playerInput": "Есть сломанная рукоять, обменяем на хлеб?"}, paths)
    assert "dialogue_barter_offered" in [e["id"] for e in events]
    state, events = _cmd(state, {"type": "accept_barter", "npcId": "npc_innkeeper_boris"}, paths)
    assert "barter_completed" in [e["id"] for e in events]
    assert state["player"]["gold"] == 13


def test_offline_discount_and_hint(paths):
    state = _start(paths)
    state, _ = _cmd(state, {"type": "talk_npc", "npcId": "npc_innkeeper_boris",
                            "playerInput": "Скинешь немного?"}, paths)
    assert state["npcs"]["npc_innkeeper_boris"].get("tempDiscount10") is True
    state, _ = _cmd(state, {"type": "talk_npc", "npcId": "npc_elder_miroslav",
                            "playerInput": "Куда идти?"}, paths)
    assert state["flags"].get("revealedHints")


def test_offline_barter_prices_within_limit():
    for bundle in OFFLINE_DIALOGUES.values():
        for script in bundle["scripts"]:
            if script["action"].get("type") == "barter_offer":
                give = GD.get_item(script["action"]["giveItemId"])
                assert give["economy"]["buyPrice"] <= 15
                take = GD.get_item(script["action"]["takeItemId"])
                assert take["category"] in ("junk", "material")


def test_unknown_phrase_falls_back_to_greeting(paths):
    state = _start(paths)
    state, events = _cmd(state, {"type": "talk_npc", "npcId": "npc_innkeeper_boris",
                                 "playerInput": "квак квак"}, paths)
    spoke = next(e for e in events if e["id"] == "npc_spoke")
    assert spoke["npcReply"] == OFFLINE_DIALOGUES["npc_innkeeper_boris"]["greeting"]["ru"]
