from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath


def get_parent_category(json_path: Path, characters_root: Path) -> str:
    """Infer category from parent directory structure."""
    rel = json_path.parent.relative_to(characters_root)
    parts = rel.parts
    
    if not parts:
        return "Unknown"
    
    if len(parts) >= 2:
        potential = parts[-2]
        return potential.capitalize()
    
    return parts[-1].capitalize()


def build_source_type_index(repo_root: Path) -> dict[str, list[str]]:
    """Index source type_name values by JSON filename stem."""
    index: dict[str, list[str]] = {}
    source_candidates = [
        repo_root.parent / "Universal-LPC-Spritesheet-Character-Generator" / "sheet_definitions",
        repo_root.parent / "Universal-LPC-Spritesheet-Character-Generator" / "resources" / "sheet_definitions",
    ]

    source_root = None
    for candidate in source_candidates:
        if candidate.exists() and candidate.is_dir():
            source_root = candidate
            break

    if source_root is None:
        return index

    for src_json in source_root.rglob("*.json"):
        try:
            with src_json.open("r", encoding="utf-8") as f:
                data = json.load(f)
            type_name = data.get("type_name")
            if not type_name:
                continue
            key = src_json.stem.lower()
            index.setdefault(key, [])
            if type_name not in index[key]:
                index[key].append(type_name)
        except Exception:
            continue

    return index


def build_source_definition_index(repo_root: Path) -> dict[str, dict]:
    """Index ULPC source definitions by JSON filename stem.

    The source repo still contains the original layer_* blocks we need to restore.
    """
    index: dict[str, dict] = {}
    source_candidates = [
        repo_root.parent / "Universal-LPC-Spritesheet-Character-Generator" / "sheet_definitions",
        repo_root.parent / "Universal-LPC-Spritesheet-Character-Generator" / "resources" / "sheet_definitions",
    ]

    source_root = None
    for candidate in source_candidates:
        if candidate.exists() and candidate.is_dir():
            source_root = candidate
            break

    if source_root is None:
        return index

    for src_json in source_root.rglob("*.json"):
        try:
            with src_json.open("r", encoding="utf-8") as f:
                data = json.load(f)
            index.setdefault(src_json.stem.lower(), data)
        except Exception:
            continue

    return index


SOURCE_DEFINITION_ALIASES = {
    "characters/torso/armour/chainmail/chainmail.json": "torso_chainmail",
    "characters/head/heads/human_child.json": "heads_human_child",
    "characters/head/heads/human_female.json": "heads_human_female",
    "characters/head/heads/human_male.json": "heads_human_male",
}


def resolve_category(
    json_path: Path,
    data: dict,
    characters_root: Path,
    source_type_index: dict[str, list[str]],
) -> str:
    """Resolve category while preserving/repairing existing values."""
    if data.get("type_name"):
        return data["type_name"]

    existing = data.get("category")
    # Keep existing if it already looks like a canonical machine category.
    if isinstance(existing, str) and existing and (existing.islower() or "_" in existing):
        return existing

    # Recover from ULPC source by filename when possible.
    key = json_path.stem.lower()
    source_types = source_type_index.get(key, [])
    if len(source_types) == 1:
        return source_types[0]

    if isinstance(existing, str) and existing:
        return existing

    return get_parent_category(json_path, characters_root)


