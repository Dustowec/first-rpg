"""Тесты для Блока 2.1: Прогрессия персонажа, атрибуты, навыки и реестр вех."""

import pytest

from engine.progression import (
    calc_max_hp,
    calc_max_mp,
    xp_to_next_level,
    sync_derived_resources,
    allocate_attribute,
    allocate_skill,
    grant_xp,
    has_milestone,
    # melee_heavy perks
    has_stunning_blow,
    has_armor_sunder,
    has_crushing_strike,
    # melee_light perks
    has_lunge,
    has_long_reach,
    has_deadly_precision,
    # armor_mastery perks
    has_armor_comfort,
    has_tempering,
    has_unbreakable,
    # pyromancy perks
    has_intense_heat,
    has_concentration,
    has_elemental_breakthrough,
    # restoration perks
    has_frugality,
    has_sturdy_barrier,
    has_second_wind,
    # hexes perks
    has_caustic_toxins,
    has_withering,
    has_soul_harvest,
    # alchemy perks
    has_herbalist,
    has_thrifty_alchemist,
    has_double_dose,
    # crafting perks
    has_field_sharpening,
    has_repair_master,
    has_reinforcement,
    # scavenging perks
    has_keen_eye,
    has_tight_belt,
    has_treasure_sense,
)
from engine.models import create_default_player


# ---------------------------------------------------------------------------
# 1. Тесты формул (xp_to_next_level, calc_max_hp, calc_max_mp)
# ---------------------------------------------------------------------------


class TestFormulas:
    def test_xp_to_next_level_table(self):
        """Проверка таблицы xp_to_next_level для уровней 1, 2, 10, 19."""
        assert xp_to_next_level(1) == 50
        assert xp_to_next_level(2) == 127
        assert xp_to_next_level(10) == 1119
        assert xp_to_next_level(19) == 2662

    def test_xp_to_next_level_cap_20(self):
        """xp_to_next_level возвращает None на уровне 20."""
        assert xp_to_next_level(20) is None
        assert xp_to_next_level(25) is None

    def test_calc_max_hp_boundary_points(self):
        """Проверка граничных точек calc_max_hp."""
        # level=1, con=1 -> 10
        assert calc_max_hp(1, 1) == 10
        # level=20, con=1 -> 48
        assert calc_max_hp(20, 1) == 48
        # level=20, con=10 -> 66
        assert calc_max_hp(20, 10) == 66

    def test_calc_max_mp_boundary_points(self):
        """Проверка граничных точек calc_max_mp."""
        # level=1, wis=1 -> 2
        assert calc_max_mp(1, 1) == 2
        # level=20, wis=1 -> 21
        assert calc_max_mp(20, 1) == 21
        # level=20, wis=10 -> 39
        assert calc_max_mp(20, 10) == 39

    def test_sync_derived_resources_restore(self):
        """При повышении кон/вис current восстанавливается на разницу max."""
        player = create_default_player()
        # Начальное: level=1, con=1 -> max_hp=10, current=10
        assert player["resources"]["hp"]["max"] == 10
        assert player["resources"]["hp"]["current"] == 10

        # Повышаем constitution до 5
        player["attributes"]["constitution"] = 5
        sync_derived_resources(player, restore_delta=True)

        # new_max_hp = 10 + 0*2 + 4*2 = 18
        assert player["resources"]["hp"]["max"] == 18
        # current должен увеличиться на delta = 8
        assert player["resources"]["hp"]["current"] == 18

    def test_sync_derived_resources_no_restore(self):
        """При restore_delta=False current не меняется."""
        player = create_default_player()
        player["resources"]["hp"]["current"] = 5  # Уменьшаем current
        player["attributes"]["constitution"] = 5

        sync_derived_resources(player, restore_delta=False)

        assert player["resources"]["hp"]["max"] == 18
        # current остаётся 5 (не восстанавливается)
        assert player["resources"]["hp"]["current"] == 5

    def test_sync_derived_resources_clamp(self):
        """current клампит в [0, new_max]."""
        player = create_default_player()
        player["resources"]["hp"]["current"] = 100  # Больше max
        sync_derived_resources(player, restore_delta=True)

        assert player["resources"]["hp"]["current"] == player["resources"]["hp"]["max"]


# ---------------------------------------------------------------------------
# 2. Тесты распределения атрибутов
# ---------------------------------------------------------------------------


