"""Патч data/npcs/*.json: actionWhitelist по ТЗ 5.2 (§ 31.2 + discount_10 + end_dialogue).

Запуск: python scripts/patch_npc_actions.py
Идемпотентен: повторный запуск ничего не ломает.
"""

import json
import re
from pathlib import Path

WHITELISTS = {
    "npc_elder_miroslav": ["give_hint", "none", "end_dialogue"],
    "npc_merchant_ganna": ["open_trade", "discount_10", "none", "end_dialogue"],
    "npc_blacksmith_kolm": ["open_trade", "discount_10", "none", "end_dialogue"],
    "npc_innkeeper_boris": ["barter_offer", "discount_10", "give_hint", "none", "end_dialogue"],
    "npc_herbalist_vela": ["open_trade", "discount_10", "give_hint", "none", "end_dialogue"],
    "npc_hunter_rask": ["give_hint", "barter_offer", "discount_10", "none", "end_dialogue"],
    "npc_wanderer_kit": ["barter_offer", "give_hint", "none", "end_dialogue"],
}


def main() -> None:
    data_dir = Path(__file__).resolve().parents[1] / "data" / "npcs"
    for npc_id, actions in WHITELISTS.items():
        path = data_dir / f"{npc_id}.json"
        text = path.read_text(encoding="utf-8")
        block = '"actionWhitelist": [\n' + ",\n".join(f'    "{a}"' for a in actions) + "\n  ]"
        new_text, n = re.subn(r'"actionWhitelist":\s*\[[^\]]*\]', block, text, count=1)
        if n == 0:
            raise SystemExit(f"Не найдено поле actionWhitelist в {path}")
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            print(f"обновлён {npc_id}: {actions}")
        else:
            print(f"без изменений {npc_id}")
        json.loads(path.read_text(encoding="utf-8"))  # проверка валидности JSON


if __name__ == "__main__":
    main()