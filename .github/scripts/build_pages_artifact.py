from __future__ import annotations

import gzip
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "_site"

# GitHub Pages receives only these browser runtime files. Data builders, local
# inputs, audit files, and source workbooks stay outside the deployed artifact.
PUBLIC_FILES = (
    ".nojekyll",
    "index.html",
    "styles.css",
    "app-config.js",
    "app.js",
    "restaurant-catalog.js",
    "restaurant-catalog-cheonsang.js",
    "restaurant-catalog-gulhwa.js",
    "restaurant-catalog-mugeo.js",
    "restaurant-catalog-eonyang.js",
    "bento-restaurants.js",
    "external-details.js",
    "restaurant-ranking.js",
)

PRIVATE_SUFFIXES = {".xlsx", ".xls", ".xlsm", ".xlsb", ".ods"}
WORKBOOK_REFERENCE = re.compile(r"\.(?:xlsx|xls|xlsm|xlsb|ods)\b", re.IGNORECASE)
SENSITIVE_DATA_FIELD = re.compile(
    r'"(?:usageCount|usageAmount|usageTrend|avgAmount|mentions|hasUnistUsage|count)"\s*:'
)
PUBLIC_DATA_FILES = {
    "restaurant-catalog.js",
    "restaurant-catalog-cheonsang.js",
    "restaurant-catalog-gulhwa.js",
    "restaurant-catalog-mugeo.js",
    "restaurant-catalog-eonyang.js",
    "restaurant-ranking.js",
}
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 512 * 1024


def format_size(size: int) -> str:
    return f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.2f} MB"


def build_artifact() -> None:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir()

    missing = [name for name in PUBLIC_FILES if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit(f"Missing public runtime files: {', '.join(missing)}")

    for name in PUBLIC_FILES:
        source = ROOT / name
        if source.suffix.lower() in PRIVATE_SUFFIXES:
            raise SystemExit(f"Private workbook cannot be deployed: {name}")
        shutil.copy2(source, OUTPUT_DIR / name)

    artifact_files = list(OUTPUT_DIR.iterdir())
    for path in artifact_files:
        if path.suffix.lower() in PRIVATE_SUFFIXES:
            raise SystemExit(f"Private workbook found in artifact: {path.name}")
        if path.suffix.lower() in {".html", ".js", ".css"}:
            text = path.read_text(encoding="utf-8")
            if WORKBOOK_REFERENCE.search(text):
                raise SystemExit(f"Workbook filename reference found in artifact: {path.name}")
            if path.name in PUBLIC_DATA_FILES and SENSITIVE_DATA_FIELD.search(text):
                raise SystemExit(f"Sensitive usage field found in public artifact: {path.name}")

    oversized = [path for path in artifact_files if path.stat().st_size > MAX_SINGLE_FILE_BYTES]
    if oversized:
        details = ", ".join(f"{path.name} ({format_size(path.stat().st_size)})" for path in oversized)
        raise SystemExit(f"Public file size budget exceeded: {details}")

    raw_size = sum(path.stat().st_size for path in artifact_files)
    if raw_size > MAX_ARTIFACT_BYTES:
        raise SystemExit(
            f"Artifact size budget exceeded: {format_size(raw_size)} > {format_size(MAX_ARTIFACT_BYTES)}"
        )
    gzip_size = sum(len(gzip.compress(path.read_bytes(), compresslevel=9)) for path in artifact_files)
    print(
        f"Built {len(PUBLIC_FILES)} public files in {OUTPUT_DIR.name}/ "
        f"(raw {format_size(raw_size)}, gzip estimate {format_size(gzip_size)})"
    )


if __name__ == "__main__":
    build_artifact()
