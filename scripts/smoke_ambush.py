"""Verify ambush -> real combat -> attack & flee work end-to-end."""
import copy
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.exploration import move_to_node, _load_game_data
from engine.combat import combat_step
from engine.data_loader import GameData
from engine.worldgen import generate_region

ROOT = Path(__file__).parent.parent
gd_flat = _load_game_data(str(ROOT / "data"))
GD = GameData(str(ROOT / "data"))

map_data = generate_region(20260101, 1, gd_flat)

st = {
    "schemaVersion": 1,
    "meta": {"seed": 20260101, "region": 1, "difficultyMultiplier": 1.0,
             "llm": {"enabled": False}},
    "player": {
        "level": 1, "xp": 0, "gold": 15,
        "attributes": {"strength": 1, "agility": 1, "constitution": 1,
                       "intelligence": 1, "wisdom": 1},
        "skills": {k: 0 for k in ("melee_heavy", "melee_light", "armor_mastery",
                                   "pyromancy", "restoration", "hexes", "alchemy",
                                   "crafting", "scavenging")},
        "resources": {"hp": {"current": 10, "max": 10}, "mp": {"current": 2, "max": 2}},
        "inventory": [],
        "equipment": {
            "weapon": {"itemId": "wpn_club_simple",
                       "durability": {"current": 15, "max": 15}},
            "armor": {"itemId": "arm_cloth_poor",
                      "durability": {"current": 15, "max": 15}},
        },
    },
    "world": {"day": 1, "stepOfDay": 1, "fedMorning": True, "fedEvening": True,
              "inCombat": False, "activeCombat": None, "activeEffects": [],
              "killsTotal": 0, "locationsVisited": 1},
    "map": map_data, "npcs": {}, "flags": {},
}

cur = next(nd for nd in map_data["nodes"] if nd["connections"])
target_id = cur["connections"][0]
for nd in st["map"]["nodes"]:
    if nd["id"] == target_id:
        nd["state"]["spawnRolled"] = True
        nd["state"]["monster"] = {"mobId": "mob_wolf_forest", "revealed": False,
                                  "hp": 6, "maxHp": 6}
        break
st["map"]["currentNodeId"] = cur["id"]

for seed in range(500):
    st2 = copy.deepcopy(st)
    new_st, events = move_to_node(st2, target_id, rng=random.Random(seed),
                                  game_data=gd_flat)
    if any(e["id"] == "ambush_triggered" for e in events):
        break

print("events after move:", [e["id"] for e in events])
print("inCombat     =", new_st["world"]["inCombat"])
print("activeCombat =", (new_st["world"].get("activeCombat") or {}).get("monster", {}).get("mobId"))
assert new_st["world"]["activeCombat"] is not None, "FIX FAILED: no activeCombat"

# 1) Атака работает
st_at, ev_at = combat_step(new_st, {"type": "attack"}, GD)
print("attack ->", [e["id"] for e in ev_at])
assert not any(e["id"] == "err_not_in_combat" for e in ev_at), "attack still broken"

# 2) Отступление работает: долбим flee, пока не получится
st_cur = new_st
for attempt in range(50):
    st_cur, ev_flee = combat_step(st_cur, {"type": "flee"}, GD)
    ids = [e["id"] for e in ev_flee]
    print(f"flee #{attempt} ->", ids)
    if "combat_fled_success" in ids:
        assert st_cur["world"]["inCombat"] is False
        assert st_cur["world"]["activeCombat"] is None
        print("OK: вышел из боя")
        break
else:
    raise AssertionError("flee never succeeded in 50 attempts (chance 50%)")

print("\nFIX VERIFIED: ambush -> real combat -> attack works, retreat works.")
