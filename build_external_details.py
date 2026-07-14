from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from urllib.parse import quote

from region_config import get_region
from runtime_payload import write_window_values


DATA_DIR = Path("data")
OUT_DIR = DATA_DIR / "processed"


DETAIL_SEEDS = {
    "guyeong": {
        "댓잎장어": {
            "external_hours": "화-토 11:00-21:00, 일 11:00-15:00, 월 휴무, 브레이크타임 14:00-17:00",
            "external_phone": "052-243-3334",
            "external_menu": "히츠마부시, 장어구이정식, 민물장어튀김정식, 민물장어더덕고추장불고기",
            "external_tags": "장어구이, 민물장어, 히츠마부시, 주차가능, 예약가능, 포장",
            "reservation_hint": "테이블링 예약/상세정보 확인 가능",
            "parking_hint": "주차 이용 가능",
            "detail_source": "테이블링",
            "detail_url": "https://www.tabling.co.kr/place/677cd15e66de5f069887c7c4",
            "verification_status": "verified_external_seed",
        },
        "스시미즈기와 울산구영리점": {
            "external_hours": "11:00-21:00, 브레이크타임 15:00-16:30, 점심 라스트오더 14:30, 저녁 라스트오더 20:30",
            "external_phone": "0507-1340-0942",
            "external_menu": "한판 스시, 미나리 백 나가사끼짬뽕, 초밥, 돈까스, 튀김, 면요리",
            "external_tags": "초밥, 일식, 주차가능, 테이블링 상세정보",
            "reservation_hint": "테이블링 입점 요청 상태로 표시됨",
            "parking_hint": "가게 뒤편 주차 가능, 근처 공영주차장 이용 안내",
            "detail_source": "테이블링",
            "detail_url": "https://www.tabling.co.kr/place/68103bb160fa39d16f0c76b8",
            "verification_status": "verified_external_seed",
        },
        "갓포 HERO": {
            "external_hours": "",
            "external_phone": "",
            "external_menu": "숙성회, 초밥, 철판요리, 이자카야 메뉴",
            "external_tags": "숙성회, 초밥, 철판요리, 이자카야, 예약문의",
            "reservation_hint": "공식 인스타그램에서 DM 또는 전화 예약 문의 안내",
            "parking_hint": "",
            "detail_source": "Instagram",
            "detail_url": "https://www.instagram.com/kappo.hero/",
            "verification_status": "verified_external_seed",
        },
    }
}


def clean(value: str | None) -> str:
    return str(value or "").strip()


def platform_query(row: dict[str, str], region_name: str) -> str:
    name = clean(row.get("name")) or clean(row.get("업소명")) or clean(row.get("excel_name"))
    address = clean(row.get("address")) or clean(row.get("주소"))
    return f"{region_name} {name} {address}".strip()


def search_urls(query: str, tabling_query: str) -> dict[str, str]:
    encoded = quote(query)
    tabling_encoded = quote(tabling_query)
    return {
        "diningcode_search_url": f"https://www.diningcode.com/list.dc?query={encoded}",
        "tabling_search_url": f"https://www.tabling.co.kr/search?keyword={tabling_encoded}",
        "kakao_search_url": f"https://map.kakao.com/?q={encoded}",
        "naver_search_url": f"https://map.naver.com/p/search/{encoded}",
    }


