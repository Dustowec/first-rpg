"""Заглушка точки входа."""

from .engine.storage import new_game


def main() -> None:
    """Запуск новой игры."""
    state = new_game()
    print(f"Новая игра создана. seed={state['meta']['seed']}")


if __name__ == "__main__":
    main()
