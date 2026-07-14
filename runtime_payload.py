from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path


UNKNOWN_HOURS = {"", "확인필요", "영업시간 확인 필요"}
USAGE_SCORE_BASE = 65
USAGE_SCORE_MAX = 95


def number(value: object, default: float = 0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return default


def usage_trend(value: object) -> list[dict[str, int | str]]:
    """Normalize private monthly counts before deriving a public trend."""
    if not isinstance(value, list):
        return []
    return sorted(
        [
            {"month": str(point.get("month") or ""), "count": int(number(point.get("count")))}
            for point in value
            if isinstance(point, dict)
            and re.fullmatch(r"\d{4}-\d{2}", str(point.get("month") or ""))
        ],
        key=lambda point: str(point["month"]),
    )


def public_trend(value: object) -> list[dict[str, int | str]]:
    """Quantize exact counts to five relative levels so counts cannot be recovered."""
    points = usage_trend(value)
    peak = max((int(point["count"]) for point in points), default=0)
    if peak <= 0:
        return []

    result: list[dict[str, int | str]] = []
    for point in points:
        count = int(point["count"])
        level = 0 if count <= 0 else min(4, max(1, math.ceil(count / peak * 4)))
        result.append({"month": point["month"], "level": level})
    return result


def _recent_count(item: Mapping[str, object], month_count: int) -> int:
    return sum(int(point["count"]) for point in usage_trend(item.get("usageTrend"))[-month_count:])


def _monthly_growth(item: Mapping[str, object], month_count: int = 6) -> float:
    points = usage_trend(item.get("usageTrend"))[-month_count:]
    if len(points) < 2:
        return 0
    mean_index = (len(points) - 1) / 2
    mean_count = sum(int(point["count"]) for point in points) / len(points)
    numerator = sum(
        (index - mean_index) * (int(point["count"]) - mean_count)
        for index, point in enumerate(points)
    )
    denominator = sum((index - mean_index) ** 2 for index in range(len(points)))
    return numerator / denominator if denominator else 0


def _usage_metadata(items: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    metadata: list[dict[str, object]] = [{"usageScore": USAGE_SCORE_BASE} for _ in items]
    groups: dict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(items):
        groups[str(item.get("category") or "기타")].append(index)

    for indices in groups.values():
        valid = [
            index
            for index in indices
            if number(items[index].get("usageCount")) > 0
            and number(items[index].get("usageAmount")) > 0
        ]
        if not valid:
            continue
        max_count = max(number(items[index].get("usageCount")) for index in valid)
        max_amount = max(number(items[index].get("usageAmount")) for index in valid)
        combined = {
            index: (
                number(items[index].get("usageCount")) / max(max_count, 1) * 0.5
                + number(items[index].get("usageAmount")) / max(max_amount, 1) * 0.5
            )
            for index in valid
        }
        highest = max(combined.values(), default=1)
        for index, value in combined.items():
            score = round(USAGE_SCORE_BASE + value / max(highest, 1e-9) * (USAGE_SCORE_MAX - USAGE_SCORE_BASE))
            metadata[index]["usageScore"] = max(USAGE_SCORE_BASE + 1, min(USAGE_SCORE_MAX, score))

    visit_indices = [index for index, item in enumerate(items) if number(item.get("usageCount")) > 0]
    visit_indices.sort(
        key=lambda index: (
            -number(items[index].get("usageCount")),
            -number(items[index].get("usageAmount")),
            str(items[index].get("name") or ""),
        )
    )
    for rank, index in enumerate(visit_indices, start=1):
        metadata[index]["visitRank"] = rank

    trend_indices = [
        index
        for index, item in enumerate(items)
        if any(int(point["count"]) > 0 for point in usage_trend(item.get("usageTrend")))
    ]
    trend_indices.sort(
        key=lambda index: (
            -_monthly_growth(items[index]),
            -_recent_count(items[index], 6),
            -number(items[index].get("usageCount")),
            str(items[index].get("name") or ""),
        )
    )
    for rank, index in enumerate(trend_indices, start=1):
        metadata[index]["trendRank"] = rank

    new_entry_indices = [
        index
        for index, item in enumerate(items)
        if _recent_count(item, 12) < 24 and _recent_count(item, 6) >= 12
    ]
    new_entry_indices.sort(
        key=lambda index: (
            -_recent_count(items[index], 6),
            -number(items[index].get("usageCount")),
            -number(items[index].get("usageAmount")),
            str(items[index].get("name") or ""),
        )
    )
    for rank, index in enumerate(new_entry_indices, start=1):
        metadata[index]["newEntryRank"] = rank

    return metadata


def compact_restaurant(item: Mapping[str, object]) -> dict[str, object]:
    """Return non-sensitive fields used by the browser application."""
    category = str(item.get("category") or "기타").strip()
    result: dict[str, object] = {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or "확인필요"),
        "category": category,
        "address": str(item.get("address") or ""),
        "lat": number(item.get("lat")),
        "lng": number(item.get("lng")),
    }

    optional_text = {
        "publicId": item.get("publicId"),
        "phone": item.get("phone"),
    }
    menu = str(item.get("menu") or "").strip()
    if menu and menu != category:
        optional_text["menu"] = menu
    hours = str(item.get("hours") or "").strip()
    if hours not in UNKNOWN_HOURS:
        optional_text["hours"] = hours
    for key, value in optional_text.items():
        text = str(value or "").strip()
        if text:
            result[key] = text

    combined_score = item.get("combinedScore")
    if combined_score not in (None, ""):
        result["combinedScore"] = combined_score
    return result


def compact_restaurants(items: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Create a public catalog with derived values instead of private usage totals."""
    metadata = _usage_metadata(items)
    result = []
    for index, item in enumerate(items):
        public_item = compact_restaurant(item)
        public_item.update(metadata[index])
        trend = public_trend(item.get("usageTrend"))
        if trend:
            public_item["trend"] = trend
        result.append(public_item)
    return result


def compact_bento_restaurant(item: Mapping[str, object]) -> dict[str, object]:
    result = compact_restaurant(item)
    district = str(item.get("district") or "").strip()
    if district:
        result["district"] = district
    result["schoolDistanceKm"] = round(number(item.get("schoolDistanceKm")), 2)
    return result


def private_catalog_path(root: Path, region_id: str) -> Path:
    return root / "data" / "processed" / f"{region_id}_restaurant_catalog_private.json"


def write_private_catalog(path: Path, items: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(items), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def read_private_catalog(path: Path) -> list[dict[str, object]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"Private catalog must be a list: {path}")
    return [item for item in value if isinstance(item, dict)]


def read_window_value(path: Path, variable_name: str) -> object:
    source = path.read_text(encoding="utf-8-sig")
    match = re.search(rf"window\.{re.escape(variable_name)}\s*=\s*", source)
    if not match:
        raise ValueError(f"{path.name}에서 window.{variable_name} 값을 찾지 못했습니다.")
    value, _ = json.JSONDecoder().raw_decode(source[match.end() :])
    return value


def write_window_values(path: Path, values: Mapping[str, object]) -> None:
    source = "".join(
        f"window.{name}={json.dumps(value, ensure_ascii=False, separators=(',', ':'))};\n"
        for name, value in values.items()
    )
    path.write_text(source, encoding="utf-8")
