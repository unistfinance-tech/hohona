from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from region_config import REGIONS
from runtime_payload import (
    private_catalog_path,
    public_trend,
    read_private_catalog,
    write_window_values,
)


ROOT = Path(__file__).resolve().parent
OUTPUT_PATH = ROOT / "restaurant-ranking.js"
DEFAULT_LIMIT = 100
REGION_IDS = ("guyeong", "cheonsang", "gulhwa", "eonyang", "mugeo")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="지역 음식점 통합 방문 랭킹 생성")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="출력할 순위 수")
    return parser.parse_args()


def compact(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())


def number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def load_catalog(region_id: str) -> list[dict[str, object]]:
    path = private_catalog_path(ROOT, region_id)
    if not path.exists():
        raise FileNotFoundError(
            f"비공개 원본 카탈로그가 없습니다: {path}. 먼저 해당 지역 카탈로그를 생성하세요."
        )
    return read_private_catalog(path)


def is_lunchbox(item: dict) -> bool:
    name = " ".join(str(item.get(key) or "") for key in ("name", "canonicalName"))
    if re.search(r"도시락|한솥|본도시락", name):
        return True

    item_type = " ".join(str(item.get(key) or "") for key in ("category", "menu"))
    return bool(re.search(r"도시락|케이터링|출장조리|출장요리|배달전문", item_type))


def restaurant_key(item: dict) -> str:
    for field in ("kakaoPlaceId", "id", "publicId"):
        value = compact(item.get(field))
        if value:
            return f"{field}:{value}"
    return f"fallback:{compact(item.get('name'))}:{compact(item.get('address'))}"


def build_ranking(limit: int = DEFAULT_LIMIT) -> dict:
    if limit < 1:
        raise ValueError("limit은 1 이상이어야 합니다.")

    candidates: dict[str, dict] = {}
    source_counts: dict[str, int] = {}

    for region_order, region_id in enumerate(REGION_IDS):
        region = REGIONS[region_id]
        excluded_names = {compact(name) for name in region.get("excluded_names", [])}
        catalog = load_catalog(region_id)
        source_counts[region_id] = len(catalog)

        for item in catalog:
            usage_count = int(number(item.get("usageCount")))
            if usage_count <= 0 or is_lunchbox(item):
                continue
            if compact(item.get("name")) in excluded_names:
                continue

            candidate = {
                "id": str(item.get("id") or item.get("kakaoPlaceId") or restaurant_key(item)),
                "name": str(item.get("name") or "확인필요"),
                "regionId": region_id,
                "regionName": region["name"].replace("·", ""),
                "category": str(item.get("category") or "기타").strip(),
                "usageCount": usage_count,
                "usageTrend": item.get("usageTrend"),
                "regionOrder": region_order,
                "usageAmount": number(item.get("usageAmount")),
            }
            key = restaurant_key(item)
            previous = candidates.get(key)
            if previous is None or (candidate["usageCount"], candidate["usageAmount"]) > (
                previous["usageCount"],
                previous["usageAmount"],
            ):
                candidates[key] = candidate

    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            -item["usageCount"],
            -item["usageAmount"],
            item["name"],
            item["regionOrder"],
        ),
    )[:limit]

    items = []
    for rank, item in enumerate(ranked, start=1):
        items.append(
            {
                "rank": rank,
                "id": item["id"],
                "name": item["name"],
                "regionId": item["regionId"],
                "regionName": item["regionName"],
                "category": item["category"],
                "trend": public_trend(item["usageTrend"]),
            }
        )

    return {
        "generatedAt": date.today().isoformat(),
        "criteria": "비공개 원자료 기반 방문 순위",
        "excluded": ["도시락"],
        "regionIds": list(REGION_IDS),
        "sourceCounts": source_counts,
        "limit": limit,
        "items": items,
    }


def write_ranking(limit: int = DEFAULT_LIMIT) -> dict:
    ranking = build_ranking(limit)
    write_window_values(OUTPUT_PATH, {"restaurantRanking": ranking})
    return ranking


def main() -> None:
    args = parse_args()
    ranking = write_ranking(args.limit)
    print(
        json.dumps(
            {
                "output": OUTPUT_PATH.name,
                "regions": ranking["regionIds"],
                "items": len(ranking["items"]),
                "first": ranking["items"][0]["name"] if ranking["items"] else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
