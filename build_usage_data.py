from pathlib import Path
import hashlib
import json
import re
import sys

import pandas as pd

from address_keys import address_key as precise_address_key
from region_config import get_region
from usage_dates import ACTUAL_USAGE_START_DATE, ACTUAL_USAGE_START_MONTH, actual_usage_dates


ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "input"
PROCESSED_DIR = ROOT / "data" / "processed"
SOURCE_FILE_HINT = "개인정보제외파일"
ACTIVE_REGION_ID, ACTIVE_REGION = get_region(sys.argv[1] if len(sys.argv) > 1 else None)
ACTIVE_REGION_TOKENS = ACTIVE_REGION.get("usage_tokens", ACTIVE_REGION["search_tokens"])


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

FOOD_HINTS = [
    "회의비",
]

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

DROP_MEMO_PATTERNS = [
    "카드취소",
    "전액카드취소",
    "취소예정",
    "오사용",
    "환불",
    "반품",
]

ALIASES = {
    "호훈테이블hohoontable": "호훈테이블",
    "호훈테이블": "호훈테이블",
    "하삼동커피울산구영점": "하삼동커피 구영범서점",
    "하삼동구영범서점": "하삼동커피 구영범서점",
    "정성순대울산구영리점": "정성순대 울산구영리점",
    "정성순대울산구영점": "정성순대 울산구영리점",
    "써브웨이울산구영점": "써브웨이 울산구영점",
    "서브웨이울산구영점": "써브웨이 울산구영점",
}

CATEGORY_OVERRIDES = {
    "정나루": "칼국수",
    "갓포hero": "일식",
    "스시미즈기와": "일식",
    "김호권의청년어부": "일식",
    "담락참치일잔": "일식",
    "하오츠": "중식",
    "라이라이": "중식",
    "이비가짬뽕": "중식",
    "차이나짬뽕": "중식",
}


def find_source_file(explicit_path: str | None) -> Path:
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


def normalize_text(value) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\(주\)|㈜|주식회사", "", text)
    text = re.sub(r"[^0-9a-z가-힣]", "", text)
    return text


def normalize_merchant(value) -> str:
    key = normalize_text(value)
    key = re.sub(r"울산|구영리점|구영점|울산구영리점|범서점|직영점|본점", "", key)
    return ALIASES.get(key, key)


def normalize_address(value) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("울산광역시", "울산")
    text = text.replace(".", "")
    return text


def normalize_business_id(value) -> str:
    return re.sub(r"[^0-9]", "", str(value or ""))


def normalize_industry(value) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def address_key(value) -> str:
    return precise_address_key(value, ACTIVE_REGION["address_key_pattern"])


def is_region_address(value) -> bool:
    text = normalize_address(value)
    return any(token in text for token in ACTIVE_REGION_TOKENS)