def infer_recolors(json_path: Path, characters_root: Path, data: dict) -> dict | None:
    """Generate recolors based on asset type and path."""
    rel = json_path.parent.relative_to(characters_root)
    full_path = rel.as_posix().lower()
    name = data.get("name", "").lower()
    category = data.get("category", data.get("type_name", "")).lower()
    
    # Hair-based recolors (furry ears, tails, etc.)
    if any(x in full_path for x in ["ears", "tail", "furry", "hair"]):
        if "furry" in full_path or ("ears" in full_path and "furry" not in full_path):
            # Furry ears/tails use hair colors
            return {"material": "hair", "palettes": ["ulpc", "lpcr", "all.lpcr"]}
    
    # Metal/armor recolors
    if any(x in full_path for x in ["armour", "armor", "helm", "helmet", "weapon", "shield"]):
        if "armor" in name or "armour" in name or "mail" in name or "plate" in name or "helm" in name:
            return {"material": "metal", "palettes": ["ulpc", "lpcr", "all.lpcr"]}
    
    # Leather recolors
    if any(x in full_path for x in ["leather", "boots", "shoes", "sandal", "slipper"]):
        return {"material": "leather", "palettes": ["ulpc", "lpcr", "all.lpcr"]}
    
    # Cloth/textile recolors (default for most items)
    if any(x in full_path for x in ["dress", "clothes", "shirt", "pants", "legs", "torso", "apron", "cape", "hat", "cloak"]):
        return {"material": "cloth", "palettes": ["ulpc", "lpcr", "all.lpcr"]}
    
    # Skin tone recolors
    if "skin" in full_path:
        return {"material": "skin", "palettes": ["ulpc", "lpcr", "all.lpcr"]}
    
    # Default fallback for unmapped categories
    return {"material": "cloth", "palettes": ["ulpc", "lpcr", "all.lpcr"]}


def is_overlay_or_accessory(json_path: Path, data: dict) -> bool:
    """Detect if asset is an overlay/accessory that needs a prerequisite."""
    name = data.get("name", "").lower()
    type_name = data.get("type_name", "").lower()
    tags = [t.lower() for t in data.get("tags", [])]
    json_name = json_path.name.lower()
    
    overlay_keywords = {
        "sleeves", "trim", "cockade", "skull", "feather", "plumage", 
        "crest", "accessory", "knot", "buckle", "belt", "overskirt",
        "overlay", "clasp", "brooch", "pin", "clip", "patch", "badge"
    }
    
    combined_text = f"{name} {type_name} {' '.join(tags)} {json_name}"
    return any(kw in combined_text for kw in overlay_keywords)


def _read_asset_identity(json_file: Path) -> tuple[str | None, str | None]:
    """Read name/category from a JSON file safely."""
    try:
        with json_file.open("r", encoding="utf-8") as f:
            d = json.load(f)
        return d.get("name"), d.get("category", d.get("type_name"))
    except Exception:
        return None, None


def _unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for i in items:
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _find_parent_asset_ids(json_path: Path) -> list[str]:
    """Find likely prerequisite asset ids near this file.

    This intentionally returns filename stems, not display names.
    """
    results: list[str] = []

    parent_dir = json_path.parent.parent
    if not parent_dir.exists():
        return results

    for candidate in sorted(parent_dir.glob("*.json")):
        if candidate.name.endswith(".stub.json") or candidate == json_path:
            continue
        results.append(candidate.stem)

    for sub in ("base", "normal", "split"):
        subdir = parent_dir / sub
        if not subdir.exists() or not subdir.is_dir():
            continue
        for candidate in sorted(subdir.glob("*.json")):
            if candidate.name.endswith(".stub.json") or candidate == json_path:
                continue
            results.append(candidate.stem)

    return _unique_keep_order(results)


def _source_layers_to_refactored_layers(source_data: dict, json_path: Path, characters_root: Path) -> list[dict]:
    """Convert source layer_* blocks into refactored layer objects."""
    layers: list[dict] = []
    layer_index = 1

    json_dir = json_path.parent
    while True:
        layer_key = f"layer_{layer_index}"
        if layer_key not in source_data:
            break

        layer_data = source_data[layer_key]
        if not isinstance(layer_data, dict):
            layer_index += 1
            continue

        layer_obj = {
            "id": _infer_layer_id(layer_index, layer_data),
            "zPos": layer_data.get("zPos", 0),
        }

        for body_type, path_val in layer_data.items():
            if body_type == "zPos" or not isinstance(path_val, str):
                continue
            layer_obj[body_type] = make_path_relative(path_val, json_dir, characters_root)

        layers.append(layer_obj)
        layer_index += 1

    return layers


