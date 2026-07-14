from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

from region_config import get_region


DATA_DIR = Path("data")
OUT_DIR = DATA_DIR / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

REGION_ID, REGION = get_region(sys.argv[1] if len(sys.argv) > 1 else None)
SOURCE_FILES = [(label, Path(path)) for label, path in REGION["localdata_files"]]
REGION_TOKENS = REGION.get("scope_tokens", REGION["search_tokens"])


def clean(value: str | None) -> str:
    return str(value or "").strip()


def normalize_name(value: str | None) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", clean(value).lower())


def row_address(row: dict[str, str]) -> str:
    return clean(row.get("도로명주소")) or clean(row.get("지번주소"))


def is_target_region(row: dict[str, str]) -> bool:
    text = " ".join([clean(row.get("도로명주소")), clean(row.get("지번주소"))])
    return any(token in text for token in REGION_TOKENS)


def classify_category(row: dict[str, str], license_type: str) -> str:
    raw = clean(row.get("위생업태명")) or clean(row.get("업태구분명")) or license_type
    name = clean(row.get("사업장명"))
    text = f"{raw} {name}"
    if any(word in text for word in ["커피", "카페", "다방", "디저트", "아이스크림", "빙수"]):
        return "카페/디저트"
    if any(word in text for word in ["제과", "베이커리", "빵"]):
        return "베이커리"
    if any(word in text for word in ["중국", "중식", "짬뽕", "짜장", "양꼬치"]):
        return "중식"
    if any(word in text for word in ["일식", "스시", "초밥", "참치", "돈까스", "돈카츠"]):
        return "일식"
    if any(word in text for word in ["횟집", "회", "해물", "아구", "장어", "어탕"]):
        return "해산물/횟집"
    if any(word in text for word in ["고기", "갈비", "삼겹", "한우", "족발", "보쌈", "닭", "치킨"]):
        return "고기/치킨"
    if any(word in text for word in ["국밥", "탕", "찌개", "칼국수", "국수", "냉면", "면"]):
        return "국밥/면"
    if any(word in text for word in ["분식", "김밥", "떡볶이", "패스트푸드", "편의점"]):
        return "간편식"
    return raw or license_type


def classify_status(row: dict[str, str]) -> str:
    status = clean(row.get("영업상태명"))
    detail = clean(row.get("상세영업상태명"))
    closed = clean(row.get("폐업일자"))
    text = f"{status} {detail}"
    if "폐업" in text:
        return f"폐업({closed})" if closed else "폐업"
    if "중지" in text or "정지" in text:
        return text.strip()
    if "취소" in text or "말소" in text:
        return text.strip()
    if status == "영업/정상" and detail in ("영업", "정상", ""):
        return "영업중"
    return detail or status or "확인 필요"


def read_public_restaurants() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for license_type, path in SOURCE_FILES:
        with path.open("r", encoding="cp949", errors="replace", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                if not is_target_region(row):
                    continue
                rows.append(
                    {
                        "업소명": clean(row.get("사업장명")),
                        "대분류": classify_category(row, license_type),
                        "인허가구분": license_type,
                        "영업상태": clean(row.get("영업상태명")),
                        "상세상태": clean(row.get("상세영업상태명")),
                        "특이사항": classify_status(row),
                        "폐업일자": clean(row.get("폐업일자")),
                        "인허가일자": clean(row.get("인허가일자")),
                        "주소": row_address(row),
                        "도로명주소": clean(row.get("도로명주소")),
                        "지번주소": clean(row.get("지번주소")),
                        "전화번호": clean(row.get("전화번호")),
                        "관리번호": clean(row.get("관리번호")),
                        "좌표X": clean(row.get("좌표정보(X)")),
                        "좌표Y": clean(row.get("좌표정보(Y)")),
                        "최종수정시점": clean(row.get("최종수정시점")),
                        "name_key": normalize_name(row.get("사업장명")),
                    }
                )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "업소명",
        "대분류",
        "인허가구분",
        "영업상태",
        "상세상태",
        "특이사항",
        "폐업일자",
        "인허가일자",
        "주소",
        "도로명주소",
        "지번주소",
        "전화번호",
        "관리번호",
        "좌표X",
        "좌표Y",
        "최종수정시점",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows = read_public_restaurants()
    rows.sort(key=lambda row: (row["특이사항"] != "영업중", row["업소명"], row["주소"]))
    active = [row for row in rows if row["특이사항"] == "영업중"]
    special = [row for row in rows if row["특이사항"] != "영업중"]

    write_csv(OUT_DIR / f"{REGION_ID}_public_restaurants_all.csv", rows)
    write_csv(OUT_DIR / f"{REGION_ID}_public_restaurants_active.csv", active)
    write_csv(OUT_DIR / f"{REGION_ID}_public_restaurants_special.csv", special)

    summary = {
        "region_id": REGION_ID,
        "region_name": REGION["name"],
        "source_files": [str(path) for _, path in SOURCE_FILES],
        "mfds_status": "식약처 I2861 변경정보는 인증키(FOODSAFETY_API_KEY) 입력 후 build_license_status.py로 병합 가능",
        "region_tokens": REGION_TOKENS,
        "total": len(rows),
        "active": len(active),
        "special": len(special),
        "by_license_type": dict(Counter(row["인허가구분"] for row in rows)),
        "active_by_category": dict(Counter(row["대분류"] for row in active).most_common()),
        "outputs": [
            f"data/processed/{REGION_ID}_public_restaurants_all.csv",
            f"data/processed/{REGION_ID}_public_restaurants_active.csv",
            f"data/processed/{REGION_ID}_public_restaurants_special.csv",
        ],
    }
    (OUT_DIR / f"{REGION_ID}_public_restaurants_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n영업중 상위 30건")
    for row in active[:30]:
        print(f"{row['업소명']}\t{row['대분류']}\t{row['인허가구분']}\t{row['주소']}")


if __name__ == "__main__":
    main()