class TestAllocateAttribute:
    def _make_state(self, **overrides):
        """Создаёт тестовое состояние с player."""
        player = create_default_player()
        player.update(overrides)
        return {"player": player, "meta": {}}

    def test_allocate_attribute_success(self):
        """Успешное распределение атрибута."""
        state = self._make_state()
        new_state, events = allocate_attribute(state, "strength")

        assert new_state["player"]["attributes"]["strength"] == 2
        assert new_state["player"]["unspentPoints"]["attributes"] == 2
        assert events[0]["id"] == "attr_increased"
        assert events[0]["value"] == 2

    def test_allocate_attribute_no_points(self):
        """Нет очков — возвращается ошибка."""
        state = self._make_state(unspentPoints={"attributes": 0, "skills": 0})
        new_state, events = allocate_attribute(state, "strength")

        assert events[0]["id"] == "err_no_attribute_points"
        assert new_state["player"]["attributes"]["strength"] == 1

    def test_allocate_attribute_cap_10(self):
        """Кап 10 — нельзя поднять выше."""
        player = create_default_player()
        player["attributes"]["strength"] = 10
        player["unspentPoints"]["attributes"] = 5
        state = {"player": player, "meta": {}}

        new_state, events = allocate_attribute(state, "strength")
        assert events[0]["id"] == "err_attribute_max"

    def test_creation_attr_cap_3(self):
        """is_creation=True: нельзя поднять стат выше 3."""
        state = self._make_state()

        # Поднимаем strength до 3 — OK
        new_state, events = allocate_attribute(state, "strength", is_creation=True)
        assert events[0]["id"] == "attr_increased"
        assert new_state["player"]["attributes"]["strength"] == 2

        # Поднимаем strength до 3 — OK
        new_state, events = allocate_attribute(new_state, "strength", is_creation=True)
        assert events[0]["id"] == "attr_increased"
        assert new_state["player"]["attributes"]["strength"] == 3

        # Поднимаем strength до 4 — ошибка
        new_state, events = allocate_attribute(new_state, "strength", is_creation=True)
        assert events[0]["id"] == "err_creation_attr_cap"
        assert new_state["player"]["attributes"]["strength"] == 3

    def test_creation_can_distribute_3_2_1(self):
        """Можно распределить 3+2+1 или 2+2+2."""
        state = self._make_state()

        # 3 в strength, 2 в agility, 1 в constitution = 6 очков, но у нас только 3
        # Поэтому: 2 в strength, 1 в agility = 3 очка
        new_state, events = allocate_attribute(state, "strength", is_creation=True)
        assert new_state["player"]["attributes"]["strength"] == 2

        new_state, events = allocate_attribute(new_state, "agility", is_creation=True)
        assert new_state["player"]["attributes"]["agility"] == 2

        # unspentPoints должно быть 1
        assert new_state["player"]["unspentPoints"]["attributes"] == 1

    def test_allocate_attribute_invalid(self):
        """Невалидный attr_id — ошибка."""
        state = self._make_state()
        new_state, events = allocate_attribute(state, "nonexistent_attr")

        assert events[0]["id"] == "err_invalid_attribute"

    def test_allocate_attribute_restores_hp(self):
        """При распределении constitution восстанавливается HP."""
        state = self._make_state()
        initial_max_hp = state["player"]["resources"]["hp"]["max"]

        new_state, events = allocate_attribute(state, "constitution")

        assert new_state["player"]["resources"]["hp"]["max"] > initial_max_hp
        assert new_state["player"]["resources"]["hp"]["current"] == new_state["player"]["resources"]["hp"]["max"]


# ---------------------------------------------------------------------------
# 3. Тесты распределения навыков
# ---------------------------------------------------------------------------


