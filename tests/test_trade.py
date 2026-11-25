"""Тесты для Блока 4.4: Сервисы деревни, торговля и репутация NPC."""

import os
import sys
from pathlib import Path

import pytest

# Добавляем корень проекта в sys.path для импорта
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from engine.data_loader import GameData
from engine import trade
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
        "meta": {},
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
        "world": {},
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
        else:
            state[key] = value
    return state


def _make_camp_state(npc_id: str = "npc_hunter_rask"):
    """Создаёт тестовое состояние с лагерём (camp)."""
    player = create_default_player()
    return {
        "player": player,
        "meta": {},
        "map": {
            "currentNodeId": "camp_01",
            "nodes": [
                {
                    "id": "camp_01",
                    "type": "camp",
                    "name": "Test Camp",
                    "connections": [],
                    "npcId": npc_id,
                }
            ],
        },
        "npcs": {
            "npc_hunter_rask": {"mood": "neutral", "reputation": "neutral", "met": False},
        },
        "flags": {},
        "world": {},
    }


def _make_wild_state():
    """Создаёт тестовое состояние с дикой локацией."""
    player = create_default_player()
    return {
        "player": player,
        "meta": {},
        "map": {
            "currentNodeId": "node_forest",
            "nodes": [
                {
                    "id": "node_forest",
                    "type": "biome",
                    "name": "Forest Edge",
                    "connections": [],
                }
            ],
        },
        "npcs": {},
        "flags": {},
        "world": {},
    }


# ---------------------------------------------------------------------------
# A. Присутствие NPC
# ---------------------------------------------------------------------------


class TestNpcPresence:
    """Критерий приёмки 1: Присутствие NPC."""

    def test_village_all_npcs_present(self):
        """В node_00 (village) доступны все 5 деревенских NPC."""
        state = _make_state()
        for npc_id in trade.VILLAGE_NPCS:
            assert trade.is_npc_present(state, npc_id) is True

    def test_village_non_village_npc_absent(self):
        """В деревне охотник Раск отсутствует."""
        state = _make_state()
        assert trade.is_npc_present(state, "npc_hunter_rask") is False

    def test_wild_location_no_npcs(self):
        """В дикой локации (biome) любые NPC отсутствуют."""
        state = _make_wild_state()
        for npc_id in trade.VILLAGE_NPCS:
            assert trade.is_npc_present(state, npc_id) is False
        assert trade.is_npc_present(state, "npc_hunter_rask") is False

    def test_camp_only_assigned_npc(self):
        """В лагере (camp) доступен только назначенный node["npcId"]."""
        state = _make_camp_state("npc_hunter_rask")
        assert trade.is_npc_present(state, "npc_hunter_rask") is True
        # Деревенские NPC в лагере отсутствуют
        for npc_id in trade.VILLAGE_NPCS:
            assert trade.is_npc_present(state, npc_id) is False

    def test_camp_different_npc(self):
        """В лагере с другим назначенным NPC."""
        state = _make_camp_state("npc_merchant_ganna")
        assert trade.is_npc_present(state, "npc_merchant_ganna") is True
        assert trade.is_npc_present(state, "npc_blacksmith_kolm") is False


# ---------------------------------------------------------------------------
# B. Влияние репутации
# ---------------------------------------------------------------------------