def resolve_source_definition(
    json_path: Path,
    repo_root: Path,
    source_definition_index: dict[str, dict],
) -> dict:
    """Resolve the original ULPC definition for a local JSON file."""
    direct_key = json_path.stem.lower()
    if direct_key in source_definition_index:
        return source_definition_index[direct_key]

    rel_key = json_path.relative_to(repo_root / "characters").as_posix()
    alias_key = SOURCE_DEFINITION_ALIASES.get(f"characters/{rel_key}")
    if alias_key and alias_key in source_definition_index:
        return source_definition_index[alias_key]

    return {}


def _infer_layer_id(layer_index: int, layer_data: dict) -> str:
    """Infer a stable layer id from source path data."""
    for body_type, path_val in layer_data.items():
        if body_type == "zPos" or not isinstance(path_val, str):
            continue
        lowered = path_val.lower()
        if "/fg/" in lowered or lowered.endswith("fg/"):
            return "fg"
        if "/bg/" in lowered or lowered.endswith("bg/"):
            return "bg"
        if "/mg/" in lowered or lowered.endswith("mg/"):
            return "mg"

    if layer_index == 1:
        return "base"
    return f"layer_{layer_index}"


def infer_prerequisites(json_path: Path, data: dict, characters_root: Path) -> dict | None:
    """Infer structured prerequisites.

    Output format:
    {
      "category": ["..."],
      "asset": ["..."]
    }
    """
    rel = json_path.as_posix().lower()
    category = data.get("category", data.get("type_name", "")).lower()
    name = data.get("name", "")
    tags = [t.lower() for t in data.get("tags", [])]

    # Hair extensions should work with any hair asset.
    if "/hair/extensions/" in rel:
        return {"category": ["hair"]}

    # Furry ear skintones should require the paired ear base asset.
    if "/head/ears/" in rel and json_path.stem.lower().endswith("_skin"):
        base_stem = json_path.stem[:-5]
        return {"asset": [base_stem]}

    # Torso sleeve overlays should point to the direct sleeve base asset id.
    if "/torso/clothes/shortsleeve/" in rel and category == "sleeves":
        return {"asset": ["torso_clothes_shortsleeve"]}

    if "/torso/clothes/longsleeve/" in rel and category == "sleeves":
        if "/longsleeves2/" in rel:
            return {"asset": ["torso_clothes_longsleeve2"]}
        return {"asset": ["torso_clothes_longsleeve"]}

    # Kimono sleeves should require specific kimono base ids.
    if "/dress/kimono/sleeves_oversize/" in rel:
        return {"asset": ["dress_kimono_oversize"]}

    if "/dress/kimono/sleeves/" in rel:
        return {"asset": ["dress_kimono", "dress_kimono_split"]}

    # Kimono trims should point at their direct base asset id.
    if "/dress/kimono/normal/trim/" in rel:
        return {"asset": ["dress_kimono"]}

    if "/dress/kimono/split/trim/" in rel:
        return {"asset": ["dress_kimono_split"]}

    # Trim assets support very few base assets: target explicit nearby bases.
    is_trim = "trim" in category or "/trim/" in rel or " trim" in name.lower()
    if is_trim:
        parent_assets = _find_parent_asset_ids(json_path)
        if parent_assets:
            return {"asset": parent_assets}

        # Special case: holiday hat trims map to Christmas Hat.
        if "/hat/holiday/elf/" in rel or "/hat/holiday/santa/" in rel or "santa" in tags:
            return {"asset": ["hat_holiday_christmas"]}

    # General overlays/accessories: prefer explicit nearby base assets.
    if is_overlay_or_accessory(json_path, data):
        parent_assets = _find_parent_asset_ids(json_path)
        if parent_assets:
            return {"asset": parent_assets}

    return None


