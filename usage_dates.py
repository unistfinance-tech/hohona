from __future__ import annotations

import pandas as pd


# 엑셀 결제월은 실제 이용월보다 한 달 뒤에 기록된다.
EXCEL_USAGE_MONTH_LAG = 1
ACTUAL_USAGE_START_MONTH = "2025-01"
ACTUAL_USAGE_START_DATE = pd.Timestamp(f"{ACTUAL_USAGE_START_MONTH}-01")


def actual_usage_dates(values: pd.Series) -> pd.Series:
    """Convert Excel payment dates into the corresponding actual usage dates."""
    return pd.to_datetime(values, errors="coerce") - pd.DateOffset(months=EXCEL_USAGE_MONTH_LAG)