class TestReputation:
    """Критерий приёмки 2: Влияние репутации."""

    def test_hostile_buy_rejected(self):
        """При reputation == "hostile" покупка отклоняется."""
        state = _make_state(npcs={
            "npc_merchant_ganna": {"mood": "neutral", "reputation": "hostile", "met": False},
        })
        state["player"]["inventory"].append({"itemId": "food_bread", "count": 1})
        new_state, events = trade.buy_item(state, "npc_merchant_ganna", "food_bread", 1, _game_data)
        assert events[0]["id"] == "err_npc_refuses_trade"
        assert events[0]["reason"] == "hostile"

    def test_hated_buy_rejected(self):
        """При reputation == "hated" покупка отклоняется."""
        state = _make_state(npcs={
            "npc_merchant_ganna": {"mood": "neutral", "reputation": "hated", "met": False},
        })
        state["player"]["inventory"].append({"itemId": "food_bread", "count": 1})
        new_state, events = trade.buy_item(state, "npc_merchant_ganna", "food_bread", 1, _game_data)
        assert events[0]["id"] == "err_npc_refuses_trade"
        assert events[0]["reason"] == "hated"

    def test_hostile_sell_rejected(self):
        """При reputation == "hostile" продажа отклоняется."""
        state = _make_state(npcs={
            "npc_merchant_ganna": {"mood": "neutral", "reputation": "hostile", "met": False},
        })
        state["player"]["inventory"].append({"itemId": "food_berries", "count": 5})
        new_state, events = trade.sell_item(state, "npc_merchant_ganna", "food_berries", 1, _game_data)
        assert events[0]["id"] == "err_npc_refuses_trade"

    def test_friendly_buy_discount(self):
        """При reputation == "friendly" цена покупки снижается."""
        npc_state = {"reputation": "friendly"}
        item_data = _game_data.get_item("food_bread")
        # buyPrice = 3, mult = 0.95, round(3 * 0.95) = round(2.85) = 3
        price = trade.get_buy_price(item_data, npc_state)
        # При small buyPrice rounding может дать ту же цену, но множитель применяется
        assert price == 3  # round(2.85) = 3

        # Проверяем на более дорогом предмете
        item_data = _game_data.get_item("pot_heal_minor")
        # buyPrice = 15, mult = 0.95, round(15 * 0.95) = round(14.25) = 14
        price = trade.get_buy_price(item_data, npc_state)
        assert price == 14

    def test_honored_buy_discount(self):
        """При reputation == "honored" цена покупки снижается сильнее."""
        npc_state = {"reputation": "honored"}
        item_data = _game_data.get_item("pot_heal_minor")
        # buyPrice = 15, mult = 0.90, round(15 * 0.90) = round(13.5) = 14 (banker's rounding)
        price = trade.get_buy_price(item_data, npc_state)
        assert price == 14

    def test_honored_sell_bonus(self):
        """При reputation == "honored" цена продажи возрастает на +5%."""
        npc_state = {"reputation": "honored"}
        item_data = _game_data.get_item("food_berries")
        # sellPrice = 0 -> returns 0
        price = trade.get_sell_price(item_data, npc_state)
        assert price == 0

        # Проверяем на предмете с sellPrice > 0
        item_data = _game_data.get_item("wpn_sword_regular")
        # sellPrice = 7, mult = 1.05, round(7 * 1.05) = round(7.35) = 7
        price = trade.get_sell_price(item_data, npc_state)
        assert price == 7

        # Проверяем на более дорогом
        item_data = _game_data.get_item("wpn_sword_fine")
        # sellPrice = 30, mult = 1.05, round(30 * 1.05) = round(31.5) = 32
        price = trade.get_sell_price(item_data, npc_state)
        assert price == 32

    def test_neutral_no_modifiers(self):
        """При reputation == "neutral" модификаторы не применяются."""
        npc_state = {"reputation": "neutral"}
        item_data = _game_data.get_item("pot_heal_minor")
        buy_price = trade.get_buy_price(item_data, npc_state)
        assert buy_price == item_data["economy"]["buyPrice"]

        item_data = _game_data.get_item("wpn_sword_regular")
        sell_price = trade.get_sell_price(item_data, npc_state)
        assert sell_price == item_data["economy"]["sellPrice"]


# ---------------------------------------------------------------------------
# C. Временная скидка 10%
# ---------------------------------------------------------------------------


