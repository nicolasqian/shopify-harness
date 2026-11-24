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

EDITOR_NAME_TO_TYPES = {
    "pdp rich text": ["pdp-rich-text"],
    "pdp text with image": ["pdp-text-with-image", "pdp-text-with-image-2"],
    "pdp slideshow": ["pdp-slideshow", "pdp-slideshow-new", "pdp-slideshow-alter"],
}


def load_template(path: Path) -> dict:
    text = path.read_text()
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return json.loads(text)


def types_for(editor_name: str | None, section_type: str | None, source_only: bool) -> list[str]:
    if section_type:
        return [section_type]
    if not editor_name:
        raise SystemExit("Provide --editor-name or --type")
    key = editor_name.strip().lower()
    types = EDITOR_NAME_TO_TYPES.get(key)
    if not types:
        raise SystemExit(f"Unknown editor name: {editor_name!r}. Known: {list(EDITOR_NAME_TO_TYPES)}")
    # Source templates usually use the canonical type without -2.
    if source_only:
        return [types[0]]
    return types


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
        help="Also match type variants (-2, -new, -alter). Default: canonical source type only.",
    )
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--nth", type=int, help="1-based index including disabled")
    parser.add_argument("--dump", action="store_true", help="Print the nth section JSON")
    args = parser.parse_args()

    types = types_for(args.editor_name, args.type, source_only=not args.include_variants)
    data = load_template(args.template)
    ids = matched_ids(data, types)

    if args.list or args.nth is None:
        print(f"type={types} count={len(ids)}")
        for i, sid in enumerate(ids, 1):
            sec = data["sections"][sid]
            flag = " disabled" if sec.get("disabled") else ""
            print(f"{i}. {sid} ({sec.get('type')}){flag} | {clue(sec)}")
        if args.nth is None and not args.dump:
            return 0

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
    raise SystemExit(main())