def seed_for(region_id: str, name: str) -> dict[str, str]:
    seeds = DETAIL_SEEDS.get(region_id, {})
    if name in seeds:
        return seeds[name]
    for seed_name, seed in seeds.items():
        if seed_name.replace(" ", "") in name.replace(" ", "") or name.replace(" ", "") in seed_name.replace(" ", ""):
            return seed
    return {
        "external_hours": "",
        "external_phone": "",
        "external_menu": "",
        "external_tags": "",
        "reservation_hint": "",
        "parking_hint": "",
        "detail_source": "",
        "detail_url": "",
        "verification_status": "needs_external_review",
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    preferred = [
        "name",
        "category",
        "address",
        "phone",
        "external_phone",
        "external_hours",
        "external_menu",
        "external_tags",
        "reservation_hint",
        "parking_hint",
        "verification_status",
        "detail_source",
        "detail_url",
        "diningcode_search_url",
        "tabling_search_url",
        "kakao_search_url",
        "naver_search_url",
    ]
    fields = preferred + sorted({key for row in rows for key in row.keys()} - set(preferred))
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_js(path: Path, rows: list[dict[str, str]]) -> None:
    details = []
    for row in rows:
        if row.get("verification_status") != "verified_external_seed":
            continue
        details.append(
            {
                "name": row.get("name", ""),
                "aliases": sorted(
                    {
                        clean(row.get("name")),
                        clean(row.get("excel_name")),
                        clean(row.get("canonical_name")),
                    }
                    - {""}
                ),
                "externalPhone": row.get("external_phone", ""),
                "externalHours": row.get("external_hours", ""),
                "externalMenu": row.get("external_menu", ""),
                "externalTags": row.get("external_tags", ""),
                "reservationHint": row.get("reservation_hint", ""),
                "parkingHint": row.get("parking_hint", ""),
                "detailSource": row.get("detail_source", ""),
                "detailUrl": row.get("detail_url", ""),
                "verificationStatus": row.get("verification_status", ""),
            }
        )
    write_window_values(path, {"restaurantExternalDetails": details})


def main() -> None:
    region_id, region = get_region(sys.argv[1] if len(sys.argv) > 1 else None)
    master_path = OUT_DIR / f"{region_id}_restaurant_master.csv"
    if not master_path.exists():
        raise SystemExit(f"Missing master file: {master_path}. Run build_restaurant_master.py {region_id} first.")

    rows = read_csv(master_path)
    enriched = []
    for row in rows:
        name = clean(row.get("name"))
        query = platform_query(row, region["name"])
        detail = seed_for(region_id, name)
        urls = search_urls(query, name)
        merged = {**row, **urls, **detail}
        if not merged.get("external_phone"):
            merged["external_phone"] = clean(row.get("phone"))
        enriched.append(merged)

    detail_rows = [
        {
            key: row.get(key, "")
            for key in [
                "name",
                "category",
                "address",
                "external_phone",
                "external_hours",
                "external_menu",
                "external_tags",
                "reservation_hint",
                "parking_hint",
                "verification_status",
                "detail_source",
                "detail_url",
                "diningcode_search_url",
                "tabling_search_url",
                "kakao_search_url",
                "naver_search_url",
            ]
        }
        for row in enriched
    ]

    write_csv(OUT_DIR / f"{region_id}_restaurant_external_details.csv", detail_rows)
    write_csv(OUT_DIR / f"{region_id}_restaurant_enriched_master.csv", enriched)
    write_js(Path("external-details.js"), enriched)

    summary = {
        "region_id": region_id,
        "region_name": region["name"],
        "master_rows": len(rows),
        "verified_external_seed": sum(1 for row in enriched if row["verification_status"] == "verified_external_seed"),
        "needs_external_review": sum(1 for row in enriched if row["verification_status"] == "needs_external_review"),
        "note": "DiningCode/Tableling 공식 공개 API는 확인되지 않아 검색 URL과 공개 상세 seed를 분리 저장합니다.",
        "outputs": [
            f"data/processed/{region_id}_restaurant_external_details.csv",
            f"data/processed/{region_id}_restaurant_enriched_master.csv",
            "external-details.js",
        ],
    }
    (OUT_DIR / f"{region_id}_restaurant_external_details_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nVERIFIED_SAMPLE")
    for row in enriched:
        if row["verification_status"] == "verified_external_seed":
            print(row["name"], row["external_menu"], row["detail_source"], row["detail_url"])


if __name__ == "__main__":
    main()
