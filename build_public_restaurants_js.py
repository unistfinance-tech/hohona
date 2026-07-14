from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from region_config import get_region


ROOT = Path.cwd()
CACHE_PATH = ROOT / "data" / "processed" / "kakao_geocode_cache.json"
BASE_LAT = 35.5761
BASE_LNG = 129.1896
PUBLIC_DATA_SOURCE_URLS = {
    "일반음식점": "https://www.data.go.kr/data/15045016/fileData.do",
    "휴게음식점": "https://www.data.go.kr/data/15006730/fileData.do",
}


def clean(value: str | None) -> str:
    return str(value or "").strip()


def number(value: str | None, default: float = 0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def int_number(value: str | None, default: int = 0) -> int:
    return int(round(number(value, default)))


def json_array(value: str | None) -> list[dict]:
    try:
        parsed = json.loads(clean(value) or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def slug(name: str, public_id: str, address: str) -> str:
    base = "".join(ch if ch.isalnum() else "-" for ch in name).strip("-").lower() or "restaurant"
    digest = hashlib.md5(f"{public_id}|{name}|{address}".encode("utf-8")).hexdigest()[:8]
    return f"public-{base[:26]}-{digest}"


def fallback_coords(row: dict[str, str], index: int, center_lat: float, center_lng: float) -> tuple[float, float]:
    seed = f"{row.get('public_id')}|{row.get('address')}|{row.get('name')}|{index}"
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    h1 = int(digest[:8], 16)
    h2 = int(digest[8:16], 16)
    lat = center_lat + ((h1 % 1800) - 900) / 100000
    lng = center_lng + ((h2 % 1800) - 900) / 100000
    return round(lat, 7), round(lng, 7)


def distance_km(lat: float, lng: float) -> float:
    radius = 6371
    dlat = math.radians(lat - BASE_LAT)
    dlng = math.radians(lng - BASE_LNG)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(BASE_LAT)) * math.cos(math.radians(lat)) * math.sin(dlng / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def contains_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


def is_convenience_store(name: str) -> bool:
    compact_name = "".join(name.lower().split())
    markers = [
        "gs25",
        "지에스25",
        "세븐일레븐",
        "이마트24",
        "미니스톱",
        "gs수퍼마켓",
        "지에스수퍼마켓",
        "gs더프레시",
        "지에스더프레시",
    ]
    return contains_any(compact_name, markers) or compact_name.startswith(("cu", "씨유"))


def is_non_restaurant_business(name: str, category: str = "") -> bool:
    text = f"{name} {category}".lower().replace(" ", "")
    markers = (
        "문구팬시",
        "팬시점",
        "문구점",
        "pc",
        "피씨",
        "pc방",
        "피씨방",
        "보드게임카페",
        "보드카페",
        "만화카페",
        "만화방",
        "키즈카페",
        "키즈룸",
        "게임방,pc방",
        "블럭나무",
        "제라&티",
        "제라앤티",
    )
    return any(marker in text for marker in markers)


def dining_category(name: str, public_category: str, license_type: str, excel_industry: str = "") -> str:
    name_text = name.lower()
    metadata_text = f"{public_category} {license_type} {excel_industry}".lower()

    # Prefer explicit business names; public subcategories are often broad or stale.
    if contains_any(name_text, ["카페", "까페", "커피", "다방", "디저트", "빙수", "아이스크림", "요거트", "설빙", "배스킨", "베스킨", "투썸", "스타벅스", "이디야", "메가커피", "메가엠지씨", "컴포즈", "더벤티", "파스쿠찌", "빽다방", "공차", "요아정", "쥬스", "주스", "스트로우", "초콜릿", "크레페"]):
        return "카페/디저트"
    if contains_any(name_text, ["베이커리", "제과", "빵", "파리바게", "뚜레쥬르", "브레드", "샌드위치", "샌드", "토스트", "써브웨이", "서브웨이", "호두과자", "복호두", "도넛", "도너", "던킨", "크리스피크림", "꽈배기", "병과", "찹쌀"]):
        return "베이커리"
    if contains_any(name_text, ["블럭나무", "제라&티", "제라앤티", "문구팬시", "pc방", "피씨방", "피씨"]) or "pc" in name_text:
        return "기타"
    if contains_any(name_text, ["국밥", "감자탕", "갈비탕", "삼계탕", "백숙", "추어탕", "어탕", "곰탕", "설렁탕"]):
        return "국밥/탕"
    if contains_any(name_text, ["칼국수", "칼국시", "국수", "국시", "냉면", "밀면", "막국수"]):
        return "면/칼국수"
    if contains_any(name_text, ["중식", "중국", "짜장", "짬뽕", "반점", "마라", "탕화", "양꼬치", "훠궈", "차이나"]):
        return "중식"
    if contains_any(name_text, ["일식", "스시", "초밥", "참치", "돈카츠", "돈까스", "카츠", "라멘", "이자카야", "사시미", "우동", "소바", "갓포", "돈갓"]):
        return "일식"
    if contains_any(name_text, ["횟집", "회", "해산물", "복국", "복어", "아구", "아귀", "장어", "낙지", "조개", "해물", "수산", "바다"]):
        return "해산물/횟집"
    if contains_any(name_text, ["도시락", "케이터링", "출장조리", "출장요리", "배달전문"]):
        return "도시락"
    if contains_any(name_text, ["치킨", "통닭", "닭강정", "찜닭", "닭똥집", "피자", "버거", "햄버거", "롯데리아", "맘스터치", "맥도날드", "노브랜드버거", "kfc"]):
        return "치킨/피자/버거"
    if contains_any(name_text, ["고기", "갈비", "삼겹", "돼지", "소고기", "한우", "육회", "족발", "보쌈", "곱창", "막창", "닭갈비", "불고기", "정육", "구이", "숯불", "화로", "자연처럼"]):
        return "고기/구이"
    if contains_any(name_text, ["분식", "김밥", "떡볶", "순대", "튀김", "라볶", "유부", "만두", "어묵", "타코야끼", "강다짐", "화떡화떡", "로얄푸드랩", "다섯꼬마"]):
        return "분식/김밥"
    if contains_any(name_text, ["핫도그", "호떡", "매점", "밀키트", "싸가지고가게"]):
        return "기타"
    if contains_any(name_text, ["술집", "호프", "포차", "소주방", "대포", "맥주", "비어", "bar", "와인", "펍", "pub", "홀덤", "투다리", "마누팍투스", "홍대당나귀", "반주", "호맥", "제우스홉"]):
        return "술집"
    if contains_any(name_text, ["경양식", "양식", "레스토랑", "브런치", "스테이크", "파스타", "리조또", "필라프", "함박", "타코"]):
        return "양식"
    if contains_any(name_text, ["한식", "밥", "식당", "가든", "정식", "한정식", "백반", "쌈밥", "두부", "콩나물", "찜", "조림"]):
        return "한식"

    if contains_any(metadata_text, ["카페", "까페", "커피전문점", "다방", "디저트", "빙수", "아이스크림", "요거트"]):
        return "카페/디저트"
    if contains_any(metadata_text, ["베이커리", "제과", "과자점", "떡,한과", "떡집", "방앗간"]):
        return "베이커리"
    if contains_any(metadata_text, ["중식", "중국음식"]):
        return "중식"
    if contains_any(metadata_text, ["횟집", "해산물", "해물,생선"]):
        return "해산물/횟집"
    if contains_any(metadata_text, ["일식", "일식회집"]):
        return "일식"
    if contains_any(metadata_text, ["도시락", "케이터링", "출장조리", "출장요리", "배달전문"]):
        return "도시락"
    if contains_any(metadata_text, ["패스트푸드", "고기/치킨", "치킨", "닭강정", "피자", "햄버거", "버거"]):
        return "치킨/피자/버거"
    if contains_any(metadata_text, ["식육", "고기", "숯불구이"]):
        return "고기/구이"
    if contains_any(metadata_text, ["국밥", "탕", "찌개", "해장국", "감자탕", "설렁탕", "곰탕", "삼계탕", "추어탕", "매운탕", "백숙"]):
        return "국밥/탕"
    if contains_any(metadata_text, ["칼국수", "칼국시", "국수", "국시", "냉면", "밀면", "막국수", "국밥/면"]):
        return "면/칼국수"
    if contains_any(metadata_text, ["분식", "김밥", "떡볶", "순대", "튀김", "라볶", "유부", "만두"]):
        return "분식/김밥"
    if contains_any(metadata_text, ["간편식", "스낵", "음식점 > 간식"]):
        return "기타"
    if contains_any(metadata_text, ["경양식", "양식", "서양음식"]):
        return "양식"
    if contains_any(metadata_text, ["정종", "대포집", "소주방", "주점", "술집", "호프"]):
        return "술집"
    if contains_any(metadata_text, ["일반한식", "한식"]):
        return "한식"
    return "기타"


def load_cache() -> dict[str, dict]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict[str, dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def kakao_get(url: str, rest_key: str) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {rest_key}"})
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def address_candidates(address: str) -> list[str]:
    candidates = [address.strip()]
    base = address.split(",", 1)[0].strip()
    if base:
        candidates.append(base)
    no_parens = " ".join(part for part in address.replace("(", " ").replace(")", " ").split() if part)
    if no_parens:
        candidates.append(no_parens)
    seen = set()
    return [item for item in candidates if item and not (item in seen or seen.add(item))]


def geocode(address: str, rest_key: str, cache: dict[str, dict]) -> dict:
    key = address.strip()
    if key in cache and cache[key].get("ok"):
        return cache[key]

    result = {"ok": False, "lat": None, "lng": None, "source": "fallback", "raw": None}
    for candidate in address_candidates(key):
        encoded = urllib.parse.quote(candidate)
        url = f"https://dapi.kakao.com/v2/local/search/address.json?query={encoded}"
        try:
            data = kakao_get(url, rest_key)
            documents = data.get("documents", [])
            if documents:
                doc = documents[0]
                result = {
                    "ok": True,
                    "lat": float(doc["y"]),
                    "lng": float(doc["x"]),
                    "source": "kakao_address",
                    "query": candidate,
                    "raw": {
                        "address_name": doc.get("address_name"),
                        "road_address": (doc.get("road_address") or {}).get("address_name"),
                        "address": (doc.get("address") or {}).get("address_name"),
                    },
                }
                break
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        time.sleep(0.08)

    cache[key] = result
    return result


def main() -> None:
    region_id, region = get_region(sys.argv[1] if len(sys.argv) > 1 else None)
    suffix = "" if region_id == "guyeong" else f"-{region_id}"
    master_path = ROOT / "data" / "processed" / f"{region_id}_restaurant_master.csv"
    match_summary_path = ROOT / "data" / "processed" / f"{region_id}_restaurant_match_summary.json"
    out_path = ROOT / "data" / "processed" / f"public-restaurants-{region_id}.js"
    center_lat = float(region["center"]["lat"])
    center_lng = float(region["center"]["lng"])
    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    if not rest_key:
        raise SystemExit("KAKAO_REST_API_KEY 환경변수가 필요합니다.")

    cache = load_cache()
    restaurants = []
    geocoded = 0
    fallback = 0
    excluded_convenience_stores = 0
    excluded_non_restaurants = 0
    excluded_bars = 0

    with master_path.open(encoding="utf-8-sig", newline="") as file:
        rows = [row for row in csv.DictReader(file) if row.get("is_active") == "Y"]

    for index, row in enumerate(rows):
        name = clean(row.get("name"))
        if is_convenience_store(name):
            excluded_convenience_stores += 1
            continue
        if is_non_restaurant_business(name, clean(row.get("category"))):
            excluded_non_restaurants += 1
            continue

        license_type = clean(row.get("license_type"))
        category = dining_category(
            name,
            clean(row.get("category")),
            license_type,
            clean(row.get("excel_industry")),
        )
        if category == "술집":
            excluded_bars += 1
            continue

        address = clean(row.get("address"))
        geo = geocode(address, rest_key, cache) if address else {"ok": False}
        if geo.get("ok"):
            lat = round(float(geo["lat"]), 7)
            lng = round(float(geo["lng"]), 7)
            geocoded += 1
        else:
            lat, lng = fallback_coords(row, index, center_lat, center_lng)
            fallback += 1

        usage_count = int_number(row.get("usage_count"))
        usage_amount = int_number(row.get("usage_amount"))
        has_usage = usage_count > 0 and usage_amount > 0
        score = max(50, min(100, int_number(row.get("score")))) if has_usage else 50
        restaurants.append(
            {
                "id": slug(name, clean(row.get("public_id")), address),
                "publicId": clean(row.get("public_id")),
                "name": name,
                "canonicalName": clean(row.get("name_key")) or name,
                "category": category,
                "address": address,
                "addressKey": clean(row.get("address_key")),
                "lat": lat,
                "lng": lng,
                "menu": ", ".join(part for part in [category, license_type] if part),
                "price": 60,
                "score": score,
                "mentions": usage_count,
                "mood": "사용기반" if has_usage else "공공데이터 영업중 업소",
                "hours": "영업시간 확인 필요",
                "phone": clean(row.get("phone")),
                "source": "행안부 지방행정 인허가 공공데이터",
                "sourceUrl": PUBLIC_DATA_SOURCE_URLS.get(license_type, ""),
                "usageCount": usage_count,
                "usageAmount": usage_amount,
                "avgAmount": int_number(row.get("avg_amount")),
                "perPersonAmount": int_number(row.get("per_person_amount")),
                "attendeeSampleCount": int_number(row.get("attendee_sample_count")),
                "usageTrend": json_array(row.get("usage_trend")),
                "recentDate": clean(row.get("recent_date")),
                "memoSample": clean(row.get("memo_sample")),
                "matchBasis": clean(row.get("match_reason")) or "공공데이터 영업중 업소",
                "publicStatus": clean(row.get("status_note")) or "영업상태 확인 필요",
                "licenseType": license_type,
                "permitDate": clean(row.get("permit_date")),
                "hasUnistUsage": has_usage,
                "geocodeSource": geo.get("source", "fallback"),
                "combinedScore": None,
            }
        )

    restaurants.sort(key=lambda item: (not item["hasUnistUsage"], -item["score"], -item["usageCount"], distance_km(item["lat"], item["lng"]), item["name"]))
    match_summary = json.loads(match_summary_path.read_text(encoding="utf-8")) if match_summary_path.exists() else {}
    summary = {
        "regionId": region_id,
        "regionName": region["name"],
        "sourceType": "local-generated-data",
        "usageDateStart": clean(match_summary.get("excel_date_start")),
        "usageDateEnd": clean(match_summary.get("excel_date_end")),
        "usageFilterBasis": clean(match_summary.get("excel_filter_basis")),
        "restaurantCount": len(restaurants),
        "withUnistUsage": sum(1 for item in restaurants if item["hasUnistUsage"]),
        "publicOnly": sum(1 for item in restaurants if not item["hasUnistUsage"]),
        "excludedConvenienceStores": excluded_convenience_stores,
        "excludedNonRestaurantBusinesses": excluded_non_restaurants,
        "excludedBars": excluded_bars,
        "kakaoGeocoded": geocoded,
        "fallbackGeocoded": fallback,
        "usageScoreFormula": "카테고리별 이용횟수와 총사용금액을 50%씩 정규화, 카테고리 1위 95점, 데이터 없음 65점",
        "note": "공공데이터 영업중 업소 중 편의점·비음식 업종·술집을 제외하고, 주소는 카카오 Local API로 위경도 변환했습니다.",
    }

    save_cache(cache)
    out_path.write_text(
        "window.publicRestaurants = "
        + json.dumps(restaurants, ensure_ascii=False, indent=2)
        + ";\nwindow.publicRestaurantSummary = "
        + json.dumps(summary, ensure_ascii=False, indent=2)
        + ";\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
