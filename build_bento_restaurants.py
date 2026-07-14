from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

from build_public_restaurants_js import distance_km, geocode, load_cache, save_cache
from runtime_payload import compact_bento_restaurant, write_window_values


ROOT = Path.cwd()
OUT_PATH = ROOT / "bento-restaurants.js"
SOURCE_FILES = [
    ("일반음식점", ROOT / "data" / "general_restaurants_national.csv"),
    ("휴게음식점", ROOT / "data" / "rest_cafes_national.csv"),
]
SOURCE_URLS = {
    "일반음식점": "https://www.data.go.kr/data/15045016/fileData.do",
    "휴게음식점": "https://www.data.go.kr/data/15006730/fileData.do",
}
EXCLUDED_DISTRICTS = ("북구", "동구")
MAX_DISTANCE_KM = 15.0
BENTO_KEYWORDS = (
    "도시락",
    "케이터링",
    "케터링",
    "캐터링",
    "출장조리",
    "출장요리",
    "출장뷔페",
    "배달전문",
)


def clean(value: str | None) -> str:
    return str(value or "").strip()


def normalize(value: str | None) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", clean(value).lower())


def row_address(row: dict[str, str]) -> str:
    return clean(row.get("도로명주소")) or clean(row.get("지번주소"))


def full_address(row: dict[str, str]) -> str:
    return " ".join([clean(row.get("도로명주소")), clean(row.get("지번주소"))])


def is_active(row: dict[str, str]) -> bool:
    return clean(row.get("영업상태명")) == "영업/정상" and clean(row.get("상세영업상태명")) in {
        "",
        "영업",
        "정상",
    }


def is_bento_business(row: dict[str, str]) -> bool:
    text = " ".join(
        [
            clean(row.get("사업장명")),
            clean(row.get("업태구분명")),
            clean(row.get("위생업태명")),
        ]
    ).lower()
    return any(keyword in text for keyword in BENTO_KEYWORDS)


def is_kimbap_shop(row: dict[str, str]) -> bool:
    name = clean(row.get("사업장명"))
    return "김밥" in name and "도시락" not in name


def district_from_address(address: str) -> str:
    for district in ("울주군", "남구", "중구", "북구", "동구"):
        if district in address:
            return district
    return "확인 필요"


def service_menu(row: dict[str, str]) -> str:
    text = " ".join(
        [
            clean(row.get("사업장명")),
            clean(row.get("업태구분명")),
            clean(row.get("위생업태명")),
        ]
    )
    if any(keyword in text for keyword in ("케이터링", "케터링", "캐터링", "출장조리", "출장요리", "출장뷔페")):
        return "케이터링, 출장조리"
    if "배달전문" in text:
        return "배달전문"
    return "도시락, 포장"


def stable_id(public_id: str, name: str, address: str) -> str:
    base = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", name).strip("-").lower() or "bento"
    digest = hashlib.md5(f"{public_id}|{name}|{address}".encode("utf-8")).hexdigest()[:8]
    return f"bento-{base[:24]}-{digest}"


def read_candidates() -> tuple[list[dict[str, str]], Counter]:
    candidates: dict[str, dict[str, str]] = {}
    counts = Counter()

    for license_type, path in SOURCE_FILES:
        with path.open("r", encoding="cp949", errors="replace", newline="") as file:
            for row in csv.DictReader(file):
                address_text = full_address(row)
                if "울산광역시" not in address_text or not is_active(row) or not is_bento_business(row):
                    continue

                counts["ulsan_active_bento"] += 1
                if is_kimbap_shop(row):
                    counts["excluded_kimbap_shop"] += 1
                    continue

                district = district_from_address(address_text)
                counts[f"district_{district}"] += 1
                if district in EXCLUDED_DISTRICTS:
                    counts["excluded_district"] += 1
                    continue

                name = clean(row.get("사업장명"))
                address = row_address(row)
                dedupe_key = f"{normalize(name)}|{normalize(address.split(',', 1)[0])}"
                candidates.setdefault(
                    dedupe_key,
                    {
                        "public_id": clean(row.get("관리번호")),
                        "name": name,
                        "address": address,
                        "district": district,
                        "license_type": license_type,
                        "permit_date": clean(row.get("인허가일자")),
                        "phone": clean(row.get("전화번호")),
                        "menu": service_menu(row),
                    },
                )

    counts["after_district_filter"] = len(candidates)
    return list(candidates.values()), counts


def main() -> None:
    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    if not rest_key:
        raise SystemExit("KAKAO_REST_API_KEY 환경변수가 필요합니다.")

    candidates, counts = read_candidates()
    cache = load_cache()
    restaurants = []

    for row in candidates:
        geo = geocode(row["address"], rest_key, cache)
        if not geo.get("ok"):
            counts["excluded_geocode_failure"] += 1
            continue

        lat = round(float(geo["lat"]), 7)
        lng = round(float(geo["lng"]), 7)
        school_distance = distance_km(lat, lng)
        if school_distance >= MAX_DISTANCE_KM:
            counts["excluded_distance"] += 1
            continue

        license_type = row["license_type"]
        restaurants.append(
            {
                "id": stable_id(row["public_id"], row["name"], row["address"]),
                "publicId": row["public_id"],
                "name": row["name"],
                "canonicalName": row["name"],
                "category": "도시락",
                "address": row["address"],
                "district": row["district"],
                "lat": lat,
                "lng": lng,
                "schoolDistanceKm": round(school_distance, 2),
                "menu": row["menu"],
                "price": 60,
                "score": 50,
                "mentions": 0,
                "mood": "공공데이터 영업중 업소",
                "hours": "영업시간 확인 필요",
                "phone": row["phone"],
                "source": f"행안부 {license_type}",
                "sourceUrl": SOURCE_URLS[license_type],
                "usageCount": 0,
                "usageAmount": 0,
                "avgAmount": 0,
                "usageTrend": [],
                "recentDate": "",
                "memoSample": "",
                "matchBasis": "울산 영업중 도시락·배달·케이터링 업태",
                "publicStatus": "영업중",
                "licenseType": license_type,
                "permitDate": row["permit_date"],
                "hasUnistUsage": False,
                "geocodeSource": geo.get("source", "kakao_address"),
                "combinedScore": None,
            }
        )

    restaurants.sort(key=lambda item: (item["schoolDistanceKm"], item["district"], item["name"]))
    counts["included"] = len(restaurants)
    summary = {
        "scope": "울산광역시 영업중 도시락·배달·케이터링 업체(김밥 전문점 제외)",
        "excludedBusinessTypes": ["김밥 전문점"],
        "excludedDistricts": list(EXCLUDED_DISTRICTS),
        "maxSchoolDistanceKmExclusive": MAX_DISTANCE_KM,
        "distanceBasis": "UNIST 기준 직선거리",
        "restaurantCount": len(restaurants),
        "counts": dict(counts),
        "sourceFiles": [str(path.relative_to(ROOT)).replace("\\", "/") for _, path in SOURCE_FILES],
        "geocodeSource": "카카오 Local 주소 검색 API",
    }

    save_cache(cache)
    write_window_values(
        OUT_PATH,
        {"bentoRestaurants": [compact_bento_restaurant(item) for item in restaurants]},
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for item in restaurants:
        print(f"{item['schoolDistanceKm']:>5.1f}km\t{item['district']}\t{item['name']}\t{item['address']}")


if __name__ == "__main__":
    main()
