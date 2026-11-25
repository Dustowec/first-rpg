import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def clean_entity(entity: dict) -> dict:
    """Удаляет служебные поля, добавленные data_loader."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def main() -> None:
    json_files = sorted(DATA_DIR.rglob("*.json"))
    if not json_files:
        print("JSON-файлы не найдены в data/", file=sys.stderr)
        sys.exit(1)

    count_by_dir: dict[str, int] = {}
    for path in json_files:
        with open(path, "r", encoding="utf-8") as f:
            entity = json.load(f)

        cleaned = clean_entity(entity)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
            f.write("\n")

        dir_name = path.parent.name
        count_by_dir[dir_name] = count_by_dir.get(dir_name, 0) + 1

    total = sum(count_by_dir.values())
    print(f"Generated {total} JSON files:")
    for d, c in sorted(count_by_dir.items()):
        print(f"  {d}/: {c}")


if __name__ == "__main__":
    main()