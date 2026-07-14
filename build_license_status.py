from __future__ import annotations

import csv
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

from region_config import get_region


ROOT = Path.cwd()
DATA_DIR = ROOT / "data"
MFDS_DIR = DATA_DIR / "mfds"
OUTPUT_DIR = DATA_DIR / "processed"

REGION_ID, REGION = get_region(sys.argv[1] if len(sys.argv) > 1 else None)
REGION_TOKENS = REGION.get("scope_tokens", REGION["search_tokens"])
LOCALDATA_FILES = [(label, ROOT / path) for label, path in REGION["localdata_files"]]

MFDS_SERVICE_ID = "I2861"
MFDS_KEY_ENV = "FOODSAFETY_API_KEY"


def normalize(value: str | None) -> str:
    return (
        str(value or "")
        .lower()
        .replace("(주)", "")
        .replace("㈜", "")
        .replace("주식회사", "")
        .replace(" ", "")
        .strip()
    )


def compact_name(value: str | None) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", normalize(value))


def in_target_region(row: dict[str, str]) -> bool:
    address = " ".join([row.get("도로명주소", ""), row.get("지번주소", ""), row.get("소재지주소", "")])
    return any(token in address for token in REGION_TOKENS)


def read_localdata() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for source_type, path in LOCALDATA_FILES:
        if not path.exists():
            continue
        with path.open("r", encoding="cp949", errors="replace", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                if not in_target_region(row):
                    continue
                status = row.get("영업상태명", "")
                detail_status = row.get("상세영업상태명", "")
                rows.append(
                    {
                        "source": "localdata",
                        "license_type": source_type,
                        "license_no": row.get("관리번호", ""),
                        "name": row.get("사업장명", ""),
                        "name_key": compact_name(row.get("사업장명", "")),
                        "business_type": row.get("위생업태명") or row.get("업태구분명", ""),
                        "status": status,
                        "detail_status": detail_status,
                        "closed_date": row.get("폐업일자", ""),
                        "permit_date": row.get("인허가일자", ""),
                        "road_address": row.get("도로명주소", ""),
                        "lot_address": row.get("지번주소", ""),
                        "phone": row.get("전화번호", ""),
                        "last_modified": row.get("최종수정시점", ""),
                        "special_note": classify_local_status(status, detail_status, row.get("폐업일자", "")),
                    }
                )
    return rows


def classify_local_status(status: str, detail_status: str, closed_date: str) -> str:
    text = f"{status} {detail_status}".strip()
    if "폐업" in text:
        return f"폐업{f'({closed_date})' if closed_date else ''}"
    if "중지" in text or "정지" in text:
        return text
    if "취소" in text or "말소" in text:
        return text
    if status == "영업/정상" and (detail_status in ("영업", "정상", "")):
        return "영업중"
    return text or "확인 필요"


def fetch_mfds_sample() -> None:
    MFDS_DIR.mkdir(parents=True, exist_ok=True)
    path = MFDS_DIR / "I2861_sample.json"
    if path.exists():
        return
    url = "https://openapi.foodsafetykorea.go.kr/api/sample/I2861/json/1/100"
    urllib.request.urlretrieve(url, path)


def fetch_mfds_with_key(page_size: int = 1000, max_pages: int = 5) -> Path | None:
    api_key = os.environ.get(MFDS_KEY_ENV)
    if not api_key:
        return None

    MFDS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MFDS_DIR / "I2861_fetched.jsonl"
    if output_path.exists():
        modified_date = datetime.fromtimestamp(output_path.stat().st_mtime).date()
        if modified_date == date.today():
            return output_path

    with output_path.open("w", encoding="utf-8") as out:
        for page in range(max_pages):
            start = page * page_size + 1
            end = (page + 1) * page_size
            url = f"https://openapi.foodsafetykorea.go.kr/api/{api_key}/{MFDS_SERVICE_ID}/json/{start}/{end}"
            with urllib.request.urlopen(url, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
            rows = payload.get(MFDS_SERVICE_ID, {}).get("row", [])
            if not rows:
                break
            for row in rows:
                if "울산" in row.get("SITE_ADDR", ""):
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
            total = int(payload.get(MFDS_SERVICE_ID, {}).get("total_count", 0) or 0)
            if end >= total:
                break
    return output_path


def read_mfds_changes() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    candidates = [
        MFDS_DIR / "I2861_fetched.jsonl",
        MFDS_DIR / "I2861_ulju.jsonl",
    ]
    for path in candidates:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                row = json.loads(line)
                address = row.get("SITE_ADDR", "")
                if not any(token in address for token in REGION_TOKENS):
                    continue
                rows.append(
                    {
                        "source": "mfds",
                        "license_type": row.get("INDUTY_CD_NM", ""),
                        "license_no": row.get("LCNS_NO", ""),
                        "name": row.get("BSSH_NM", ""),
                        "name_key": compact_name(row.get("BSSH_NM", "")),
                        "business_type": row.get("INDUTY_CD_NM", ""),
                        "change_date": row.get("CHNG_DT", ""),
                        "before": row.get("CHNG_BF_CN", ""),
                        "after": row.get("CHNG_AF_CN", ""),
                        "reason": row.get("CHNG_PRVNS", ""),
                        "address": address,
                        "special_note": classify_mfds_change(row),
                    }
                )
    return rows


def classify_mfds_change(row: dict[str, str]) -> str:
    text = " ".join([row.get("CHNG_BF_CN", ""), row.get("CHNG_AF_CN", ""), row.get("CHNG_PRVNS", "")])
    if any(word in text for word in ["영업정지", "영업 중지", "정지", "취소", "폐업", "말소"]):
        return text
    return row.get("CHNG_PRVNS", "") or "변경이력"


def write_outputs(local_rows: list[dict[str, str]], mfds_rows: list[dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    active_rows = [row for row in local_rows if row["special_note"] == "영업중"]
    issue_rows = [row for row in local_rows if row["special_note"] != "영업중"]
    mfds_issue_rows = [row for row in mfds_rows if row["special_note"] != "변경민원"]

    local_fields = [
        "source",
        "license_type",
        "license_no",
        "name",
        "business_type",
        "status",
        "detail_status",
        "closed_date",
        "permit_date",
        "road_address",
        "lot_address",
        "phone",
        "last_modified",
        "special_note",
    ]
    mfds_fields = [
        "source",
        "license_type",
        "license_no",
        "name",
        "business_type",
        "change_date",
        "before",
        "after",
        "reason",
        "address",
        "special_note",
    ]

    write_csv(OUTPUT_DIR / f"{REGION_ID}_license_status.csv", local_rows, local_fields)
    write_csv(OUTPUT_DIR / f"{REGION_ID}_license_special_notes.csv", issue_rows, local_fields)
    write_csv(OUTPUT_DIR / f"{REGION_ID}_mfds_changes.csv", mfds_rows, mfds_fields)
    write_csv(OUTPUT_DIR / f"{REGION_ID}_mfds_special_notes.csv", mfds_issue_rows, mfds_fields)

    summary = {
        "region_id": REGION_ID,
        "region_name": REGION["name"],
        "region_tokens": REGION_TOKENS,
        "localdata_total": len(local_rows),
        "localdata_active": len(active_rows),
        "localdata_special_notes": len(issue_rows),
        "mfds_changes": len(mfds_rows),
        "mfds_special_notes": len(mfds_issue_rows),
        "mfds_key_env": MFDS_KEY_ENV,
        "outputs": [
            f"data/processed/{REGION_ID}_license_status.csv",
            f"data/processed/{REGION_ID}_license_special_notes.csv",
            f"data/processed/{REGION_ID}_mfds_changes.csv",
            f"data/processed/{REGION_ID}_mfds_special_notes.csv",
        ],
    }
    (OUTPUT_DIR / f"{REGION_ID}_license_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    fetch_mfds_sample()
    fetch_mfds_with_key()
    local_rows = read_localdata()
    mfds_rows = read_mfds_changes()
    write_outputs(local_rows, mfds_rows)
    summary = json.loads((OUTPUT_DIR / f"{REGION_ID}_license_summary.json").read_text(encoding="utf-8"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
