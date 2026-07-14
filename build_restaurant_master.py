from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from address_keys import address_key
from build_public_restaurants_js import geocode, load_cache, save_cache
from region_config import get_region
from usage_dates import ACTUAL_USAGE_START_DATE, ACTUAL_USAGE_START_MONTH, actual_usage_dates


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUT_DIR = DATA_DIR / "processed"
SOURCE_DIR = ROOT / "input"
SOURCE_FILE_HINT = "개인정보제외파일"

NON_FOOD_PATTERNS = [
    "다이소",
    "약국",
    "수정철물",
    "워싱데이",
    "PBS COLOR LAB",
    "구암서점",
    "오피스디포",
    "다컴",
    "엔젤정보",
    "유니텍",
    "에스엘티",
    "셀리노",
    "켐브레인",
    "에스앤아이",
    "유앤테크",
    "보담유통",
    "새천년약국",
    "지에스더프레시",
    "씨제이올리브네트웍스",
    "CJ올리브네트웍스",
    "CJ OliveNetworks",
]

FOOD_HINTS = ["회의비"]
FOOD_SERVICE_INDUSTRIES = {
    "일반한식",
    "서양음식",
    "한식",
    "일반대중음식",
    "중국음식",
    "제과점",
    "스넥",
    "일식회집",
    "패스트푸드",
    "중식",
    "일식",
    "양식",
    "커피전문점",
    "기타음료식품",
    "부페",
}
DROP_MEMO_PATTERNS = ["카드취소", "전액카드취소", "취소예정", "오사용", "환불", "반품"]
BRANCH_WORD_PATTERN = r"울산|구영리점|구영점|울산구영리점|범서점|직영점|본점|점"

ALIASES = {
    "호훈테이블hohoontable": "호훈테이블",
    "호훈테이블": "호훈테이블",
    "하삼동커피울산구영점": "하삼동커피",
    "하삼동구영범서점": "하삼동커피",
    "정성순대울산구영리점": "정성순대",
    "정성순대울산구영점": "정성순대",
    "써브웨이울산구영점": "써브웨이",
    "서브웨이울산구영점": "써브웨이",
    "찬솔사회적협동조합": "unist지관서가",
    "지관서가유니스트": "unist지관서가",
    "unist지관서가": "unist지관서가",
}

BUSINESS_MERCHANT_OVERRIDES = {
    "3168206400": "UNIST 지관서가",
}


def find_excel_file(explicit_path: str | None) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        if not path.exists():
            raise FileNotFoundError(path)
        return path
    files = sorted(SOURCE_DIR.glob("*.xlsx"), key=lambda file: file.stat().st_mtime, reverse=True)
    hinted = [file for file in files if SOURCE_FILE_HINT in file.name]
    if hinted:
        return hinted[0]
    if files:
        return files[0]
    raise FileNotFoundError(f"{SOURCE_DIR}에서 xlsx 파일을 찾지 못했습니다.")


def clean(value: str | None) -> str:
    return str(value or "").strip()


def normalize_text(value: str | None) -> str:
    text = clean(value).lower()
    text = re.sub(r"\(주\)|㈜|주식회사", "", text)
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def normalize_name(value: str | None) -> str:
    key = normalize_text(value)
    key = re.sub(BRANCH_WORD_PATTERN, "", key)
    return ALIASES.get(key, key)


def normalize_address(value: str | None) -> str:
    text = clean(value)
    text = re.sub(r"\s+", " ", text)
    return text.replace("울산광역시", "울산").replace(".", "")


def normalize_business_id(value: str | None) -> str:
    return re.sub(r"[^0-9]", "", clean(value))


def normalize_industry(value: str | None) -> str:
    return re.sub(r"\s+", "", clean(value))


