from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from address_keys import address_key as precise_address_key
from build_public_restaurants_js import clean, dining_category, int_number, is_non_restaurant_business, json_array
from region_config import get_region
from runtime_payload import (
    compact_restaurants,
    private_catalog_path,
    read_window_value,
    write_private_catalog,
    write_window_values,
)


ROOT = Path.cwd()
CACHE_PATH = ROOT / "data" / "processed" / "kakao_catalog_cache.json"
REGION_ID, ACTIVE_REGION = get_region(None)
PUBLIC_PATH = ROOT / "data" / "processed" / "public-restaurants-guyeong.js"
MASTER_PATH = ROOT / "data" / "processed" / "guyeong_restaurant_master.csv"
UNMATCHED_PATH = ROOT / "data" / "processed" / "guyeong_restaurant_excel_unmatched.csv"
REPORT_PATH = ROOT / "data" / "processed" / "restaurant_catalog_report.json"
OUT_PATH = ROOT / "restaurant-catalog.js"
PRIVATE_CATALOG_PATH = private_catalog_path(ROOT, REGION_ID)
REGION_RECT = tuple(ACTIVE_REGION["bounds"])
KAKAO_CATEGORY_CODES = ("FD6", "CE7")
ROAD_PATTERN = re.compile(ACTIVE_REGION["address_key_pattern"])
FOOD_CATEGORY_WORDS = (
    "음식점",
    "카페",
    "커피",
    "제과",
    "베이커리",
    "떡",
    "디저트",
    "아이스크림",
)
PLACE_NAME_HINTS = {
    "주식회사 리프": "그리즐리 버거",
    "모조리(빈틈없이 여무지게)": "모조리 구영리2호점",
    "클러프x콜프(cluff x colf)": "콜프로스터스X클러프",
    "트로이커피/주식회사 트로이": "트로이커피 범서중앙점",
    "뚜구리1호점": "뚜구리 본점",
    "비비큐치킨": "BBQ 울산천상점",
    "비에이치씨천상점": "BHC치킨 울산천상점",
    "감포생아구회도매센타": "감포생아구찜 천상점",
    "황금정 함흥냉면": "황금정 굴화점",
    "던킨도너츠": "던킨 울산원예농협하나로점",
    "엘엘엘 베이커리 카페/주식회": "LLL베이커리카페",
    "주식회사 더만족": "더만족 울산대점",
    "유앤아이커피": "U&I커피",
    "대칸양갈비": "대칸양고기",
    "갯마을횟집": "갯마을수산",
    "두리두리산오징어": "두리두리 울산본점",
    "Eat Us": "잇어스",
    "아웃닭": "아웃닭치킨하우스 울산대점",
    "BONMILK(본밀크)": "본밀크",
    "산들": "산들 한우육회&불고기비빔밥",
    "100도짬뽕": "백도짬뽕",
    "디디디알캔앤보틀커피 울산언": "DDDR캔&보틀커피 울산언양점",
    "조방낚지찜": "조방낙지찜 언양점",
    "투칸(toucan)": "카페투칸",
    "원조진불고기": "원조진언양불고기",
    "전주콩나물국밥.콩사돈": "콩사돈 언양점",
    "오케이(OK)목장식당": "OK목장",
}
KAKAO_CATEGORY_OVERRIDES_BY_REGION = {
    "guyeong": {
        "839325342": "한식",  # 양포항 구영점
        "50373119": "한식",  # 철판떼기 구영점
        "16438875": "한식",  # 아라쭈꾸미 구영점
        "10129815": "한식",  # 낙지볶음명가개미집 울산구영점
        "1543339688": "한식",  # 곤들애전복
        "718236886": "한식",  # 모조리 구영리2호점
        "13050731": "치킨/피자/버거",  # 또래오래 울산범서점
        "22757796": "치킨/피자/버거",  # 맘스터치 구영리점
        "1900828355": "일식",  # 히로가츠 구영리점
    },
    "cheonsang": {
        "455633372": "한식",  # 뚜구리 본점
        "1789054560": "고기/구이",  # 두구동부산갈매기
        "982470870": "한식",  # 풍성한한식뷔페
    },
    "eonyang": {
        "1655661990": "한식",  # 곱도리탕전문점 언양점
        "16404782": "한식",  # 오돌식당
        "1434025976": "한식",  # 오돌이와불닭발 울산역점
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="카카오 기준 지역 음식점 통합 카탈로그 생성")
    parser.add_argument("region", nargs="?", help="region_config.py의 지역 ID")
    parser.add_argument("--refresh", action="store_true", help="카카오 API 캐시를 사용하지 않고 다시 조회")
    return parser.parse_args()


def configure_region(region_id: str | None) -> None:
    global REGION_ID, ACTIVE_REGION, PUBLIC_PATH, MASTER_PATH, UNMATCHED_PATH
    global REPORT_PATH, OUT_PATH, PRIVATE_CATALOG_PATH, REGION_RECT, ROAD_PATTERN

    REGION_ID, ACTIVE_REGION = get_region(region_id)
    suffix = "" if REGION_ID == "guyeong" else f"-{REGION_ID}"
    PUBLIC_PATH = ROOT / "data" / "processed" / f"public-restaurants-{REGION_ID}.js"
    MASTER_PATH = ROOT / "data" / "processed" / f"{REGION_ID}_restaurant_master.csv"
    UNMATCHED_PATH = ROOT / "data" / "processed" / f"{REGION_ID}_restaurant_excel_unmatched.csv"
    REPORT_PATH = ROOT / "data" / "processed" / f"{REGION_ID}_restaurant_catalog_report.json"
    OUT_PATH = ROOT / f"restaurant-catalog{suffix}.js"
    PRIVATE_CATALOG_PATH = private_catalog_path(ROOT, REGION_ID)
    REGION_RECT = tuple(ACTIVE_REGION["bounds"])
    ROAD_PATTERN = re.compile(ACTIVE_REGION["address_key_pattern"])


def parse_js_array(path: Path, variable_name: str) -> list[dict]:
    value = read_window_value(path, variable_name)
    return value if isinstance(value, list) else []


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def compact(value: str | None) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", clean(value).lower())


def name_aliases(value: str | None) -> list[str]:
    aliases: set[str] = set()
    for raw in re.split(r"[/|]", clean(value)):
        for variant in (raw, re.sub(r"\([^)]*\)", "", raw)):
            normalized = re.sub(r"\(주\)|주식회사|유한회사", "", variant).strip()
            normalized = compact(normalized)
            normalized = normalized.replace("랑콩뜨레", "랑꽁뜨레").replace("센타", "센터")
            if not normalized:
                continue
            aliases.add(normalized)
            trimmed = re.sub(r"(?:울산)?구영(?:리)?점$", "", normalized)
            trimmed = re.sub(r"(?:과자점|제과점)$", "", trimmed)
            if trimmed:
                aliases.add(trimmed)
    return sorted(aliases, key=len, reverse=True)


def name_similarity(left: str | None, right: str | None) -> float:
    left_aliases = name_aliases(left)
    right_aliases = name_aliases(right)
    if not left_aliases or not right_aliases:
        return 0.0

    best = 0.0
    for left_name in left_aliases:
        for right_name in right_aliases:
            ratio = SequenceMatcher(None, left_name, right_name).ratio()
            if left_name in right_name or right_name in left_name:
                ratio = max(ratio, min(len(left_name), len(right_name)) / max(len(left_name), len(right_name)))
            best = max(best, ratio)
    return best


GENERIC_NAME_CORES = {
    "울산",
    "구영",
    "구영리",
    "범서",
    "천상",
    "굴화",
    "무거",
    "언양",
    "삼남",
    "카페",
    "커피",
    "식당",
}
BRANCH_SUFFIX_PATTERN = re.compile(
    r"(?:울산)?(?:구영(?:리)?|범서|천상|굴화|무거|울산대|울산과학대|언양|삼남|유니스트)(?:본점|직영점|점|[0-9]+호점)?$"
)


def name_core_aliases(value: str | None) -> set[str]:
    cores = set(name_aliases(value))
    cores.update(BRANCH_SUFFIX_PATTERN.sub("", alias) for alias in tuple(cores))
    return {core for core in cores if core and core not in GENERIC_NAME_CORES}


def related_names(left: str | None, right: str | None) -> bool:
    for left_name in name_core_aliases(left):
        for right_name in name_core_aliases(right):
            shorter, longer = sorted((left_name, right_name), key=len)
            if len(shorter) >= 2 and shorter in longer:
                return True
    return False


def address_key(value: str | None) -> str:
    return precise_address_key(value, ACTIVE_REGION["address_key_pattern"])


def row_address_key(row: dict) -> str:
    stored = clean(row.get("addressKey") or row.get("address_key") or row.get("excel_address_key")).lower()
    normalized = re.sub(r"[^0-9a-z가-힣_]", "", stored)
    return normalized or address_key(row.get("address") or row.get("excel_address"))


def road_query(value: str | None) -> str:
    text = clean(value).replace(",", " ")
    match = re.search(r"([0-9가-힣]+(?:로|길))\s*(\d+(?:-\d+)?)", text) or ROAD_PATTERN.search(text)
    return match.group(0) if match else ""


def place_address(place: dict) -> str:
    return clean(place.get("road_address_name")) or clean(place.get("address_name"))


def is_region_place(place: dict) -> bool:
    lot_address = clean(place.get("address_name"))
    road_address = clean(place.get("road_address_name"))
    full_address = f"{lot_address} {road_address}"
    if "울산" not in full_address:
        return False
    scope_tokens = ACTIVE_REGION.get("scope_tokens", ACTIVE_REGION["search_tokens"])
    return any(token in full_address for token in scope_tokens)


def is_food_place(place: dict) -> bool:
    category = clean(place.get("category_name")) or clean(place.get("kakaoCategory"))
    name = clean(place.get("place_name")) or clean(place.get("name"))
    if category.startswith(("가정,생활", "서비스,산업", "문화,예술", "여행")):
        return False
    if is_non_restaurant_business(name, category):
        return False
    category_group_code = clean(place.get("category_group_code")) or clean(place.get("kakaoCategoryGroupCode"))
    return category_group_code in {"FD6", "CE7"} or any(
        word in category for word in FOOD_CATEGORY_WORDS
    )


def catalog_category(name: str, kakao_category: str, license_type: str = "", excel_industry: str = "") -> str:
    category = clean(kakao_category)
    name_category = dining_category(name, "", "", "")
    fallback = dining_category(name, category, license_type, excel_industry)

    if name_category == "술집" or "음식점 > 술집" in category:
        return "술집"
    if name_category in {"카페/디저트", "베이커리", "치킨/피자/버거", "도시락", "중식", "일식", "분식/김밥", "국밥/탕", "면/칼국수", "양식"}:
        return name_category
    if any(marker in category for marker in ("제과,베이커리", "떡,한과", "방앗간", "패스트푸드 > 샌드위치", "간식 > 토스트", "간식 > 도넛")):
        return "베이커리"
    if "음식점 > 카페" in category or any(marker in category for marker in ("간식 > 아이스크림", "간식 > 초콜릿")):
        return "카페/디저트"
    if "음식점 > 도시락" in category:
        return "도시락"
    if any(marker in category for marker in ("음식점 > 치킨", "양식 > 피자", "양식 > 햄버거", "패스트푸드 > 버거", "패스트푸드 > 롯데리아", "패스트푸드 > 맘스터치", "패스트푸드 > 맥도날드", "패스트푸드 > KFC", "패스트푸드 > 노브랜드버거", "간식 > 닭강정")):
        return "치킨/피자/버거"
    if "음식점 > 분식" in category:
        return "분식/김밥"
    if "음식점 > 중식" in category:
        return "중식"
    if "음식점 > 일식" in category:
        return "일식"
    if "한식 > 해물,생선" in category:
        if any(marker in category for marker in ("추어", "매운탕,해물탕")):
            return "국밥/탕"
        if any(marker in category for marker in ("낙지", "쭈꾸미", "아구", "생선구이", "코다리")):
            return "한식"
        return "해산물/횟집"
    if "한식 > 육류,고기" in category:
        return fallback if fallback in {"국밥/탕", "치킨/피자/버거"} else "고기/구이"
    if any(marker in category for marker in ("한식 > 국밥", "한식 > 감자탕", "한식 > 찌개,전골", "삼계탕")):
        return "국밥/탕"
    if any(marker in category for marker in ("한식 > 국수", "한식 > 냉면", "아시아음식 > 동남아음식")):
        return "면/칼국수"
    if "음식점 > 양식" in category or any(marker in category for marker in ("음식점 > 샐러드", "음식점 > 뷔페")):
        return "양식"
    if any(marker in category for marker in ("음식점 > 한식", "음식점 > 샤브샤브", "퓨전요리 > 퓨전한식")):
        return fallback if fallback not in {"기타", "술집"} else "한식"
    if any(marker in category for marker in ("음식점 > 간식", "음식점 > 패스트푸드", "음식점 > 푸드코트")):
        return "기타"
    return fallback


def coordinates(item: dict) -> tuple[float, float] | None:
    try:
        lat = float(item.get("y", item.get("lat")))
        lng = float(item.get("x", item.get("lng")))
    except (TypeError, ValueError):
        return None
    return lat, lng


def distance_km(left: dict, right: dict) -> float:
    left_coords = coordinates(left)
    right_coords = coordinates(right)
    if not left_coords or not right_coords:
        return math.inf
    left_lat, left_lng = left_coords
    right_lat, right_lng = right_coords
    radius = 6371
    dlat = math.radians(right_lat - left_lat)
    dlng = math.radians(right_lng - left_lng)
    value = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(left_lat))
        * math.cos(math.radians(right_lat))
        * math.sin(dlng / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(value))