class TestTempDiscount:
    """Тесты временной диалоговой скидки 10%."""

    def test_discount_applied(self):
        """При tempDiscount10 скидка 10% применяется."""
        npc_state = {"reputation": "neutral", "tempDiscount10": True}
        item_data = _game_data.get_item("pot_heal_minor")
        # buyPrice = 15, mult = 1.0 * 0.90 = 0.90, round(15 * 0.90) = round(13.5) = 14
        price = trade.get_buy_price(item_data, npc_state)
        assert price == 14

    def test_discount_friendly_combined(self):
        """При friendly + tempDiscount10 множители комбинируются."""
        npc_state = {"reputation": "friendly", "tempDiscount10": True}
        item_data = _game_data.get_item("pot_heal_minor")
        # buyPrice = 15, mult = 0.95 * 0.90 = 0.855, round(15 * 0.855) = round(12.825) = 13
        price = trade.get_buy_price(item_data, npc_state)
        assert price == 13

    def test_discount_from_world_flags(self):
        """Скидка может быть в world_flags."""
        npc_state = {"reputation": "neutral"}
        world_flags = {"tempDiscount10": True}
        item_data = _game_data.get_item("pot_heal_minor")
        # buyPrice = 15, mult = 1.0 * 0.90 = 0.90, round(15 * 0.90) = 14
        price = trade.get_buy_price(item_data, npc_state, world_flags)
        assert price == 14


# ---------------------------------------------------------------------------
# D. Покупка и продажа
# ---------------------------------------------------------------------------


class TestBuyItem:
    """Критерий приёмки 3: buy_item корректно списывает золото и добавляет предмет."""

    def test_buy_success(self):
        """Успешная покупка предмета."""
        state = _make_state(player={"gold": 100})
        initial_gold = state["player"]["gold"]
        initial_inv_count = sum(
            e.get("count", 0) for e in state["player"]["inventory"]
            if e["itemId"] == "food_bread"
        )

        new_state, events = trade.buy_item(
            state, "npc_merchant_ganna", "food_bread", 3, _game_data
        )

        assert events[0]["id"] == "item_bought"
        assert events[0]["npcId"] == "npc_merchant_ganna"
        assert events[0]["itemId"] == "food_bread"
        assert events[0]["count"] == 3
        # food_bread buyPrice = 3, total = 9
        assert events[0]["goldSpent"] == 9
        assert new_state["player"]["gold"] == initial_gold - 9
        bread_entries = [
            e for e in new_state["player"]["inventory"] if e["itemId"] == "food_bread"
        ]
        assert bread_entries[0]["count"] == initial_inv_count + 3

    def test_buy_not_enough_gold(self):
        """Отклонение при нехватке золота."""
        state = _make_state(player={"gold": 1})
        state["player"]["inventory"].append({"itemId": "food_bread", "count": 1})
        new_state, events = trade.buy_item(
            state, "npc_merchant_ganna", "food_bread", 1, _game_data
        )
        assert events[0]["id"] == "err_not_enough_gold"
        # food_bread buyPrice = 3
        assert events[0]["required"] == 3
        assert events[0]["current"] == 1

    def test_buy_in_combat(self):
        """Покупка в бою запрещена."""
        state = _make_state(world={"inCombat": True})
        state["player"]["inventory"].append({"itemId": "food_bread", "count": 1})
        new_state, events = trade.buy_item(
            state, "npc_merchant_ganna", "food_bread", 1, _game_data
        )
        assert events[0]["id"] == "err_in_combat"

    def test_buy_npc_not_here(self):
        """Покупка при отсутствии NPC."""
        state = _make_wild_state()
        new_state, events = trade.buy_item(
            state, "npc_merchant_ganna", "food_bread", 1, _game_data
        )
        assert events[0]["id"] == "err_npc_not_here"

    def test_buy_item_not_sold_by_npc(self):
        """Покупка предмета, который NPC не продаёт."""
        state = _make_state()
        state["player"]["inventory"].append({"itemId": "food_bread", "count": 1})
        # У Ганны в ассортименте нет оружия
        new_state, events = trade.buy_item(
            state, "npc_merchant_ganna", "wpn_sword_fine", 1, _game_data
        )
        assert events[0]["id"] == "err_item_not_sold_by_npc"

    def test_buy_invalid_count(self):
        """Покупка с count < 1 отклоняется."""
        state = _make_state()
        new_state, events = trade.buy_item(
            state, "npc_merchant_ganna", "food_bread", 0, _game_data
        )
        assert events[0]["id"] == "err_invalid_count"

    def test_buy_with_temp_discount_reset(self):
        """После покупки с tempDiscount10 флаг сбрасывается."""
        state = _make_state(npcs={
            "npc_merchant_ganna": {
                "mood": "neutral", "reputation": "neutral",
                "met": False, "tempDiscount10": True,
            },
        })
        state["player"]["inventory"].append({"itemId": "food_bread", "count": 1})
        state["player"]["gold"] = 100

        new_state, events = trade.buy_item(
            state, "npc_merchant_ganna", "food_bread", 1, _game_data
        )
        assert events[0]["id"] == "item_bought"
        # Флаг сброшен
        npc_data = new_state["npcs"]["npc_merchant_ganna"]
        assert npc_data.get("tempDiscount10") is False