def contains_any(text: str, patterns: list[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def public_category(row: dict[str, str], license_type: str) -> str:
    raw = clean(row.get("위생업태명")) or clean(row.get("업태구분명")) or license_type
    name = clean(row.get("사업장명"))
    text = f"{raw} {name}"
    if any(word in text for word in ["도시락", "케이터링", "출장조리", "출장요리", "배달전문"]):
        return "도시락"
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


def public_status(row: dict[str, str]) -> str:
    status = clean(row.get("영업상태명"))
    detail = clean(row.get("상세영업상태명"))
    closed = clean(row.get("폐업일자"))
    text = f"{status} {detail}"
    if "폐업" in text:
        return f"폐업({closed})" if closed else "폐업"
    if "중지" in text or "정지" in text or "취소" in text or "말소" in text:
        return text.strip()
    if status == "영업/정상" and detail in ("영업", "정상", ""):
        return "영업중"
    return detail or status or "확인 필요"


def row_address(row: dict[str, str]) -> str:
    return clean(row.get("도로명주소")) or clean(row.get("지번주소"))


def in_region_address(value: str, tokens: list[str]) -> bool:
    text = normalize_address(value)
    return any(token in text for token in tokens)


def read_public_rows(region: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for license_type, source_path in region["localdata_files"]:
        path = ROOT / source_path
        with path.open("r", encoding="cp949", errors="replace", newline="") as file:
            reader = csv.DictReader(file)
            for row in reader:
                address = row_address(row)
                full_address = " ".join([clean(row.get("도로명주소")), clean(row.get("지번주소"))])
                if not in_region_address(full_address, region.get("scope_tokens", region["search_tokens"])):
                    continue
                status_note = public_status(row)
                name = clean(row.get("사업장명"))
                rows.append(
                    {
                        "public_id": clean(row.get("관리번호")),
                        "name": name,
                        "name_key": normalize_name(name),
                        "address": address,
                        "address_key": address_key(address, region["address_key_pattern"]),
                        "category": public_category(row, license_type),
                        "license_type": license_type,
                        "status_note": status_note,
                        "is_active": "Y" if status_note == "영업중" else "N",
                        "permit_date": clean(row.get("인허가일자")),
                        "closed_date": clean(row.get("폐업일자")),
                        "phone": clean(row.get("전화번호")),
                        "x": clean(row.get("좌표정보(X)")),
                        "y": clean(row.get("좌표정보(Y)")),
                        "last_modified": clean(row.get("최종수정시점")),
                    }
                )
    rows.sort(key=lambda row: (row["is_active"] != "Y", row["name"], row["address"]))
    return rows


def normalized_usage_scores(counts: pd.Series, amounts: pd.Series) -> pd.Series:
    scores = pd.Series(50, index=counts.index, dtype=float)
    valid = (counts > 0) & (amounts > 0)
    if not valid.any():
        return scores.astype(int)

    count_norm = counts / max(counts.loc[valid].max(), 1)
    amount_norm = amounts / max(amounts.loc[valid].max(), 1)
    combined = count_norm + amount_norm
    highest = max(float(combined.loc[valid].max()), 1e-9)
    scores.loc[valid] = 50 + combined.loc[valid] / highest * 50
    scores.loc[valid] = scores.loc[valid].round().clip(51, 100)
    return scores.astype(int)


def category_normalized_usage_scores(
    categories: pd.Series, counts: pd.Series, amounts: pd.Series
) -> pd.Series:
    scores = pd.Series(50, index=counts.index, dtype=int)
    for category_name in categories.fillna("기타").unique():
        category_mask = categories.fillna("기타") == category_name
        scores.loc[category_mask] = normalized_usage_scores(
            counts.loc[category_mask], amounts.loc[category_mask]
        )
    return scores.astype(int)


def score_usage(grouped: pd.DataFrame) -> pd.DataFrame:
    if grouped.empty:
        grouped["score"] = []
        return grouped
    grouped["score"] = normalized_usage_scores(grouped["usage_count"], grouped["usage_amount"])
    return grouped


def usage_trend_by_group(scoped: pd.DataFrame, amount_col: str) -> dict[str, str]:
    dated = scoped.copy()
    dated["_date"] = pd.to_datetime(dated["_actual_usage_date"], errors="coerce")
    dated = dated.dropna(subset=["_date"])
    if dated.empty:
        return {}

    first_month = pd.Period(ACTUAL_USAGE_START_MONTH, freq="M")
    latest_month = dated["_date"].max().to_period("M")
    months = list(pd.period_range(first_month, latest_month, freq="M"))
    month_labels = [str(month) for month in months]
    dated["_month"] = dated["_date"].dt.to_period("M").astype(str)
    monthly = dated.groupby(["_group_key", "_month"])[amount_col].size()

    trends: dict[str, str] = {}
    for group_key in dated["_group_key"].dropna().unique():
        points = [{"month": month, "count": int(monthly.get((group_key, month), 0))} for month in month_labels]
        trends[group_key] = json.dumps(points, ensure_ascii=False, separators=(",", ":"))
    return trends


def attendee_count_from_memo(value: str) -> int | None:
    text = str(value or "")
    matches = []
    for pattern, includes_writer in [
        (r"외\s*(\d{1,2})\s*(?:인|명)", True),
        (r"총\s*(\d{1,2})\s*(?:인|명)", False),
        (r"(\d{1,2})\s*(?:인|명)", False),
    ]:
        for match in re.finditer(pattern, text):
            count = int(match.group(1)) + (1 if includes_writer else 0)
            if 1 <= count <= 60:
                matches.append(count)
    return max(matches) if matches else None


def geocode_scope_text(result: dict) -> str:
    raw = result.get("raw") or {}
    return " ".join(
        clean(raw.get(field))
        for field in ("address", "address_name", "road_address")
    )


def is_region_geocode(result: dict, region: dict) -> bool:
    if not result.get("ok"):
        return False
    scope_tokens = region.get("scope_tokens", region["search_tokens"])
    text = geocode_scope_text(result)
    return any(token in text for token in scope_tokens)


def kakao_region_address_keys(
    addresses: list[str],
    region: dict,
    known_keys: set[str],
) -> tuple[set[str], int]:
    cache = load_cache()
    resolved_keys: set[str] = set()
    cached_keys: set[str] = set()
    pattern = region["address_key_pattern"]

    for result in cache.values():
        if not result.get("ok"):
            continue
        raw = result.get("raw") or {}
        raw_address = clean(raw.get("road_address")) or clean(raw.get("address_name")) or clean(raw.get("address"))
        key = address_key(raw_address, pattern)
        if not key:
            continue
        cached_keys.add(key)
        if is_region_geocode(result, region):
            resolved_keys.add(key)

    rest_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    api_queries = 0
    cache_changed = False
    for value in sorted(set(addresses)):
        key = address_key(value, pattern)
        if not key or key in known_keys or key in cached_keys:
            continue

        result = cache.get(value)
        if result is None and rest_key:
            result = geocode(value, rest_key, cache)
            api_queries += 1
            cache_changed = True
        if result and is_region_geocode(result, region):
            resolved_keys.add(key)

    if cache_changed:
        save_cache(cache)
    return resolved_keys, api_queries


def read_excel_usage(
    region: dict,
    excel_path: Path,
    public_rows: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, str]], dict[str, str | int]]:
    df = pd.read_excel(excel_path, sheet_name=0)
    cols = list(df.columns)
    amount_col = next(col for col in cols if str(col) == "금액")
    merchant_col = next(col for col in cols if str(col) in ["가맹점명", "음식점명", "업체명"])
    memo_col = next((col for col in cols if str(col) == "적요"), None)
    business_col = next((col for col in cols if str(col) in ["가맹점사업자번호", "사업자등록번호"]), None)
    industry_col = next((col for col in cols if str(col) in ["업종", "업종명"]), None)
    date_col = next(col for col in cols if str(col) == "결제일")
    address_cols = [col for col in cols if str(col).startswith("가맹점주소") or str(col) in ["주소", "소재지"]]
    if memo_col is None and industry_col is None:
        raise ValueError("적요 또는 업종 열이 필요합니다.")

    for col in [merchant_col, *address_cols, *([memo_col] if memo_col else []), *([industry_col] if industry_col else []), *([business_col] if business_col else [])]:
        df[col] = df[col].fillna("").astype(str)
    df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce").fillna(0)
    df["_actual_usage_date"] = actual_usage_dates(df[date_col])
    df["_address"] = df[address_cols].agg(" ".join, axis=1).map(normalize_address)
    df["_business_id"] = df[business_col].map(normalize_business_id) if business_col else ""
    df["_merchant_name"] = df[merchant_col]
    for business_id, merchant_name in BUSINESS_MERCHANT_OVERRIDES.items():
        df.loc[df["_business_id"] == business_id, "_merchant_name"] = merchant_name
    df["_merchant_key"] = df["_merchant_name"].map(normalize_name)
    df["_address_key"] = df["_address"].map(lambda value: address_key(value, region["address_key_pattern"]))
    df["_memo"] = df[memo_col] if memo_col else ""
    df["_industry"] = df[industry_col].map(normalize_industry) if industry_col else ""
    fallback_key = df["_merchant_key"] + "|" + df["_address_key"]
    df["_group_key"] = df["_business_id"].where(df["_business_id"] != "", fallback_key)
    df["_attendees"] = df["_memo"].map(attendee_count_from_memo)
    df["_per_person_amount"] = df.apply(
        lambda row: row[amount_col] / row["_attendees"] if pd.notna(row["_attendees"]) and row["_attendees"] else None,
        axis=1,
    )
    df["_attendee_amount"] = df.apply(
        lambda row: row[amount_col] if pd.notna(row["_attendees"]) and row["_attendees"] else 0,
        axis=1,
    )

    df["_drop_memo"] = df["_memo"].map(lambda value: contains_any(value, DROP_MEMO_PATTERNS))

    def is_food_like(row) -> bool:
        text = f"{row[merchant_col]} {row['_memo']}"
        if contains_any(text, NON_FOOD_PATTERNS):
            return False
        if memo_col:
            return contains_any(text, FOOD_HINTS)
        return row["_industry"] in FOOD_SERVICE_INDUSTRIES

    df["_is_food"] = df.apply(is_food_like, axis=1)
    usage_period_mask = df["_actual_usage_date"] >= ACTUAL_USAGE_START_DATE
    eligible_mask = usage_period_mask & (df[amount_col] > 0) & ~df["_drop_memo"] & df["_is_food"]

    token_region_mask = df["_address"].map(
        lambda value: in_region_address(value, region.get("usage_tokens", region["search_tokens"]))
    )
    public_address_keys = {
        clean(row.get("address_key"))
        for row in (public_rows or [])
        if clean(row.get("address_key"))
    }
    public_address_mask = df["_address_key"].isin(public_address_keys)

    admin_tokens = region.get("usage_admin_tokens", [])
    admin_candidate_mask = df["_address"].map(
        lambda value: in_region_address(value, admin_tokens) if admin_tokens else False
    )
    unresolved_addresses = df.loc[
        eligible_mask & admin_candidate_mask & ~token_region_mask & ~public_address_mask,
        "_address",
    ].tolist()
    kakao_address_keys, kakao_api_queries = kakao_region_address_keys(
        unresolved_addresses,
        region,
        public_address_keys,
    )
    kakao_address_mask = df["_address_key"].isin(kakao_address_keys)
    region_mask = token_region_mask | public_address_mask | kakao_address_mask

    scoped = df[region_mask & usage_period_mask].copy()
    region_row_count = len(scoped)
    scoped = scoped[(scoped[amount_col] > 0) & ~scoped["_drop_memo"] & scoped["_is_food"]].copy()
    token_food_rows = int((eligible_mask & token_region_mask).sum())
    public_recovered_rows = int((eligible_mask & ~token_region_mask & public_address_mask).sum())
    kakao_recovered_rows = int(
        (eligible_mask & ~token_region_mask & ~public_address_mask & kakao_address_mask).sum()
    )
    if scoped.empty:
        return [], {
            "total_rows": len(df),
            "region_rows": region_row_count,
            "food_rows": 0,
            "token_food_rows": token_food_rows,
            "public_address_recovered_rows": public_recovered_rows,
            "kakao_address_recovered_rows": kakao_recovered_rows,
            "kakao_scope_api_queries": kakao_api_queries,
            "filter_basis": "업종" if memo_col is None else "적요",
            "date_start": "",
            "date_end": "",
        }
    trend_map = usage_trend_by_group(scoped, amount_col)

    grouped = (
        scoped.groupby("_group_key", dropna=False)
        .agg(
            excel_name=("_merchant_name", lambda values: values.mode().iat[0] if not values.mode().empty else values.iloc[0]),
            excel_name_key=("_merchant_key", "first"),
            excel_business_id=("_business_id", "first"),
            excel_industry=("_industry", lambda values: values.mode().iat[0] if not values.mode().empty else values.iloc[0]),
            usage_count=(amount_col, "size"),
            usage_amount=(amount_col, "sum"),
            avg_amount=(amount_col, "mean"),
            attendee_amount=("_attendee_amount", "sum"),
            attendee_count=("_attendees", "sum"),
            attendee_sample_count=("_attendees", "count"),
            per_person_amount=("_per_person_amount", "mean"),
            recent_date=("_actual_usage_date", "max"),
            excel_address=("_address", lambda values: values.mode().iat[0] if not values.mode().empty else values.iloc[0]),
            excel_address_key=("_address_key", "first"),
            memo_sample=("_memo", lambda values: " / ".join([value for value in values.astype(str).head(4) if value])[:180]),
        )
        .reset_index()
    )
    grouped = score_usage(grouped)

    results = []
    for _, row in grouped.iterrows():
        results.append(
            {
                "excel_id": slug(row["excel_name"], row["excel_address_key"]),
                "excel_name": str(row["excel_name"]),
                "excel_name_key": str(row["excel_name_key"]),
                "excel_business_id": str(row["excel_business_id"]),
                "excel_industry": str(row["excel_industry"]),
                "excel_address": str(row["excel_address"]),
                "excel_address_key": str(row["excel_address_key"]),
                "usage_count": int(row["usage_count"]),
                "usage_amount": int(row["usage_amount"]),
                "avg_amount": int(round(row["avg_amount"])),
                "attendee_amount": int(row["attendee_amount"]) if pd.notna(row["attendee_amount"]) else 0,
                "attendee_count": int(row["attendee_count"]) if pd.notna(row["attendee_count"]) else 0,
                "attendee_sample_count": int(row["attendee_sample_count"]) if pd.notna(row["attendee_sample_count"]) else 0,
                "per_person_amount": int(round(row["attendee_amount"] / row["attendee_count"]))
                if pd.notna(row["attendee_count"]) and row["attendee_count"]
                else 0,
                "recent_date": str(pd.to_datetime(row["recent_date"]).date()) if pd.notna(row["recent_date"]) else "",
                "score": int(row["score"]),
                "memo_sample": str(row["memo_sample"]),
                "usage_trend": trend_map.get(str(row["_group_key"]), "[]"),
            }
        )
    profile = {
        "total_rows": len(df),
        "region_rows": region_row_count,
        "food_rows": len(scoped),
        "token_food_rows": token_food_rows,
        "public_address_recovered_rows": public_recovered_rows,
        "kakao_address_recovered_rows": kakao_recovered_rows,
        "kakao_scope_api_queries": kakao_api_queries,
        "filter_basis": "업종" if memo_col is None else "적요",
        "date_start": str(pd.to_datetime(scoped["_actual_usage_date"], errors="coerce").min().date()),
        "date_end": str(pd.to_datetime(scoped["_actual_usage_date"], errors="coerce").max().date()),
    }
    return sorted(results, key=lambda row: (row["score"], row["usage_count"], row["usage_amount"]), reverse=True), profile


def slug(name: str, addr_key: str) -> str:
    digest = hashlib.md5(f"{name}|{addr_key}".encode("utf-8")).hexdigest()[:8]
    return f"excel-{normalize_text(name)[:20]}-{digest}"


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def best_match(excel_row: dict[str, str], public_rows: list[dict[str, str]]) -> tuple[dict[str, str] | None, int, str]:
    exact_name_candidates = [
        public_row for public_row in public_rows if excel_row["excel_name_key"] == public_row["name_key"]
    ]
    if len(exact_name_candidates) == 1:
        public_row = exact_name_candidates[0]
        score = 70 if excel_row["excel_address_key"] != public_row["address_key"] else 105
        reason = "name_exact_unique" if score == 70 else "address_exact+name_exact"
        return public_row, score, reason

    best: tuple[dict[str, str] | None, int, str] = (None, 0, "no_candidate")
    for public_row in public_rows:
        score = 0
        reasons = []
        has_name_evidence = False
        if public_row["is_active"] == "Y":
            score += 5
        if excel_row["excel_address_key"] and excel_row["excel_address_key"] == public_row["address_key"]:
            score += 55
            reasons.append("address_exact")
        if excel_row["excel_name_key"] == public_row["name_key"]:
            score += 45
            reasons.append("name_exact")
            has_name_evidence = True
        elif excel_row["excel_name_key"] and public_row["name_key"] and (
            excel_row["excel_name_key"] in public_row["name_key"] or public_row["name_key"] in excel_row["excel_name_key"]
        ):
            score += 32
            reasons.append("name_contains")
            has_name_evidence = True
        else:
            name_sim = similarity(excel_row["excel_name_key"], public_row["name_key"])
            if name_sim >= 0.72:
                score += int(name_sim * 28)
                reasons.append(f"name_similarity_{name_sim:.2f}")
                has_name_evidence = True
        if not has_name_evidence:
            continue
        if score > best[1]:
            best = (public_row, score, "+".join(reasons))
    if best[1] < 60:
        return None, best[1], best[2]
    return best


def aggregate_master_rows(matched_pairs: list[dict], public_unmatched: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for pair in matched_pairs:
        key = pair["public_id"] or f"{pair['name']}|{pair['address']}"
        if key not in grouped:
            grouped[key] = {
                **{k: v for k, v in pair.items() if not k.startswith("excel_")},
                "master_status": "matched",
                "excel_id": pair["excel_id"],
                "excel_name": pair["excel_name"],
                "excel_address": pair["excel_address"],
                "excel_business_id": pair["excel_business_id"],
                "excel_industry": pair["excel_industry"],
                "usage_count": pair["usage_count"],
                "usage_amount": pair["usage_amount"],
                "avg_amount": pair["avg_amount"],
                "attendee_amount": pair["attendee_amount"],
                "attendee_count": pair["attendee_count"],
                "attendee_sample_count": pair["attendee_sample_count"],
                "per_person_amount": pair["per_person_amount"],
                "recent_date": pair["recent_date"],
                "score": pair["score"],
                "memo_sample": pair["memo_sample"],
                "usage_trend": pair["usage_trend"],
                "match_score": pair["match_score"],
                "match_reason": pair["match_reason"],
            }
            continue
        current = grouped[key]
        current["excel_id"] = join_unique(current["excel_id"], pair["excel_id"])
        current["excel_name"] = join_unique(current["excel_name"], pair["excel_name"])
        current["excel_address"] = join_unique(current["excel_address"], pair["excel_address"])
        current["excel_business_id"] = join_unique(current["excel_business_id"], pair["excel_business_id"])
        current["excel_industry"] = join_unique(current["excel_industry"], pair["excel_industry"])
        current["usage_count"] += pair["usage_count"]
        current["usage_amount"] += pair["usage_amount"]
        current["avg_amount"] = int(round(current["usage_amount"] / max(current["usage_count"], 1)))
        current["attendee_amount"] += pair["attendee_amount"]
        current["attendee_count"] += pair["attendee_count"]
        current["attendee_sample_count"] += pair["attendee_sample_count"]
        current["per_person_amount"] = int(round(current["attendee_amount"] / max(current["attendee_count"], 1))) if current["attendee_count"] else 0
        current["recent_date"] = max(current["recent_date"], pair["recent_date"])
        current["score"] = max(current["score"], pair["score"])
        current["memo_sample"] = join_unique(current["memo_sample"], pair["memo_sample"])
        current["usage_trend"] = merge_usage_trends(current["usage_trend"], pair["usage_trend"])
        current["match_score"] = max(current["match_score"], pair["match_score"])
        current["match_reason"] = join_unique(current["match_reason"], pair["match_reason"])

    matched_rows = list(grouped.values())
    if matched_rows:
        score_frame = pd.DataFrame(
            {
                "category": [row.get("category") or "기타" for row in matched_rows],
                "usage_count": [row["usage_count"] for row in matched_rows],
                "usage_amount": [row["usage_amount"] for row in matched_rows],
            }
        )
        scores = category_normalized_usage_scores(
            score_frame["category"], score_frame["usage_count"], score_frame["usage_amount"]
        )
        for row, score in zip(matched_rows, scores.tolist()):
            row["score"] = int(score)

    master = matched_rows + [
        {
            **row,
            "master_status": "public_only",
            "excel_id": "",
            "excel_name": "",
            "excel_address": "",
            "excel_business_id": "",
            "excel_industry": "",
            "usage_count": 0,
            "usage_amount": 0,
            "avg_amount": 0,
            "attendee_amount": 0,
            "attendee_count": 0,
            "attendee_sample_count": 0,
            "per_person_amount": 0,
            "recent_date": "",
            "score": 50,
            "memo_sample": "",
            "usage_trend": "[]",
            "match_score": 0,
            "match_reason": "public_only",
        }
        for row in public_unmatched
    ]
    master.sort(key=lambda row: (row.get("score", 0), row.get("usage_count", 0), row["name"]), reverse=True)
    return master


def join_unique(left: str, right: str) -> str:
    values = []
    for item in [left, right]:
        for value in str(item or "").split(" | "):
            value = value.strip()
            if value and value not in values:
                values.append(value)
    return " | ".join(values)


def merge_usage_trends(left: str, right: str) -> str:
    try:
        left_items = json.loads(left or "[]")
        right_items = json.loads(right or "[]")
    except json.JSONDecodeError:
        return left or right or "[]"

    counts: dict[str, int] = {}
    for item in [*left_items, *right_items]:
        month = str(item.get("month", ""))
        if not month:
            continue
        counts[month] = counts.get(month, 0) + int(item.get("count") or 0)
    return json.dumps(
        [{"month": month, "count": counts[month]} for month in sorted(counts)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def merge_rows(public_rows: list[dict[str, str]], excel_rows: list[dict[str, str]]) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    active_public = [row for row in public_rows if row["is_active"] == "Y"]
    matched = []
    excel_unmatched = []
    matched_public_ids = set()

    for excel_row in excel_rows:
        public_row, match_score, match_reason = best_match(excel_row, active_public)
        if public_row is None:
            excel_unmatched.append({**excel_row, "match_score": match_score, "match_reason": match_reason})
            continue
        matched_public_ids.add(public_row["public_id"])
        matched.append({**public_row, **excel_row, "match_score": match_score, "match_reason": match_reason, "master_status": "matched"})

    public_unmatched = [
        {**row, "master_status": "public_only"}
        for row in active_public
        if row["public_id"] not in matched_public_ids
    ]
    master = aggregate_master_rows(matched, public_unmatched)
    return master, matched, public_unmatched, excel_unmatched


def write_csv(path: Path, rows: list[dict]) -> None:
    preferred = [
        "master_status",
        "public_id",
        "name",
        "category",
        "license_type",
        "status_note",
        "permit_date",
        "closed_date",
        "address",
        "phone",
        "excel_id",
        "excel_name",
        "excel_address",
        "excel_business_id",
        "excel_industry",
        "usage_count",
        "usage_amount",
        "avg_amount",
        "attendee_amount",
        "attendee_count",
        "attendee_sample_count",
        "per_person_amount",
        "recent_date",
        "score",
        "match_score",
        "match_reason",
        "memo_sample",
        "usage_trend",
        "x",
        "y",
        "last_modified",
    ]
    fields = preferred + sorted({key for row in rows for key in row.keys()} - set(preferred))
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    region_id, region = get_region(sys.argv[1] if len(sys.argv) > 1 else None)
    excel_path = find_excel_file(sys.argv[2] if len(sys.argv) > 2 else None)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    public_rows = read_public_rows(region)
    excel_rows, usage_profile = read_excel_usage(region, excel_path, public_rows)
    master, matched, public_unmatched, excel_unmatched = merge_rows(public_rows, excel_rows)

    prefix = OUT_DIR / f"{region_id}_restaurant"
    write_csv(prefix.with_name(f"{region_id}_restaurant_master.csv"), master)
    write_csv(prefix.with_name(f"{region_id}_restaurant_matched.csv"), matched)
    write_csv(prefix.with_name(f"{region_id}_restaurant_public_only.csv"), public_unmatched)
    write_csv(prefix.with_name(f"{region_id}_restaurant_excel_unmatched.csv"), excel_unmatched)

    summary = {
        "region_id": region_id,
        "region_name": region["name"],
        "excel_file": "local-private-input",
        "excel_total_rows": usage_profile["total_rows"],
        "excel_region_rows": usage_profile["region_rows"],
        "excel_food_rows": usage_profile["food_rows"],
        "excel_token_food_rows": usage_profile["token_food_rows"],
        "excel_public_address_recovered_rows": usage_profile["public_address_recovered_rows"],
        "excel_kakao_address_recovered_rows": usage_profile["kakao_address_recovered_rows"],
        "excel_kakao_scope_api_queries": usage_profile["kakao_scope_api_queries"],
        "excel_filter_basis": usage_profile["filter_basis"],
        "excel_date_start": usage_profile["date_start"],
        "excel_date_end": usage_profile["date_end"],
        "public_total": len(public_rows),
        "public_active": len([row for row in public_rows if row["is_active"] == "Y"]),
        "excel_usage_groups": len(excel_rows),
        "matched": len(matched),
        "matched_public": len({row["public_id"] for row in matched}),
        "master_rows": len(master),
        "public_only_active": len(public_unmatched),
        "excel_unmatched": len(excel_unmatched),
        "match_rate_by_excel": round(len(matched) / len(excel_rows), 4) if excel_rows else 0,
        "usage_score_formula": "이용횟수와 총사용금액을 정규화해 동일 비중 합산, 최고 100점, 데이터 없음 50점",
        "outputs": [
            f"data/processed/{region_id}_restaurant_master.csv",
            f"data/processed/{region_id}_restaurant_matched.csv",
            f"data/processed/{region_id}_restaurant_public_only.csv",
            f"data/processed/{region_id}_restaurant_excel_unmatched.csv",
        ],
    }
    (OUT_DIR / f"{region_id}_restaurant_match_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nMATCHED_SAMPLE")
    for row in matched[:15]:
        print(row["name"], row["excel_name"], row["usage_count"], row["usage_amount"], row["match_score"], row["match_reason"])
    print("\nEXCEL_UNMATCHED_SAMPLE")
    for row in excel_unmatched[:15]:
        print(row["excel_name"], row["excel_address"], row["usage_count"], row["usage_amount"], row["match_score"], row["match_reason"])


if __name__ == "__main__":
    main()
