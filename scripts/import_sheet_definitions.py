from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path, PurePosixPath


TERMINAL_DIRS = {
    # body type variants
    "male",
    "thin",
    "female",
    "muscular",
    "pregnant",
    "teen",
    # age variants
    "adult",
    "child",
    # layer depth variants
    "bg",
    "fg",
    "mg",  # middle-ground, used by relm_ponytail
    # sub-body/orientation variants
    "universal",
    "skin",
    "adult_back",
    "adult_front",
}

PNG_SUFFIX = ".png"


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parent
    default_source = repo_root.parent / "Universal-LPC-Spritesheet-Character-Generator" / "sheet_definitions"
    default_target = repo_root / "characters"

    parser = argparse.ArgumentParser(
        description="Import ULPC sheet definition JSON files into the local LPC asset repo."
    )
    parser.add_argument("--source", type=Path, default=default_source, help="Source sheet_definitions directory")
    parser.add_argument("--target", type=Path, default=default_target, help="Target characters directory")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing local JSON files. Disabled by default to protect local edits.",
    )
    parser.add_argument(
        "--no-stubs",
        action="store_true",
        help="Skip generating local stub JSON files for unmatched assets.",
    )
    return parser.parse_args()


def iter_source_json_files(source_root: Path) -> list[Path]:
    return sorted(
        path
        for path in source_root.rglob("*.json")
        if path.is_file() and not path.name.startswith("meta_")
    )


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def extract_layer_paths(data: dict) -> list[str]:
    layer_paths: list[str] = []
    for key, value in data.items():
        if not key.startswith("layer_") or not isinstance(value, dict):
            continue
        for layer_key, layer_value in value.items():
            if layer_key == "zPos" or not isinstance(layer_value, str):
                continue
            layer_paths.append(layer_value)
    return layer_paths


def split_posix_dir(path_value: str) -> list[str]:
    return [part for part in PurePosixPath(path_value).parts if part not in {"", "/"}]


def common_parts(paths: list[list[str]]) -> list[str]:
    if not paths:
        return []
    prefix: list[str] = []
    for parts in zip(*paths):
        if len(set(parts)) != 1:
            break
        prefix.append(parts[0])
    return prefix


def strip_terminal_parts(parts: list[str]) -> list[str]:
    trimmed = list(parts)
    while trimmed and trimmed[-1] in TERMINAL_DIRS:
        trimmed.pop()
    return trimmed


def resolve_item_dir_from_json(data: dict) -> Path | None:
    layer_paths = extract_layer_paths(data)
    if not layer_paths:
        return None
    path_parts = [split_posix_dir(path_value) for path_value in layer_paths]
    common = common_parts(path_parts)
    trimmed = strip_terminal_parts(common)
    if not trimmed:
        return None
    return Path(*trimmed)


def has_direct_pngs(path: Path) -> bool:
    return any(child.is_file() and child.suffix.lower() == PNG_SUFFIX for child in path.iterdir())


def direct_child_dirs(path: Path) -> list[Path]:
    return sorted(child for child in path.iterdir() if child.is_dir())


def _collect_item_dirs(path: Path, item_dirs: list[Path]) -> None:
    """Recursively walk directories, collecting item-level dirs.

    Rules:
    - Skip any directory whose own name is a terminal name (we never classify
      the terminal dirs themselves as item dirs).
    - A directory is an item dir if it directly contains PNG files.
    - A directory is an item dir if ALL of its direct child directories have
      terminal names.  Once we identify it as an item dir we stop descending
      into it (the children are just body/age/layer variants, not items).
    - Otherwise, recurse into non-terminal child directories.
    """
    if path.name in TERMINAL_DIRS:
        return

    children = direct_child_dirs(path)

    if has_direct_pngs(path):
        item_dirs.append(path)
        return

    if children and all(c.name in TERMINAL_DIRS for c in children):
        item_dirs.append(path)
        return

    for child in children:
        _collect_item_dirs(child, item_dirs)


