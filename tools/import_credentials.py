#!/usr/bin/env python3
import argparse
import os
import re
import sys
from pathlib import Path


DEFAULT_XHS_OUTPUT = Path(os.environ.get("XHS_COOKIE_OUTPUT", "/volume2/docker/xhs-downloader/auto/config/xhs_cookie.txt"))
DEFAULT_X_OUTPUT = Path(os.environ.get("X_COOKIE_OUTPUT", "/volume2/docker/x-auto-download/config/x_cookies.txt"))
DEFAULT_PIXIV_OUTPUT = Path(
    os.environ.get("PIXIV_REFRESH_TOKEN_OUTPUT", "/volume2/docker/pixiv-auto-download/config/pixiv_refresh_token.txt")
)
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{30,}")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace").strip()


def extract_pixiv_token(text: str) -> str:
    matches = TOKEN_RE.findall(text.strip())
    return matches[-1] if matches else text.strip()


def looks_like_cookie_export(text: str) -> bool:
    return "# Netscape HTTP Cookie File" in text or "\t" in text or "=" in text


def detect_cookie_target(path: Path, text: str) -> str:
    name = path.name.lower()
    lowered = text.lower()
    if "xiaohongshu.com" in lowered or "xhslink.com" in lowered or "xhs" in name or "xiaohongshu" in name:
        return "xhs"
    if "twitter.com" in lowered or "x.com" in lowered or name.startswith("x_") or "twitter" in name:
        return "x"
    if "pixiv" in name and "token" in name:
        return "pixiv_token"
    return ""


def discover_bundle(bundle: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted(p for p in bundle.rglob("*") if p.is_file()):
        try:
            text = read_text(path)
        except OSError:
            continue
        target = detect_cookie_target(path, text)
        if target and target not in found:
            found[target] = path
    return found


def write_secret(target: Path, value: str, dry_run: bool) -> Path:
    if dry_run:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value.strip() + "\n", encoding="utf-8")
    return target


def import_cookie(label: str, source: Path, output: Path, dry_run: bool) -> str:
    text = read_text(source)
    if not looks_like_cookie_export(text):
        raise ValueError(f"{label} source does not look like a cookie export: {source}")
    target = write_secret(output, text, dry_run)
    return f"{label}: {source} -> {target}"


def import_pixiv_token(source: Path, output: Path, dry_run: bool) -> str:
    token = extract_pixiv_token(read_text(source))
    if not token:
        raise ValueError(f"Pixiv token source is empty: {source}")
    target = write_secret(output, token, dry_run)
    return f"pixiv-token: {source} -> {target}"


def existing_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Import NAS downloader credentials into the shared secrets folder.")
    parser.add_argument("--bundle", default="", help="Folder containing exported cookie/token files to auto-detect.")
    parser.add_argument("--xhs", default="", help="XHS Netscape cookies.txt, Cookie header, or cookie JSON file.")
    parser.add_argument("--x", default="", help="X/Twitter Netscape cookies.txt, Cookie header, or cookie JSON file.")
    parser.add_argument("--pixiv-token", default="", help="Pixiv refresh-token text file.")
    parser.add_argument("--xhs-output", default=str(DEFAULT_XHS_OUTPUT))
    parser.add_argument("--x-output", default=str(DEFAULT_X_OUTPUT))
    parser.add_argument("--pixiv-output", default=str(DEFAULT_PIXIV_OUTPUT))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    selected: dict[str, Path] = {}
    if args.bundle:
        bundle = existing_path(args.bundle)
        if bundle is None or not bundle.is_dir():
            raise NotADirectoryError(args.bundle)
        selected.update(discover_bundle(bundle))

    explicit = {
        "xhs": existing_path(args.xhs),
        "x": existing_path(args.x),
        "pixiv_token": existing_path(args.pixiv_token),
    }
    for key, path in explicit.items():
        if path is not None:
            selected[key] = path

    if not selected:
        parser.error("Provide --bundle and/or at least one of --xhs, --x, --pixiv-token.")

    results = []
    if selected.get("xhs"):
        results.append(import_cookie("xhs", selected["xhs"], Path(args.xhs_output).expanduser(), args.dry_run))
    if selected.get("x"):
        results.append(import_cookie("x", selected["x"], Path(args.x_output).expanduser(), args.dry_run))
    if selected.get("pixiv_token"):
        results.append(import_pixiv_token(selected["pixiv_token"], Path(args.pixiv_output).expanduser(), args.dry_run))

    missing = [name for name in ("xhs", "x", "pixiv_token") if name not in selected]
    for line in results:
        print(("would import " if args.dry_run else "imported ") + line)
    if missing:
        print("skipped: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