class TestSellItem:
    """Критерий приёмки 3: sell_item удаляет предмет и начисляет золото."""

    def test_sell_success(self):
        """Успешная продажа предмета."""
        state = _make_state(player={"gold": 10})
        state["player"]["inventory"].append({"itemId": "food_berries", "count": 5})
        initial_gold = state["player"]["gold"]

        new_state, events = trade.sell_item(
            state, "npc_merchant_ganna", "food_berries", 3, _game_data
        )

        assert events[0]["id"] == "item_sold"
        assert events[0]["npcId"] == "npc_merchant_ganna"
        assert events[0]["itemId"] == "food_berries"
        assert events[0]["count"] == 3
        # food_berries sellPrice = 0 -> total_gain = 0
        assert events[0]["goldEarned"] == 0
        assert new_state["player"]["gold"] == initial_gold

    def test_sell_success_with_gold(self):
        """Продажа предмета с sellPrice > 0."""
        state = _make_state(player={"gold": 10})
        state["player"]["inventory"].append({"itemId": "wpn_sword_regular", "count": 1})
        initial_gold = state["player"]["gold"]

        new_state, events = trade.sell_item(
            state, "npc_blacksmith_kolm", "wpn_sword_regular", 1, _game_data
        )

        assert events[0]["id"] == "item_sold"
        # sellPrice = 7
        assert events[0]["goldEarned"] == 7
        assert new_state["player"]["gold"] == initial_gold + 7

    def test_sell_not_enough_items(self):
        """Продажа при отсутствии предмета."""
        state = _make_state()
        new_state, events = trade.sell_item(
            state, "npc_merchant_ganna", "nonexistent_item", 1, _game_data
        )
        assert events[0]["id"] == "err_not_enough_items"

    def test_sell_in_combat(self):
        """Продажа в бою запрещена."""
        state = _make_state(world={"inCombat": True})
        state["player"]["inventory"].append({"itemId": "food_berries", "count": 1})
        new_state, events = trade.sell_item(
            state, "npc_merchant_ganna", "food_berries", 1, _game_data
        )
        assert events[0]["id"] == "err_in_combat"

    def test_sell_npc_not_trader(self):
        """elder_miroslav не торгует."""
        state = _make_state()
        state["player"]["inventory"].append({"itemId": "food_berries", "count": 1})
        new_state, events = trade.sell_item(
            state, "npc_elder_miroslav", "food_berries", 1, _game_data
        )
        assert events[0]["id"] == "err_npc_not_trader"

    def test_sell_npc_not_here(self):
        """Продажа при отсутствии NPC."""
        state = _make_wild_state()
        state["player"]["inventory"].append({"itemId": "food_berries", "count": 1})
        new_state, events = trade.sell_item(
            state, "npc_merchant_ganna", "food_berries", 1, _game_data
        )
        assert events[0]["id"] == "err_npc_not_here"


# ---------------------------------------------------------------------------
# E. Сервисы деревни
# ---------------------------------------------------------------------------