def make_path_relative(layer_path: str, json_dir: Path, characters_root: Path) -> str:
    """Convert absolute-style path to relative from JSON file's directory."""
    layer_abs = characters_root / layer_path
    try:
        rel = layer_abs.relative_to(json_dir)
        return rel.as_posix() + "/"
    except ValueError:
        return layer_path


def refactor_json(
    json_path: Path,
    characters_root: Path,
    repo_root: Path,
    source_type_index: dict[str, list[str]],
    source_definition_index: dict[str, dict],
    add_prerequisites: bool = True,
) -> dict:
    """Refactor a single JSON file according to the new schema."""
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    source_data = resolve_source_definition(json_path, repo_root, source_definition_index)
    if not source_data:
        source_data = data
    
    refactored = {}
    
    refactored["name"] = data.get("name", "")
    
    refactored["category"] = resolve_category(json_path, data, characters_root, source_type_index)
    
    if "tags" in data:
        refactored["tags"] = data["tags"]

    layers = _source_layers_to_refactored_layers(source_data, json_path, characters_root)
    if layers:
        refactored["layers"] = layers
    
    if add_prerequisites:
        inferred_prereq = infer_prerequisites(json_path, data, characters_root)
        if inferred_prereq:
            refactored["prerequisites"] = inferred_prereq
        elif "prerequisites" in data:
            refactored["prerequisites"] = data["prerequisites"]
    
    if "animations" in data:
        refactored["animations"] = data["animations"]
    
    # Handle recolors (move above credits, generate if missing)
    if "recolors" in data:
        refactored["recolors"] = data["recolors"]
    else:
        generated_recolors = infer_recolors(json_path, characters_root, data)
        if generated_recolors:
            refactored["recolors"] = generated_recolors
    
    if "match_body_color" in data:
        refactored["match_body_color"] = data["match_body_color"]
    
    if "credits" in data:
        new_credits = []
        for credit in data["credits"]:
            new_credit = dict(credit)
            if "file" in new_credit:
                old_file = new_credit["file"]
                rel_file = make_path_relative(old_file, json_path.parent, characters_root)
                new_credit["file"] = rel_file.rstrip("/")
            new_credits.append(new_credit)
        refactored["credits"] = new_credits
    
    if "notes" in data:
        refactored["notes"] = data["notes"]
    
    return refactored


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    characters_root = repo_root / "characters"
    
    parser = argparse.ArgumentParser(description="Refactor JSON files to new schema.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without modifying files.")
    parser.add_argument("--no-prerequisites", action="store_true", help="Skip adding prerequisites.")
    args = parser.parse_args()
    
    json_files = sorted(characters_root.rglob("*.json"))
    source_type_index = build_source_type_index(repo_root)
    source_definition_index = build_source_definition_index(repo_root)
    processed = 0
    skipped = 0
    
    for json_file in json_files:
        if json_file.name.endswith(".stub.json"):
            skipped += 1
            continue
        
        try:
            refactored = refactor_json(
                json_file,
                characters_root,
                repo_root,
                source_type_index,
                source_definition_index,
                add_prerequisites=not args.no_prerequisites,
            )
            
            if args.dry_run:
                print(f"Would refactor: {json_file.relative_to(repo_root).as_posix()}")
            else:
                with json_file.open("w", encoding="utf-8") as f:
                    json.dump(refactored, f, indent=2)
                    f.write("\n")
                processed += 1
        except Exception as exc:
            print(f"ERROR refactoring {json_file.relative_to(repo_root).as_posix()}: {exc}")
            skipped += 1
    
    if args.dry_run:
        print(f"\nDry run: would process {processed} files (skipped {skipped})")
    else:
        print(f"Refactored {processed} files (skipped {skipped})")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