def contains_any(text: str, patterns: list[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def category(name: str) -> str:
    normalized = normalize_merchant(name)
    if normalized in CATEGORY_OVERRIDES:
        return CATEGORY_OVERRIDES[normalized]
    if contains_any(name, ["칼국수", "닭칼국수"]):
        return "칼국수"
    if contains_any(name, ["스시", "초밥", "갓포", "이자카야", "참치", "청년어부"]):
        return "일식"
    if contains_any(name, ["짬뽕", "짜장", "중국", "중화", "반점", "라이라이", "하오츠", "탕수육"]):
        return "중식"
    if contains_any(name, ["커피", "카페", "투썸", "파스쿠찌", "텐퍼센트", "파리바게뜨", "배스킨", "랑콩", "로우냅", "브래댄코"]):
        return "카페"
    if contains_any(name, ["횟집", "회센터", "바다회", "생아구", "어부의아들", "어탕", "장어", "복국", "전복", "고등어", "해물"]):
        return "횟집"
    if contains_any(name, ["한우", "갈비", "화로", "고기", "돼지", "대패", "돈", "목장", "양꼬치", "족발", "보쌈", "비프"]):
        return "고기"
    if contains_any(name, ["국밥", "순대", "삼계탕", "닭칼국수", "칼국수", "짬뽕", "반점", "중국", "탕", "라이라이"]):
        return "국밥/면"
    if contains_any(name, ["서브웨이", "써브웨이", "버거", "피자", "치킨", "떡볶이", "김밥", "핫도그", "유부", "도시락"]):
        return "간편식"
    return "한식"


def slug(name: str, addr_key: str) -> str:
    base = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", name).strip("-").lower()
    digest = hashlib.md5(f"{name}|{addr_key}".encode("utf-8")).hexdigest()[:6]
    return f"raw-{base[:24]}-{digest}"


def pseudo_coords(index: int, address: str) -> tuple[float, float]:
    # Until a geocoder is wired in, spread markers deterministically inside the active region.
    digest = hashlib.md5(f"{address}|{index}".encode("utf-8")).hexdigest()
    h = int(digest[:8], 16)
    center_lat, center_lng = ACTIVE_REGION["marker_center"]
    lat = center_lat + ((h % 1600) - 800) / 100000
    lng = center_lng + (((h // 1600) % 1600) - 800) / 100000
    return round(lat, 7), round(lng, 7)


def score_table(grouped: pd.DataFrame) -> pd.DataFrame:
    scores = pd.Series(50, index=grouped.index, dtype=float)
    for category_name, category_rows in grouped.groupby("category"):
        valid = (category_rows["usageCount"] > 0) & (category_rows["usageAmount"] > 0)
        if not valid.any():
            continue
        valid_rows = category_rows.loc[valid]
        count_norm = valid_rows["usageCount"] / max(valid_rows["usageCount"].max(), 1)
        amount_norm = valid_rows["usageAmount"] / max(valid_rows["usageAmount"].max(), 1)
        combined = count_norm * 0.5 + amount_norm * 0.5
        highest = max(float(combined.max()), 1e-9)
        scores.loc[valid_rows.index] = 50 + combined / highest * 50
        scores.loc[valid_rows.index] = scores.loc[valid_rows.index].round().clip(51, 100)
    grouped["score"] = scores.astype(int)
    return grouped


def usage_trend_by_group(scoped: pd.DataFrame, amount_col: str) -> dict[str, list[dict]]:
    dated = scoped.copy()
    dated["_date"] = pd.to_datetime(dated["_actual_usage_date"], errors="coerce")
    dated = dated.dropna(subset=["_date"])
    if dated.empty:
        return {}

    first_month = pd.Period(ACTUAL_USAGE_START_MONTH, freq="M")
    months = pd.period_range(first_month, dated["_date"].max().to_period("M"), freq="M")
    dated["_month"] = dated["_date"].dt.to_period("M").astype(str)
    monthly = dated.groupby(["_groupKey", "_month"])[amount_col].size()
    return {
        group_key: [
            {"month": str(month), "count": int(monthly.get((group_key, str(month)), 0))}
            for month in months
        ]
        for group_key in dated["_groupKey"].dropna().unique()
    }


def main() -> None:
    source = find_source_file(sys.argv[2] if len(sys.argv) > 2 else None)
    df = pd.read_excel(source, sheet_name=0)
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
    df["_merchantKey"] = df[merchant_col].map(normalize_merchant)
    df["_addressKey"] = df["_address"].map(address_key)
    df["_memo"] = df[memo_col] if memo_col else ""
    df["_industry"] = df[industry_col].map(normalize_industry) if industry_col else ""
    df["_businessId"] = df[business_col].map(normalize_business_id) if business_col else ""
    fallback_key = df["_merchantKey"] + "|" + df["_addressKey"]
    df["_groupKey"] = df["_businessId"].where(df["_businessId"] != "", fallback_key)

    scoped = df[
        df["_address"].map(is_region_address)
        & (df["_actual_usage_date"] >= ACTUAL_USAGE_START_DATE)
    ].copy()
    before_filter_rows = len(scoped)

    scoped["_isDropMemo"] = scoped["_memo"].map(lambda value: contains_any(value, DROP_MEMO_PATTERNS))
    scoped = scoped[(scoped[amount_col] > 0) & ~scoped["_isDropMemo"]].copy()
    after_cancel_filter_rows = len(scoped)

    def is_food_like(row) -> bool:
        name = str(row[merchant_col])
        text = f"{name} {row['_memo']}"
        if contains_any(text, NON_FOOD_PATTERNS):
            return False
        if memo_col:
            return contains_any(text, FOOD_HINTS)
        return row["_industry"] in FOOD_SERVICE_INDUSTRIES

    counts = scoped.groupby("_groupKey")[amount_col].transform("size")
    scoped["_merchantCount"] = counts
    scoped = scoped[scoped.apply(is_food_like, axis=1)].copy()
    trend_map = usage_trend_by_group(scoped, amount_col)

    grouped = (
        scoped.groupby("_groupKey", dropna=False)
        .agg(
            name=(merchant_col, lambda values: values.mode().iat[0] if not values.mode().empty else values.iloc[0]),
            canonicalName=("_merchantKey", "first"),
            businessId=("_businessId", "first"),
            industry=("_industry", lambda values: values.mode().iat[0] if not values.mode().empty else values.iloc[0]),
            usageCount=(amount_col, "size"),
            usageAmount=(amount_col, "sum"),
            avgAmount=(amount_col, "mean"),
            recentDate=("_actual_usage_date", "max"),
            address=("_address", lambda values: values.mode().iat[0] if not values.mode().empty else values.iloc[0]),
            memoSample=("_memo", lambda values: " / ".join([value for value in values.astype(str).head(4) if value])[:180]),
            addressKey=("_addressKey", "first"),
        )
        .reset_index()
    )

    grouped["category"] = grouped["name"].map(category)
    grouped = score_table(grouped)
    grouped = grouped.sort_values(["score", "usageCount", "usageAmount"], ascending=False)

    restaurants = []
    for index, row in grouped.iterrows():
        lat, lng = pseudo_coords(index, row["address"])
        restaurants.append(
            {
                "id": slug(row["name"], row["addressKey"]),
                "name": row["name"],
                "canonicalName": row["canonicalName"],
                "businessId": row["businessId"],
                "category": row["category"],
                "address": row["address"],
                "addressKey": row["addressKey"],
                "lat": lat,
                "lng": lng,
                "menu": f"{row['industry']} 이용 데이터" if row["industry"] else "엑셀 이용 데이터",
                "price": int(max(40, min(95, round(100 - (row["avgAmount"] / max(grouped["avgAmount"].max(), 1)) * 40)))),
                "score": int(row["score"]),
                "mentions": int(row["usageCount"]),
                "mood": "실사용 데이터 기반",
                "hours": "영업시간 확인 필요",
                "source": "local-private-input",
                "sourceUrl": "",
                "usageCount": int(row["usageCount"]),
                "usageAmount": int(row["usageAmount"]),
                "avgAmount": int(round(row["avgAmount"])),
                "recentDate": str(pd.to_datetime(row["recentDate"]).date()) if pd.notna(row["recentDate"]) else "",
                "memoSample": row["memoSample"],
                "usageTrend": trend_map.get(row["_groupKey"], []),
                "matchBasis": "사업자등록번호 우선 + 업체명/주소키 보완",
            }
        )

    summary = {
        "sourceType": "local-private-input",
        "regionId": ACTIVE_REGION_ID,
        "regionName": ACTIVE_REGION["name"],
        "scope": f"주소에 {', '.join(ACTIVE_REGION_TOKENS)} 포함",
        "expenseType": "업종 기준 음식점·카페 사용" if memo_col is None else "적요에 회의비 포함",
        "dateStart": str(pd.to_datetime(scoped["_actual_usage_date"]).min().date()) if not scoped.empty else "",
        "dateEnd": str(pd.to_datetime(scoped["_actual_usage_date"]).max().date()) if not scoped.empty else "",
        "totalRows": int(len(df)),
        "scopeRows": int(before_filter_rows),
        "afterCancelFilterRows": int(after_cancel_filter_rows),
        "foodRows": int(len(scoped)),
        "scopeAmount": int(scoped[amount_col].sum()),
        "restaurantCount": len(restaurants),
        "scoreFormula": "카테고리별 이용횟수와 총사용금액을 50%씩 정규화, 카테고리 1위 100점, 데이터 없음 50점",
        "matchBasis": "사업자등록번호 우선 + 업체명/주소키 보완 그룹핑",
    }

    output = "window.excelUsageSummary = "
    output += json.dumps(summary, ensure_ascii=False, indent=2)
    output += ";\n\nwindow.excelRestaurants = "
    output += json.dumps(restaurants, ensure_ascii=False, indent=2)
    output += ";\n"
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    (PROCESSED_DIR / "usage-data.js").write_text(output, encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for item in restaurants[:15]:
        print(item["name"], item["address"], item["usageCount"], item["usageAmount"], item["score"])


if __name__ == "__main__":
    main()