class TestSmithRepair:
    """Критерий приёмки 4: use_smith_repair работает только при наличии Колма."""

    def test_smith_repair_with_kolm(self):
        """Ремонт работает при наличии Колма в деревне."""
        state = _make_state(player={"gold": 100})
        # Надеваем wpn_sword_fine и ломаем
        state["player"]["inventory"].append({"itemId": "wpn_sword_fine", "count": 1})
        state, _ = __import__("engine.inventory", fromlist=["equip_item"]).equip_item(
            state, len(state["player"]["inventory"]) - 1, _game_data
        )
        state["player"]["equipment"]["weapon"]["durability"]["current"] = 0

        new_state, events = trade.use_smith_repair(state, "weapon", _game_data)
        assert events[0]["id"] == "smith_repaired"
        assert new_state["player"]["equipment"]["weapon"]["durability"]["current"] == 55

    def test_smith_repair_npc_not_here(self):
        """Ремонт вне деревни возвращает err_npc_not_here."""
        state = _make_wild_state()
        new_state, events = trade.use_smith_repair(state, "weapon", _game_data)
        assert events[0]["id"] == "err_npc_not_here"

    def test_smith_repair_hated_refuses(self):
        """При hated репутации Колм отказывает в ремонте."""
        state = _make_state(
            player={"gold": 100},
            npcs={
                "npc_blacksmith_kolm": {
                    "mood": "neutral", "reputation": "hated", "met": False,
                },
            },
        )
        new_state, events = trade.use_smith_repair(state, "weapon", _game_data)
        assert events[0]["id"] == "err_npc_refuses_service"


class TestInnRest:
    """Критерий приёмки 4: use_inn_rest работает только при наличии Бориса."""

    def test_inn_rest_with_boris(self):
        """Ночлег работает при наличии Бориса."""
        state = _make_state(
            player={"gold": 100},
            world={"stepOfDay": 10, "day": 1, "fedMorning": False, "fedEvening": False},
        )
        state["player"]["resources"]["hp"]["current"] = 5
        state["player"]["resources"]["mp"]["current"] = 1

        new_state, events = trade.use_inn_rest(state, _game_data)

        assert events[0]["id"] == "inn_rested"
        assert events[0]["cost"] == 5
        assert new_state["player"]["gold"] == 95
        # Время перематывается на следующее утро
        assert new_state["world"]["stepOfDay"] == 1
        assert new_state["world"]["day"] == 2

    def test_inn_rest_npc_not_here(self):
        """Ночлег вне деревни возвращает err_npc_not_here."""
        state = _make_wild_state()
        new_state, events = trade.use_inn_rest(state, _game_data)
        assert events[0]["id"] == "err_npc_not_here"

    def test_inn_rest_hated_refuses(self):
        """При hated репутации Борис отказывает в ночлеге."""
        state = _make_state(
            player={"gold": 100},
            npcs={
                "npc_innkeeper_boris": {
                    "mood": "neutral", "reputation": "hated", "met": False,
                },
            },
        )
        new_state, events = trade.use_inn_rest(state, _game_data)
        assert events[0]["id"] == "err_npc_refuses_service"

    def test_inn_rest_not_enough_gold(self):
        """Ночлег при нехватке золота."""
        state = _make_state(player={"gold": 3})
        new_state, events = trade.use_inn_rest(state, _game_data)
        assert events[0]["id"] == "err_not_enough_gold"
        assert events[0]["required"] == 5


# ---------------------------------------------------------------------------
# F. shift_reputation
# ---------------------------------------------------------------------------