class TestAllocateSkill:
    def _make_state(self, skill_points: int = 0):
        """Создаёт тестовое состояние с player."""
        player = create_default_player()
        player["unspentPoints"]["skills"] = skill_points
        return {"player": player, "meta": {}}

    def test_allocate_skill_success(self):
        """Успешное распределение навыка."""
        state = self._make_state(skill_points=1)
        new_state, events = allocate_skill(state, "melee_heavy")

        assert new_state["player"]["skills"]["melee_heavy"] == 1
        assert new_state["player"]["unspentPoints"]["skills"] == 0
        assert events[-1]["id"] == "skill_increased"

    def test_allocate_skill_no_points(self):
        """Нет очков — ошибка."""
        state = self._make_state(skill_points=0)
        new_state, events = allocate_skill(state, "melee_heavy")

        assert events[0]["id"] == "err_no_skill_points"

    def test_allocate_skill_cap_10(self):
        """Кап 10 — нельзя поднять выше."""
        player = create_default_player()
        player["skills"]["melee_heavy"] = 10
        player["unspentPoints"]["skills"] = 5
        state = {"player": player, "meta": {}}

        new_state, events = allocate_skill(state, "melee_heavy")
        assert events[0]["id"] == "err_skill_max"

    def test_allocate_skill_invalid(self):
        """Невалидный skill_id — ошибка."""
        state = self._make_state()
        new_state, events = allocate_skill(state, "nonexistent_skill")

        assert events[0]["id"] == "err_invalid_skill"

    def test_perk_unlocked_at_3(self):
        """Событие perk_unlocked на уровне 3 навыка."""
        state = self._make_state(skill_points=3)
        player = state["player"]
        player["skills"]["melee_heavy"] = 2

        new_state, events = allocate_skill(state, "melee_heavy")

        assert any(e["id"] == "perk_unlocked" for e in events)
        perk_event = [e for e in events if e["id"] == "perk_unlocked"][0]
        assert perk_event["skill"] == "melee_heavy"
        assert perk_event["level"] == 3

    def test_perk_unlocked_at_6(self):
        """Событие perk_unlocked на уровне 6 навыка."""
        state = self._make_state(skill_points=4)
        player = state["player"]
        player["skills"]["pyromancy"] = 5

        new_state, events = allocate_skill(state, "pyromancy")

        assert any(e["id"] == "perk_unlocked" for e in events)
        perk_event = [e for e in events if e["id"] == "perk_unlocked"][0]
        assert perk_event["level"] == 6

    def test_perk_unlocked_at_10(self):
        """Событие perk_unlocked на уровне 10 навыка."""
        state = self._make_state(skill_points=5)
        player = state["player"]
        player["skills"]["scavenging"] = 9

        new_state, events = allocate_skill(state, "scavenging")

        assert any(e["id"] == "perk_unlocked" for e in events)
        perk_event = [e for e in events if e["id"] == "perk_unlocked"][0]
        assert perk_event["level"] == 10


# ---------------------------------------------------------------------------
# 4. Тесты опыта и Level-Up
# ---------------------------------------------------------------------------


class TestGrantXp:
    def _make_state(self, level: int = 1, xp: int = 0, meta: dict | None = None):
        """Создаёт тестовое состояние."""
        player = create_default_player()
        player["level"] = level
        player["xp"] = xp
        return {"player": player, "meta": meta or {}}

    def test_grant_xp_single_level(self):
        """Обычный левел-ап за один пакет XP."""
        state = self._make_state(level=1, xp=0)

        # Нужно 50 XP для перехода на уровень 2
        new_state, events = grant_xp(state, 50)

        assert new_state["player"]["level"] == 2
        assert new_state["player"]["xp"] == 0
        assert new_state["player"]["unspentPoints"]["attributes"] == 4  # 3+1
        assert new_state["player"]["unspentPoints"]["skills"] == 1  # 0+1
        assert any(e["id"] == "level_up" for e in events)
        assert any(e["id"] == "xp_gained" for e in events)

    def test_grant_xp_multi_levelup(self):
        """+200 XP на 1-м уровне сразу поднимает до 3-го уровня."""
        state = self._make_state(level=1, xp=0)

        # Уровень 1->2: нужно 50 XP, остаётся 150
        # Уровень 2->3: нужно 127 XP, остаётся 23
        new_state, events = grant_xp(state, 200)

        assert new_state["player"]["level"] == 3
        assert new_state["player"]["xp"] == 23
        # +2 очка атрибутов и навыков (за 2 левела)
        assert new_state["player"]["unspentPoints"]["attributes"] == 5  # 3+2
        assert new_state["player"]["unspentPoints"]["skills"] == 2  # 0+2

        # Два события level_up
        level_up_events = [e for e in events if e["id"] == "level_up"]
        assert len(level_up_events) == 2
        assert level_up_events[0]["level"] == 2
        assert level_up_events[1]["level"] == 3

    def test_grant_xp_cap_20(self):
        """Остановка на капе 20 уровня, xp=0."""
        state = self._make_state(level=19, xp=0)

        # Нужно 2662 XP для перехода на 20
        new_state, events = grant_xp(state, 3000)

        assert new_state["player"]["level"] == 20
        assert new_state["player"]["xp"] == 0  # Обнуляется на 20 уровне
        assert any(e["id"] == "level_up" for e in events)

    def test_grant_xp_no_gain_at_20(self):
        """Уровень 20 — опыт не начисляется."""
        state = self._make_state(level=20, xp=0)

        new_state, events = grant_xp(state, 1000)

        assert new_state["player"]["level"] == 20
        assert new_state["player"]["xp"] == 0
        assert events == []  # Нет событий

    def test_grant_xp_xp_rate(self):
        """Настраиваемый множитель XP."""
        state = self._make_state(level=1, xp=0, meta={"xpRate": 2.0})

        # base_xp=25, rate=2.0 -> gained=50 -> ровно на уровень 2
        new_state, events = grant_xp(state, 25)

        assert new_state["player"]["level"] == 2
        xp_gained_events = [e for e in events if e["id"] == "xp_gained"]
        assert xp_gained_events[0]["amount"] == 50

    def test_grant_xp_partial(self):
        """Недостаточно XP для левела — просто прибавляется."""
        state = self._make_state(level=1, xp=0)

        # Нужно 50, даём 30
        new_state, events = grant_xp(state, 30)

        assert new_state["player"]["level"] == 1
        assert new_state["player"]["xp"] == 30
        assert any(e["id"] == "xp_gained" for e in events)
        # Нет level_up событий
        assert not any(e["id"] == "level_up" for e in events)