def merge_trends(left: list[dict] | str | None, right: list[dict] | str | None) -> list[dict]:
    counts: defaultdict[str, int] = defaultdict(int)
    left_points = json_array(left) if isinstance(left, str) else (left or [])
    right_points = json_array(right) if isinstance(right, str) else (right or [])
    for point in [*left_points, *right_points]:
        month = clean(point.get("month"))
        if month:
            counts[month] += int_number(point.get("count"))
    return [{"month": month, "count": count} for month, count in sorted(counts.items())]


class KakaoClient:
    def __init__(self, rest_key: str, refresh: bool = False) -> None:
        self.rest_key = rest_key
        self.refresh = refresh
        self.cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}

    def request(self, endpoint: str, params: dict) -> dict:
        query = urllib.parse.urlencode(params)
        cache_key = f"{endpoint}?{query}"
        if not self.refresh and cache_key in self.cache:
            return self.cache[cache_key]

        request = urllib.request.Request(
            f"https://dapi.kakao.com/v2/local/search/{endpoint}.json?{query}",
            headers={"Authorization": f"KakaoAK {self.rest_key}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            data = {"meta": {"total_count": 0, "pageable_count": 0, "is_end": True}, "documents": [], "error": f"{type(exc).__name__}: {exc}"}
        self.cache[cache_key] = data
        time.sleep(0.05)
        return data

    def category_places(self, category_code: str, rect: tuple[float, float, float, float], depth: int = 0) -> list[dict]:
        rect_value = ",".join(f"{value:.7f}" for value in rect)
        base_params = {"category_group_code": category_code, "rect": rect_value, "size": 15}
        first = self.request("category", {**base_params, "page": 1})
        total_count = int(first.get("meta", {}).get("total_count", 0))

        # 카카오는 한 검색영역에서 최대 45건만 노출하므로 밀집구역을 재귀 분할한다.
        if total_count > 45 and depth < 6:
            west, south, east, north = rect
            middle_lng = (west + east) / 2
            middle_lat = (south + north) / 2
            quadrants = (
                (west, south, middle_lng, middle_lat),
                (middle_lng, south, east, middle_lat),
                (west, middle_lat, middle_lng, north),
                (middle_lng, middle_lat, east, north),
            )
            return [place for quadrant in quadrants for place in self.category_places(category_code, quadrant, depth + 1)]

        documents = list(first.get("documents", []))
        page = 1
        current = first
        while not current.get("meta", {}).get("is_end", True) and page < 3:
            page += 1
            current = self.request("category", {**base_params, "page": page})
            documents.extend(current.get("documents", []))
        return documents

    def keyword_places(self, query: str) -> list[dict]:
        return self.request("keyword", {"query": query, "size": 15}).get("documents", [])

    def save(self) -> None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_kakao_places(client: KakaoClient) -> tuple[list[dict], int]:
    places_by_id: dict[str, dict] = {}
    excluded_non_food_ids: set[str] = set()
    for category_code in KAKAO_CATEGORY_CODES:
        for place in client.category_places(category_code, REGION_RECT):
            place_id = clean(place.get("id"))
            if not place_id or not is_region_place(place):
                continue
            if not is_food_place(place):
                excluded_non_food_ids.add(place_id)
                continue
            places_by_id[place_id] = place
    places = sorted(places_by_id.values(), key=lambda place: clean(place.get("place_name")))
    return places, len(excluded_non_food_ids)


def catalog_item(place: dict) -> dict:
    name = clean(place.get("place_name"))
    address = place_address(place)
    category_name = clean(place.get("category_name"))
    kakao_phone = clean(place.get("phone"))
    return {
        "id": f"kakao-{clean(place.get('id'))}",
        "publicId": "",
        "name": name,
        "canonicalName": compact(name),
        "aliases": [],
        "category": catalog_category(name, category_name),
        "address": address,
        "addressKey": address_key(address),
        "lat": round(float(place.get("y")), 7),
        "lng": round(float(place.get("x")), 7),
        "menu": catalog_category(name, category_name),
        "price": 60,
        "score": 50,
        "mentions": 0,
        "mood": "카카오 장소정보",
        "hours": "영업시간 확인 필요",
        "phone": kakao_phone,
        "phoneSource": "카카오 Local API" if kakao_phone else "",
        "source": "카카오 장소정보",
        "sourceUrl": clean(place.get("place_url")),
        "usageCount": 0,
        "usageAmount": 0,
        "avgAmount": 0,
        "usageTrend": [],
        "recentDate": "",
        "matchBasis": "카카오 장소 ID 기준",
        "publicStatus": "카카오 장소 확인",
        "licenseType": "",
        "permitDate": "",
        "hasUnistUsage": False,
        "geocodeSource": "kakao_place",
        "kakaoPlaceId": clean(place.get("id")),
        "kakaoPlaceUrl": clean(place.get("place_url")),
        "kakaoCategory": category_name,
        "kakaoCategoryGroupCode": clean(place.get("category_group_code")),
        "roadAddress": clean(place.get("road_address_name")),
        "lotAddress": clean(place.get("address_name")),
        "publicDataMatched": False,
        "excelDataMatched": False,
        "dataPriority": "kakao>public>excel",
        "dataSources": ["kakao"],
        "combinedScore": None,
    }


def public_match_metrics(item: dict, public_item: dict) -> tuple[bool, float]:
    similarity = max(
        name_similarity(item.get("name"), public_item.get("name")),
        name_similarity(item.get("name"), public_item.get("canonicalName")),
    )
    same_address = bool(row_address_key(item) and row_address_key(item) == row_address_key(public_item))
    nearby = distance_km(item, public_item) <= 0.12
    accepted = (same_address and similarity >= 0.75) or (nearby and similarity >= 0.90)
    score = similarity * 100 + (35 if same_address else 0) + (10 if nearby else 0)
    return accepted, score


def attach_public_data(catalog: list[dict], public_restaurants: list[dict]) -> int:
    used_public_ids = {clean(item.get("publicId")) for item in catalog if item.get("publicDataMatched")}
    by_address: defaultdict[str, list[dict]] = defaultdict(list)
    by_name: defaultdict[str, list[dict]] = defaultdict(list)
    by_grid: defaultdict[tuple[int, int], list[dict]] = defaultdict(list)

    for public_item in public_restaurants:
        public_id = clean(public_item.get("publicId"))
        if not public_id:
            continue
        key = row_address_key(public_item)
        if key:
            by_address[key].append(public_item)
        for alias in name_aliases(public_item.get("name")):
            by_name[alias].append(public_item)
        coords = coordinates(public_item)
        if coords:
            lat, lng = coords
            by_grid[(round(lat / 0.002), round(lng / 0.002))].append(public_item)

    matched = 0
    for item in catalog:
        if item.get("publicDataMatched"):
            continue
        candidate_rows: dict[str, dict] = {}
        key = row_address_key(item)
        for public_item in by_address.get(key, []):
            candidate_rows[clean(public_item.get("publicId"))] = public_item
        for alias in name_aliases(item.get("name")):
            for public_item in by_name.get(alias, []):
                candidate_rows[clean(public_item.get("publicId"))] = public_item
        coords = coordinates(item)
        if coords:
            lat, lng = coords
            grid_lat, grid_lng = round(lat / 0.002), round(lng / 0.002)
            for lat_offset in (-1, 0, 1):
                for lng_offset in (-1, 0, 1):
                    for public_item in by_grid.get((grid_lat + lat_offset, grid_lng + lng_offset), []):
                        candidate_rows[clean(public_item.get("publicId"))] = public_item

        candidates = []
        for public_item in candidate_rows.values():
            public_id = clean(public_item.get("publicId"))
            if not public_id or public_id in used_public_ids:
                continue
            accepted, score = public_match_metrics(item, public_item)
            if accepted:
                candidates.append((score, public_item))
        if not candidates:
            continue
        _, public_item = max(candidates, key=lambda candidate: candidate[0])
        public_id = clean(public_item.get("publicId"))
        public_phone = clean(public_item.get("phone"))
        resolved_category = catalog_category(
            item["name"],
            item["kakaoCategory"],
            clean(public_item.get("licenseType")),
            clean(public_item.get("category")),
        )
        used_public_ids.add(public_id)
        matched += 1
        item.update(
            {
                "publicId": public_id,
                "category": resolved_category,
                "menu": resolved_category,
                "phone": item["phone"] or public_phone,
                "phoneSource": item.get("phoneSource") or ("공공 인허가 데이터" if public_phone else ""),
                "publicStatus": clean(public_item.get("publicStatus")) or "영업상태 확인 필요",
                "licenseType": clean(public_item.get("licenseType")),
                "permitDate": clean(public_item.get("permitDate")),
                "publicDataMatched": True,
                "dataSources": ["kakao", "public"],
            }
        )
    return matched


def public_fallback_item(public_item: dict) -> dict:
    name = clean(public_item.get("name"))
    address = clean(public_item.get("address"))
    category = clean(public_item.get("category")) or catalog_category(
        name,
        "",
        clean(public_item.get("licenseType")),
    )
    usage_count = int_number(public_item.get("usageCount"))
    usage_amount = int_number(public_item.get("usageAmount"))
    phone = clean(public_item.get("phone"))
    coords = coordinates(public_item)
    lat, lng = coords if coords else (0.0, 0.0)
    has_usage = usage_count > 0 and usage_amount > 0
    data_sources = ["public"]
    if has_usage:
        data_sources.append("excel")
    return {
        "id": clean(public_item.get("id")) or f"public-{clean(public_item.get('publicId'))}",
        "publicId": clean(public_item.get("publicId")),
        "name": name,
        "canonicalName": compact(name),
        "aliases": [],
        "category": category,
        "address": address,
        "addressKey": row_address_key(public_item),
        "lat": round(lat, 7),
        "lng": round(lng, 7),
        "menu": category,
        "price": int_number(public_item.get("price"), 60),
        "score": int_number(public_item.get("score"), 50),
        "mentions": usage_count,
        "mood": "사용기반" if has_usage else "공공데이터 영업중 업소",
        "hours": clean(public_item.get("hours")) or "영업시간 확인 필요",
        "phone": phone,
        "phoneSource": "공공 인허가 데이터" if phone else "",
        "source": clean(public_item.get("source")) or "공공 인허가 데이터",
        "sourceUrl": clean(public_item.get("sourceUrl")),
        "usageCount": usage_count,
        "usageAmount": usage_amount,
        "avgAmount": int_number(public_item.get("avgAmount")),
        "usageTrend": public_item.get("usageTrend") if isinstance(public_item.get("usageTrend"), list) else [],
        "recentDate": clean(public_item.get("recentDate")),
        "matchBasis": "공공 인허가 보완(카카오 장소 미등록)",
        "publicStatus": clean(public_item.get("publicStatus")) or "영업상태 확인 필요",
        "licenseType": clean(public_item.get("licenseType")),
        "permitDate": clean(public_item.get("permitDate")),
        "hasUnistUsage": has_usage,
        "geocodeSource": clean(public_item.get("geocodeSource")) or "public_address",
        "kakaoPlaceId": "",
        "kakaoPlaceUrl": "",
        "kakaoCategory": "",
        "kakaoCategoryGroupCode": "",
        "roadAddress": address,
        "lotAddress": "",
        "publicDataMatched": True,
        "publicFallback": True,
        "excelDataMatched": has_usage,
        "dataPriority": "kakao>public>excel",
        "dataSources": data_sources,
        "combinedScore": public_item.get("combinedScore"),
    }


def append_configured_public_fallbacks(catalog: list[dict], public_restaurants: list[dict]) -> int:
    fallback_ids = {clean(value) for value in ACTIVE_REGION.get("public_fallback_ids", []) if clean(value)}
    existing_public_ids = {clean(item.get("publicId")) for item in catalog if clean(item.get("publicId"))}
    public_by_id = {
        clean(item.get("publicId")): item
        for item in public_restaurants
        if clean(item.get("publicId"))
    }
    added = 0
    for public_id in sorted(fallback_ids - existing_public_ids):
        public_item = public_by_id.get(public_id)
        if not public_item or clean(public_item.get("publicStatus")) != "영업중" or not coordinates(public_item):
            continue
        catalog.append(public_fallback_item(public_item))
        added += 1
    return added


def load_usage_rows() -> list[dict[str, str]]:
    master_usage = [row for row in read_csv(MASTER_PATH) if int_number(row.get("usage_count")) > 0]
    for row in master_usage:
        row["usage_row_source"] = "master_matched"
    unmatched_usage = read_csv(UNMATCHED_PATH)
    for row in unmatched_usage:
        row["usage_row_source"] = "excel_unmatched"
    return master_usage + unmatched_usage


def usage_name(row: dict) -> str:
    return clean(row.get("excel_name")) or clean(row.get("name"))


def direct_usage_match(row: dict, catalog: list[dict], by_public_id: dict[str, dict]) -> tuple[dict | None, str]:
    public_id = clean(row.get("public_id"))
    if public_id and public_id in by_public_id:
        return by_public_id[public_id], "public_id"

    target_name = usage_name(row)
    target_hint = PLACE_NAME_HINTS.get(target_name, "")
    target_key = row_address_key(row)
    candidates = []
    for item in catalog:
        similarity = max(
            name_similarity(target_name, item.get("name")),
            name_similarity(target_name, " | ".join(item.get("aliases", []))),
            name_similarity(target_hint, item.get("name")) if target_hint else 0.0,
        )
        same_address = bool(target_key and target_key == row_address_key(item))
        # 구영프라자처럼 도로명 주소를 공유하는 복합상가는 이름이 충분히 같을 때만 합친다.
        accepted = (same_address and (similarity >= 0.75 or related_names(target_name, item.get("name")))) or similarity >= 0.92
        if accepted:
            score = similarity * 100 + (40 if same_address else 0)
            candidates.append((score, item))
    if not candidates:
        return None, ""
    return max(candidates, key=lambda candidate: candidate[0])[1], "name_address"


def keyword_queries(row: dict) -> list[str]:
    name = usage_name(row)
    hint = PLACE_NAME_HINTS.get(name, "")
    address = clean(row.get("excel_address")) or clean(row.get("address"))
    road = road_query(address)
    queries = []
    query_terms = ACTIVE_REGION.get("query_terms", [ACTIVE_REGION["name"]])
    for target_name in [name, hint]:
        if not target_name:
            continue
        queries.extend(f"{target_name} 울산 {term}" for term in query_terms)
        if road:
            queries.append(f"{target_name} {road}")
    if road:
        queries.extend(f"{road} 울산 {term}" for term in query_terms)
    return list(dict.fromkeys(query for query in queries if query))


def keyword_candidate_metrics(row: dict, place: dict, rank: int) -> tuple[bool, float]:
    target_name = usage_name(row)
    hint = PLACE_NAME_HINTS.get(target_name, "")
    name_score = name_similarity(target_name, place.get("place_name"))
    hint_score = name_similarity(hint, place.get("place_name")) if hint else 0.0
    similarity = max(name_score, hint_score)
    target_key = row_address_key(row)
    candidate_key = address_key(place_address(place))
    same_address = bool(target_key and target_key == candidate_key)
    same_name_family = related_names(target_name, place.get("place_name")) or (
        bool(hint) and related_names(hint, place.get("place_name"))
    )
    accepted = is_region_place(place) and is_food_place(place) and (
        similarity >= 0.68
        or (same_address and (similarity >= 0.65 or same_name_family))
        or (same_address and hint_score >= 0.68)
    )
    score = similarity * 70 + (35 if same_address else 0) + (8 if is_region_place(place) else 0) + (7 if is_food_place(place) else 0) - min(rank, 10)
    return accepted, score


def keyword_usage_match(row: dict, client: KakaoClient) -> tuple[dict | None, float]:
    candidates: dict[str, tuple[float, dict]] = {}
    for query in keyword_queries(row):
        for rank, place in enumerate(client.keyword_places(query)):
            place_id = clean(place.get("id"))
            if not place_id:
                continue
            accepted, score = keyword_candidate_metrics(row, place, rank)
            if not accepted:
                continue
            previous = candidates.get(place_id)
            if previous is None or score > previous[0]:
                candidates[place_id] = (score, place)
    if not candidates:
        return None, 0.0
    score, place = max(candidates.values(), key=lambda candidate: candidate[0])
    return place, score


def merge_usage(item: dict, row: dict, method: str) -> None:
    count = int_number(row.get("usage_count"))
    amount = int_number(row.get("usage_amount"))
    item["usageCount"] += count
    item["usageAmount"] += amount
    item["avgAmount"] = round(item["usageAmount"] / item["usageCount"]) if item["usageCount"] else 0
    item["usageTrend"] = merge_trends(item.get("usageTrend"), row.get("usage_trend"))
    item["recentDate"] = max(item.get("recentDate", ""), clean(row.get("recent_date")))
    item["mentions"] = item["usageCount"]
    item["score"] = max(item.get("score", 50), int_number(row.get("score"), 50))
    item["mood"] = "사용기반"
    item["hasUnistUsage"] = item["usageCount"] > 0 and item["usageAmount"] > 0
    item["excelDataMatched"] = True
    item["dataSources"] = list(dict.fromkeys([*item.get("dataSources", []), "excel"]))
    item["aliases"] = sorted(set([*item.get("aliases", []), *[part.strip() for part in re.split(r"[|/]", usage_name(row)) if part.strip()]]))
    item["matchBasis"] = f"카카오 장소 기준 + 엑셀 이용정보({method})"
    item["category"] = catalog_category(
        item["name"],
        item.get("kakaoCategory", ""),
        item.get("licenseType", ""),
        clean(row.get("excel_industry")),
    )
    item["menu"] = item["category"]


def apply_category_overrides(catalog: list[dict]) -> int:
    applied = 0
    category_overrides = KAKAO_CATEGORY_OVERRIDES_BY_REGION.get(REGION_ID, {})
    for item in catalog:
        category = category_overrides.get(clean(item.get("kakaoPlaceId")))
        if not category:
            continue
        item["category"] = category
        item["menu"] = category
        item["categorySource"] = "카카오 장소 ID 검증 예외"
        applied += 1
    return applied


def attach_excel_data(
    catalog: list[dict],
    public_restaurants: list[dict],
    usage_rows: list[dict],
    client: KakaoClient,
) -> tuple[list[dict], list[dict]]:
    report = []
    by_kakao_id = {item["kakaoPlaceId"]: item for item in catalog}
    by_public_id = {item["publicId"]: item for item in catalog if item.get("publicId")}

    for row in usage_rows:
        item, method = direct_usage_match(row, catalog, by_public_id)
        keyword_score = 0.0
        if item is None:
            place, keyword_score = keyword_usage_match(row, client)
            if place is not None:
                place_id = clean(place.get("id"))
                item = by_kakao_id.get(place_id)
                if item is None:
                    item = catalog_item(place)
                    available_public = [
                        public_item
                        for public_item in public_restaurants
                        if clean(public_item.get("publicId")) not in by_public_id
                    ]
                    attach_public_data([item], available_public)
                    catalog.append(item)
                    by_kakao_id[place_id] = item
                    if item.get("publicId"):
                        by_public_id[item["publicId"]] = item
                    method = "keyword_added"
                else:
                    method = "keyword_existing"

        if item is not None:
            merge_usage(item, row, method)
        report.append(
            {
                "excelName": usage_name(row),
                "excelAddress": clean(row.get("excel_address")) or clean(row.get("address")),
                "usageCount": int_number(row.get("usage_count")),
                "source": clean(row.get("usage_row_source")),
                "method": method or "unresolved",
                "kakaoPlaceId": item.get("kakaoPlaceId", "") if item else "",
                "kakaoName": item.get("name", "") if item else "",
                "keywordScore": round(keyword_score, 3),
            }
        )
    return catalog, report


def main() -> None:
    args = parse_args()
    configure_region(args.region)
    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    if not rest_key:
        raise SystemExit("KAKAO_REST_API_KEY 환경변수가 필요합니다.")

    client = KakaoClient(rest_key, refresh=args.refresh)
    public_restaurants = parse_js_array(PUBLIC_PATH, "publicRestaurants")
    kakao_places, kakao_non_food_excluded = collect_kakao_places(client)
    catalog = [catalog_item(place) for place in kakao_places]
    attach_public_data(catalog, public_restaurants)
    public_fallback_added = append_configured_public_fallbacks(catalog, public_restaurants)
    usage_rows = load_usage_rows()
    catalog, usage_report = attach_excel_data(catalog, public_restaurants, usage_rows, client)
    category_overrides_applied = apply_category_overrides(catalog)

    excluded_non_food = [
        item
        for item in catalog
        if is_non_restaurant_business(item.get("name", ""), item.get("kakaoCategory", ""))
        or (not item.get("publicFallback") and not is_food_place(item))
    ]
    catalog = [item for item in catalog if item not in excluded_non_food]
    excluded_bars = [
        item
        for item in catalog
        if item.get("category") == "술집" or "음식점 > 술집" in item.get("kakaoCategory", "")
    ]
    catalog = [item for item in catalog if item not in excluded_bars]
    configured_excluded_names = {compact(name) for name in ACTIVE_REGION.get("excluded_names", [])}
    excluded_configured = [item for item in catalog if compact(item.get("name")) in configured_excluded_names]
    catalog = [item for item in catalog if item not in excluded_configured]

    catalog.sort(key=lambda item: (-item["usageCount"], item["name"]))
    unresolved = [row["excelName"] for row in usage_report if row["method"] == "unresolved"]
    summary = {
        "regionId": REGION_ID,
        "regionName": ACTIVE_REGION["name"],
        "scopeTokens": ACTIVE_REGION.get("scope_tokens", ACTIVE_REGION["search_tokens"]),
        "dataPriority": ["kakao", "public", "excel"],
        "kakaoCategoryPlaces": len(kakao_places),
        "publicAuxiliaryMatched": sum(1 for item in catalog if item["publicDataMatched"]),
        "publicFallbackAdded": public_fallback_added,
        "excelUsageRows": len(usage_rows),
        "excelMatchedToKakao": sum(1 for row in usage_report if row["method"] != "unresolved"),
        "excelKeywordAdded": sum(1 for row in usage_report if row["method"] == "keyword_added"),
        "excelUnresolved": len(unresolved),
        "excelUnresolvedNames": unresolved,
        "restaurantCount": len(catalog),
        "withUsage": sum(1 for item in catalog if item["hasUnistUsage"]),
        "excludedNonRestaurantBusinesses": kakao_non_food_excluded + len(excluded_non_food),
        "excludedBars": len(excluded_bars),
        "excludedConfiguredBusinesses": len(excluded_configured),
        "categoryOverridesApplied": category_overrides_applied,
        "withKakaoPhone": sum(1 for item in catalog if item.get("phoneSource") == "카카오 Local API"),
        "withPublicPhoneFallback": sum(1 for item in catalog if item.get("phoneSource") == "공공 인허가 데이터"),
        "withoutPhone": sum(1 for item in catalog if not item.get("phone")),
        "kakaoHoursAvailable": 0,
        "hoursNote": "카카오 Local 장소 검색 API 응답에는 영업시간 필드가 없어 기존 보강정보가 없으면 확인필요로 유지합니다.",
        "note": f"카카오 장소를 {ACTIVE_REGION['name']} 기준 목록으로 사용하고 비음식 업종과 술집을 제외한 뒤, 행안부 인허가 정보와 엑셀 이용정보를 병합했습니다.",
    }

    client.save()
    REPORT_PATH.write_text(
        json.dumps({"summary": summary, "usageMatches": usage_report}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_private_catalog(PRIVATE_CATALOG_PATH, catalog)
    write_window_values(
        OUT_PATH,
        {"restaurantCatalog": compact_restaurants(catalog)},
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
