"""Константы прогрессии, сложности и имён файлов."""

from typing import Final

# Версия схемы состояния
SCHEMA_VERSION: Final[int] = 1

# Пути по умолчанию
DEFAULT_SESSION_PATH: Final[str] = "state_session.json"
DEFAULT_TEMPLATE_PATH: Final[str] = "state_template.json"

# Прогрессия персонажа
LEVEL_MIN: Final[int] = 1
LEVEL_MAX: Final[int] = 20

ATTR_MIN: Final[int] = 1
ATTR_MAX: Final[int] = 10

SKILL_MIN: Final[int] = 0
SKILL_MAX: Final[int] = 10

STARTING_UNSPENT_ATTR_POINTS: Final[int] = 3
MAX_START_ATTR_BONUS: Final[int] = 2  # на 1-м уровне атрибут не выше 3

# Канонические ключи
ATTRIBUTES: Final[tuple[str, ...]] = (
    "strength",
    "agility",
    "constitution",
    "intelligence",
    "wisdom",
)

SKILLS: Final[tuple[str, ...]] = (
    "melee_heavy",
    "melee_light",
    "armor_mastery",
    "pyromancy",
    "restoration",
    "hexes",
    "alchemy",
    "crafting",
    "scavenging",
)

# Множители сложности
DIFFICULTY_MULTIPLIERS: Final[dict[str, float]] = {
    "easy": 0.75,
    "normal": 1.0,
    "hard": 1.4,
    "impossible": 2.0,
}

DEFAULT_DIFFICULTY: Final[str] = "normal"
