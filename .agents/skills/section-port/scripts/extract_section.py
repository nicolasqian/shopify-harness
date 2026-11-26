#!/usr/bin/env python3
"""List or dump the Nth Shopify template section by editor name or type.

Nth is 1-based and includes disabled sections, matching template `order`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# This helper and the verifier ship with the same Shopify JSON reader.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import theme_json

SCHEMA_RE = re.compile(r"\{%-?\s*schema\s*-?%\}(.*?)\{%-?\s*endschema\s*-?%\}", re.S)


def read_object(path: Path) -> dict:
    try:
        value = theme_json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected a JSON object")
        return value
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def find_theme_root(template_path: Path) -> Path | None:
    for parent in template_path.resolve().parents:
        if (parent / "sections").is_dir():
            return parent
    return None


def load_schema_locales(theme_root: Path) -> dict:
    locales_dir = theme_root / "locales"
    for pattern in ("*.default.schema.json", "*.default.json"):
        for path in sorted(locales_dir.glob(pattern)):
            return read_object(path)
    return {}


def resolve_translation(value: str, locales: dict) -> str:
    if not value.startswith("t:") or not locales:
        return value
    cur = locales
    for part in value[2:].split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return value
    return cur if isinstance(cur, str) else value


def profile_types(label, include_variants):
    aliases_path = Path(__file__).resolve().parents[1] / "section-aliases.json"
    aliases = read_object(aliases_path).get(label.strip().casefold(), []) if aliases_path.is_file() else []
    if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
        raise ValueError(f"{aliases_path}: expected a list of types for {label!r}")
    return aliases if include_variants else aliases[:1]


def matched_by_label(data, root, label):
    key = label.strip().casefold()
    sections = data.get("sections", {})
    locales = load_schema_locales(root) if root else {}
    matching_types = set()
    ids = []
    checked = set()
    for sid in data.get("order", []):
        section = sections[sid]
        kind = section["type"]
        if root and kind not in checked and Path(kind).name == kind:
            checked.add(kind)
            path = root / "sections" / (kind + ".liquid")
            if path.is_file():
                match = SCHEMA_RE.search(path.read_text(encoding="utf-8"))
                if match:
                    try:
                        schema = theme_json.loads(match.group(1))
                        name = schema["name"]
                        if key in (name.strip().casefold(), resolve_translation(name, locales).strip().casefold()):
                            matching_types.add(kind)
                    except (KeyError, AttributeError, TypeError, ValueError) as exc:
                        print(f"[WARN] {path}: {exc}", file=sys.stderr)
        if kind in matching_types or str(section.get("name", "")).strip().casefold() == key:
            ids.append(sid)
    return ids


def clue(section: dict) -> str:
    settings = section.get("settings") or {}
    for key in ("title", "subheading", "section_id"):
        val = settings.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:80]
    blocks = section.get("blocks") or {}
    for bid in section.get("block_order") or blocks.keys():
        bset = (blocks.get(bid) or {}).get("settings") or {}
        for key in ("tab_title", "title"):
            val = bset.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:80]
    return ""


def collect_images(obj, acc: set[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            collect_images(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            collect_images(v, acc)
    elif isinstance(obj, str) and obj.startswith("shopify://shop_images/"):
        acc.add(obj.rsplit("/", 1)[-1])


def matched_ids(data: dict, types: list[str]) -> list[str]:
    type_set = set(types)
    return [
        sid
        for sid in data.get("order") or []
        if (data.get("sections") or {}).get(sid, {}).get("type") in type_set
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", type=Path)
    parser.add_argument("--editor-name", help='Theme editor label, e.g. "PDP Slideshow"')
    parser.add_argument("--type", help="Exact section type, e.g. pdp-slideshow")
    parser.add_argument(
        "--include-variants",
        action="store_true",
        help="Include additional type aliases supplied by the installed theme profile.",
    )
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--nth", type=int, help="1-based index including disabled")
    parser.add_argument("--dump", action="store_true", help="Print the nth section JSON")
    args = parser.parse_args()

    if not (args.editor_name or args.type):
        parser.error("provide --editor-name or --type")
    data = read_object(args.template)
    types = [args.type] if args.type else profile_types(args.editor_name, args.include_variants)
    if types:
        ids = matched_ids(data, types)
    else:
        ids = matched_by_label(data, find_theme_root(args.template), args.editor_name)
        types = list(dict.fromkeys(data["sections"][sid]["type"] for sid in ids))

    if args.list or args.nth is None:
        print(f"type={types} count={len(ids)}")
        for i, sid in enumerate(ids, 1):
            sec = data["sections"][sid]
            flag = " disabled" if sec.get("disabled") else ""
            print(f"{i}. {sid} ({sec.get('type')}){flag} | {clue(sec)}")

    if args.nth is None:
        return 0
    if args.nth < 1 or args.nth > len(ids):
        print(f"nth={args.nth} out of range 1..{len(ids)}", file=sys.stderr)
        return 1

    sid = ids[args.nth - 1]
    sec = data["sections"][sid]
    images: set[str] = set()
    collect_images(sec, images)
    print(f"id={sid}")
    print(f"type={sec.get('type')}")
    print(f"disabled={bool(sec.get('disabled'))}")
    print(f"clue={clue(sec)}")
    print("images=" + ",".join(sorted(images)))
    if args.dump:
        json.dump({sid: sec}, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        sys.exit(str(error))