def iter_item_dirs(characters_root: Path) -> list[Path]:
    item_dirs: list[Path] = []
    for child in sorted(characters_root.iterdir()):
        if child.is_dir():
            _collect_item_dirs(child, item_dirs)
    return item_dirs


def choose_stub_name(item_dir: Path) -> str:
    return f"{item_dir.name}.stub.json"


def relative_posix_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix() + "/"


def build_stub_content(item_dir: Path, characters_root: Path) -> dict:
    children = direct_child_dirs(item_dir)
    layer: dict[str, object] = {"zPos": 0}

    if children and all(child.name in TERMINAL_DIRS for child in children):
        for child in children:
            layer[child.name] = relative_posix_path(child, characters_root)
    else:
        layer["universal"] = relative_posix_path(item_dir, characters_root)

    return {
        "name": f"TODO: {item_dir.name}",
        "layer_1": layer,
        "animations": [],
        "credits": [],
        "type_name": "TODO",
        "notes": [
            "Generated local stub because no matching ULPC sheet definition JSON was found.",
            "Fill in metadata and any future prerequisites/layers manually.",
        ],
    }


def write_stub_json(path: Path, content: dict) -> None:
    path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    source_root = args.source.resolve()
    target_root = args.target.resolve()

    if not source_root.exists():
        raise FileNotFoundError(f"Source directory not found: {source_root}")
    if not target_root.exists():
        raise FileNotFoundError(f"Target directory not found: {target_root}")

    copied: list[str] = []
    skipped_existing: list[str] = []
    unmatched_source: list[str] = []
    unreadable_source: list[str] = []

    for source_json in iter_source_json_files(source_root):
        try:
            data = load_json(source_json)
            item_dir = resolve_item_dir_from_json(data)
        except Exception as exc:  # pragma: no cover - defensive reporting
            unreadable_source.append(f"{source_json.relative_to(source_root).as_posix()} ({exc})")
            continue

        if item_dir is None:
            unreadable_source.append(
                f"{source_json.relative_to(source_root).as_posix()} (no usable layer paths)"
            )
            continue

        target_dir = target_root / item_dir
        if not target_dir.is_dir():
            unmatched_source.append(f"{source_json.relative_to(source_root).as_posix()} -> {item_dir.as_posix()}")
            continue

        target_json = target_dir / source_json.name
        relative_target = target_json.relative_to(target_root).as_posix()
        if target_json.exists() and not args.overwrite:
            skipped_existing.append(relative_target)
            continue

        shutil.copyfile(source_json, target_json)
        copied.append(relative_target)

    stubbed: list[str] = []
    if not args.no_stubs:
        for item_dir in iter_item_dirs(target_root):
            existing_jsons = sorted(child for child in item_dir.iterdir() if child.is_file() and child.suffix.lower() == ".json")
            if existing_jsons:
                continue
            stub_path = item_dir / choose_stub_name(item_dir)
            if stub_path.exists() and not args.overwrite:
                skipped_existing.append(stub_path.relative_to(target_root).as_posix())
                continue
            stub_content = build_stub_content(item_dir, target_root)
            write_stub_json(stub_path, stub_content)
            stubbed.append(stub_path.relative_to(target_root).as_posix())

    print(f"Copied {len(copied)} ULPC JSON files.")
    print(f"Generated {len(stubbed)} stub JSON files.")
    print(f"Skipped {len(skipped_existing)} existing JSON files.")
    print(f"Unmatched source JSON files: {len(unmatched_source)}")
    print(f"Unreadable source JSON files: {len(unreadable_source)}")

    if copied:
        print("\nCopied files:")
        for entry in copied:
            print(f"  {entry}")

    if stubbed:
        print("\nStub files:")
        for entry in stubbed:
            print(f"  {entry}")

    if skipped_existing:
        print("\nSkipped existing files:")
        for entry in skipped_existing:
            print(f"  {entry}")

    if unmatched_source:
        print("\nSource JSON files with no matching local asset directory:")
        for entry in unmatched_source:
            print(f"  {entry}")

    if unreadable_source:
        print("\nUnreadable source JSON files:")
        for entry in unreadable_source:
            print(f"  {entry}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())