class TestShiftReputation:
    """Тесты функции сдвига репутации."""

    def test_shift_up(self):
        """Сдвиг репутации вверх."""
        state = _make_state(npcs={
            "npc_merchant_ganna": {"mood": "neutral", "reputation": "neutral", "met": False},
        })
        new_rep = trade.shift_reputation(state, "npc_merchant_ganna", 1)
        assert new_rep == "friendly"
        assert state["npcs"]["npc_merchant_ganna"]["reputation"] == "friendly"

    def test_shift_down(self):
        """Сдвиг репутации вниз."""
        state = _make_state(npcs={
            "npc_merchant_ganna": {"mood": "neutral", "reputation": "neutral", "met": False},
        })
        new_rep = trade.shift_reputation(state, "npc_merchant_ganna", -1)
        assert new_rep == "hostile"

    def test_shift_clamp_max(self):
        """Кламп на максимальном уровне."""
        state = _make_state(npcs={
            "npc_merchant_ganna": {"mood": "neutral", "reputation": "honored", "met": False},
        })
        new_rep = trade.shift_reputation(state, "npc_merchant_ganna", 1)
        assert new_rep == "honored"

    def test_shift_clamp_min(self):
        """Кламп на минимальном уровне."""
        state = _make_state(npcs={
            "npc_merchant_ganna": {"mood": "neutral", "reputation": "hated", "met": False},
        })
        new_rep = trade.shift_reputation(state, "npc_merchant_ganna", -1)
        assert new_rep == "hated"

    def test_shift_large_delta(self):
        """Большой сдвиг с клампом."""
        state = _make_state(npcs={
            "npc_merchant_ganna": {"mood": "neutral", "reputation": "neutral", "met": False},
        })
        new_rep = trade.shift_reputation(state, "npc_merchant_ganna", 10)
        assert new_rep == "honored"

        state = _make_state(npcs={
            "npc_merchant_ganna": {"mood": "neutral", "reputation": "neutral", "met": False},
        })
        new_rep = trade.shift_reputation(state, "npc_merchant_ganna", -10)
        assert new_rep == "hated"


# ---------------------------------------------------------------------------
# G. Цена продажи предметов с sellPrice = 0
# ---------------------------------------------------------------------------


class TestZeroSellPrice:
    """Тесты продажи предметов с sellPrice = 0."""

    def test_sell_moss_zero_price(self):
        """Продажа mоха (sellPrice=0) возвращает 0."""
        npc_state = {"reputation": "neutral"}
        item_data = _game_data.get_item("food_moss")
        price = trade.get_sell_price(item_data, npc_state)
        assert price == 0

    def test_sell_berries_zero_price(self):
        """Продажа ягод (sellPrice=0) возвращает 0."""
        npc_state = {"reputation": "neutral"}
        item_data = _game_data.get_item("food_berries")
        price = trade.get_sell_price(item_data, npc_state)
        assert price == 0

    def test_buy_zero_price_item(self):
        """Покупка предмета с buyPrice=0 возвращает 0."""
        # Все предметы должны иметь buyPrice > 0, но проверяем edge case
        item_data = {"economy": {"buyPrice": 0, "sellPrice": 0, "canBuy": True}}
        npc_state = {"reputation": "neutral"}
        price = trade.get_buy_price(item_data, npc_state)
        assert price == 0


# ---------------------------------------------------------------------------
# H. Camp NPC trading
# ---------------------------------------------------------------------------


class TestCampTrading:
    """Тесты торговли в лагере."""

    def test_camp_only_assigned_npc_tradable(self):
        """В лагере можно торговать только с назначенным NPC."""
        state = _make_camp_state("npc_hunter_rask")
        state["player"]["inventory"].append({"itemId": "food_berries", "count": 1})

        # Раск доступен
        assert trade.is_npc_present(state, "npc_hunter_rask") is True
        # Ганна недоступна
        assert trade.is_npc_present(state, "npc_merchant_ganna") is False

    def test_camp_buy_from_assigned_npc(self):
        """Покупка у назначенного NPC в лагере."""
        state = _make_camp_state("npc_hunter_rask")
        state["player"]["gold"] = 100
        state["player"]["inventory"].append({"itemId": "food_bread", "count": 1})

        # elx_accuracy продаётся Раском
        new_state, events = trade.buy_item(
            state, "npc_hunter_rask", "elx_accuracy", 1, _game_data
        )
        assert events[0]["id"] == "item_bought"

    def test_camp_buy_from_non_present_npc(self):
        """Покупка у неназначенного NPC в лагере отклоняется."""
        state = _make_camp_state("npc_hunter_rask")
        state["player"]["inventory"].append({"itemId": "food_bread", "count": 1})

        new_state, events = trade.buy_item(
            state, "npc_merchant_ganna", "food_bread", 1, _game_data
        )
        assert events[0]["id"] == "err_npc_not_here"