# ---------------------------------------------------------------------------
# 5. Тесты вех (перков)
# ---------------------------------------------------------------------------


class TestMilestones:
    def _make_player(self, skills: dict | None = None):
        """Создаёт игрока с заданными навыками."""
        player = create_default_player()
        if skills:
            player["skills"].update(skills)
        return player

    def test_has_milestone_true(self):
        """has_milestone возвращает True при достижении порога."""
        player = self._make_player({"melee_heavy": 5})
        assert has_milestone(player, "melee_heavy", 3) is True
        assert has_milestone(player, "melee_heavy", 6) is False

    def test_has_milestone_false(self):
        """has_milestone возвращает False при недостижении порога."""
        player = self._make_player({"melee_heavy": 2})
        assert has_milestone(player, "melee_heavy", 3) is False

    def test_has_milestone_default_zero(self):
        """Если навык не указан, считается 0."""
        player = self._make_player()
        assert has_milestone(player, "melee_heavy", 3) is False

    def test_all_perk_flags_melee_heavy(self):
        """3 флага для melee_heavy."""
        player = self._make_player({"melee_heavy": 10})
        assert has_stunning_blow(player) is True
        assert has_armor_sunder(player) is True
        assert has_crushing_strike(player) is True

        player_low = self._make_player({"melee_heavy": 1})
        assert has_stunning_blow(player_low) is False
        assert has_armor_sunder(player_low) is False
        assert has_crushing_strike(player_low) is False

    def test_all_perk_flags_all_skills(self):
        """Проверка хотя бы 2 навыков со всеми флагами."""
        player = self._make_player({
            "melee_light": 10,
            "armor_mastery": 10,
        })

        # melee_light
        assert has_lunge(player) is True
        assert has_long_reach(player) is True
        assert has_deadly_precision(player) is True

        # armor_mastery
        assert has_armor_comfort(player) is True
        assert has_tempering(player) is True
        assert has_unbreakable(player) is True

    def test_all_27_perk_getters_exist(self):
        """Все 27 геттеров вех существуют и вызываются."""
        player = self._make_player({
            "melee_heavy": 10,
            "melee_light": 10,
            "armor_mastery": 10,
            "pyromancy": 10,
            "restoration": 10,
            "hexes": 10,
            "alchemy": 10,
            "crafting": 10,
            "scavenging": 10,
        })

        # melee_heavy (3)
        assert has_stunning_blow(player)
        assert has_armor_sunder(player)
        assert has_crushing_strike(player)

        # melee_light (3)
        assert has_lunge(player)
        assert has_long_reach(player)
        assert has_deadly_precision(player)

        # armor_mastery (3)
        assert has_armor_comfort(player)
        assert has_tempering(player)
        assert has_unbreakable(player)

        # pyromancy (3)
        assert has_intense_heat(player)
        assert has_concentration(player)
        assert has_elemental_breakthrough(player)

        # restoration (3)
        assert has_frugality(player)
        assert has_sturdy_barrier(player)
        assert has_second_wind(player)

        # hexes (3)
        assert has_caustic_toxins(player)
        assert has_withering(player)
        assert has_soul_harvest(player)

        # alchemy (3)
        assert has_herbalist(player)
        assert has_thrifty_alchemist(player)
        assert has_double_dose(player)

        # crafting (3)
        assert has_field_sharpening(player)
        assert has_repair_master(player)
        assert has_reinforcement(player)

        # scavenging (3)
        assert has_keen_eye(player)
        assert has_tight_belt(player)
        assert has_treasure_sense(player)
