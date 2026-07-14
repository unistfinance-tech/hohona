from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from region_config import REGIONS


ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "input"
PROCESSED_DIR = ROOT / "data" / "processed"
SUMMARY_PATH = PROCESSED_DIR / "full_update_summary.json"
KAKAO_KEY_ENV = "KAKAO_REST_API_KEY"
FOODSAFETY_KEY_ENV = "FOODSAFETY_API_KEY"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="엑셀 한 파일로 지역별 음식점 데이터와 화면 카탈로그를 전체 갱신합니다."
    )
    parser.add_argument(
        "excel",
        nargs="?",
        help="입력 엑셀 경로. 생략하면 input 폴더의 최신 파일을 사용합니다.",
    )
    parser.add_argument(
        "--regions",
        nargs="+",
        choices=tuple(REGIONS),
        default=list(REGIONS),
        metavar="REGION",
        help="갱신할 지역 ID. 기본값은 전체 지역입니다.",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="카카오 장소 검색 캐시를 재사용합니다. 기본값은 최신 API 재조회입니다.",
    )
    parser.add_argument(
        "--skip-bento",
        action="store_true",
        help="도시락 목록 재생성을 건너뜁니다.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="파일과 환경만 검증하고 실행할 명령을 표시합니다.",
    )
    return parser.parse_args()


def newest_input_workbook() -> Path:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    candidates = [
        path
        for pattern in ("*.xlsx",)
        for path in INPUT_DIR.glob(pattern)
        if not path.name.startswith("~$")
    ]
    if not candidates:
        raise SystemExit(
            "입력 엑셀이 없습니다. input 폴더에 .xlsx 파일을 넣거나 "
            "명령 뒤에 엑셀 경로를 지정하세요."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def resolve_excel(explicit_path: str | None) -> Path:
    path = Path(explicit_path).expanduser() if explicit_path else newest_input_workbook()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise SystemExit(f"엑셀 파일을 찾을 수 없습니다: {path}")
    if path.suffix.lower() != ".xlsx":
        raise SystemExit(f"지원하지 않는 입력 형식입니다: {path.suffix}")
    return path


def required_public_files(region_ids: list[str]) -> list[Path]:
    paths = {
        ROOT / relative_path
        for region_id in region_ids
        for _, relative_path in REGIONS[region_id]["localdata_files"]
    }
    return sorted(paths)


def command_steps(excel_path: Path, region_ids: list[str], use_cache: bool, skip_bento: bool):
    for region_id in region_ids:
        yield region_id, "공공 인허가 목록", ["build_public_restaurant_list.py", region_id]
        yield region_id, "영업상태·변경정보", ["build_license_status.py", region_id]
        yield region_id, "엑셀 정합성·이용 집계", ["build_restaurant_master.py", region_id, str(excel_path)]
        yield region_id, "공공 보조정보·좌표", ["build_public_restaurants_js.py", region_id]
        catalog_command = ["build_restaurant_catalog.py", region_id]
        if not use_cache:
            catalog_command.append("--refresh")
        yield region_id, "카카오 기준 최종 카탈로그", catalog_command

    if "guyeong" in region_ids:
        yield "guyeong", "검증된 외부 상세정보", ["build_external_details.py", "guyeong"]
    if not skip_bento:
        yield "bento", "도시락 카탈로그", ["build_bento_restaurants.py"]
    yield "all", "5개 지역 통합 랭킹", ["build_restaurant_ranking.py"]


def validate_environment(
    excel_path: Path,
    region_ids: list[str],
    dry_run: bool,
    skip_bento: bool,
) -> None:
    errors: list[str] = []
    missing_packages = [
        package
        for package in ("pandas", "openpyxl")
        if importlib.util.find_spec(package) is None
    ]
    if missing_packages:
        errors.append(
            "Python 패키지가 없습니다: "
            + ", ".join(missing_packages)
            + f". 설치 명령: {Path(sys.executable).name} -m pip install -r requirements.txt"
        )
    if not os.environ.get(KAKAO_KEY_ENV, "").strip():
        errors.append(f"{KAKAO_KEY_ENV} 환경변수가 설정되지 않았습니다.")

    public_files = required_public_files(region_ids)
    if not skip_bento:
        public_files.extend(
            [
                ROOT / "data" / "general_restaurants_national.csv",
                ROOT / "data" / "rest_cafes_national.csv",
            ]
        )
    for path in dict.fromkeys(public_files):
        if not path.is_file():
            errors.append(f"공공데이터 원본이 없습니다: {path.relative_to(ROOT)}")

    if errors:
        raise SystemExit("\n".join(errors))

    print(f"입력 엑셀: {excel_path.name}")
    print(f"대상 지역: {', '.join(region_ids)}")
    print(f"카카오 API: {'검증만 수행' if dry_run else '사용 가능'}")
    if os.environ.get(FOODSAFETY_KEY_ENV, "").strip():
        print("식약처 변경정보 API: 사용 가능")
    else:
        print("식약처 변경정보 API: 키 없음, 보유한 인허가 상태 자료만 반영")


def run_step(index: int, total: int, region_id: str, label: str, command: list[str], dry_run: bool) -> float:
    display = " ".join([Path(sys.executable).name, *command])
    print(f"\n[{index}/{total}] {region_id} | {label}")
    print(f"  {display}")
    if dry_run:
        return 0.0

    started = time.perf_counter()
    subprocess.run([sys.executable, *command], cwd=ROOT, check=True)
    elapsed = time.perf_counter() - started
    print(f"  완료 ({elapsed:.1f}초)")
    return elapsed


def update_asset_version() -> str:
    version = datetime.now().strftime("%Y%m%d-%H%M%S-data")
    index_path = ROOT / "index.html"
    app_path = ROOT / "app.js"

    index_text = index_path.read_text(encoding="utf-8")
    index_text, asset_replacements = re.subn(
        r"(\?v=)[^\"'`<\s]+",
        rf"\g<1>{version}",
        index_text,
    )
    if asset_replacements == 0:
        raise RuntimeError("index.html의 자산 버전 선언을 찾지 못했습니다.")
    today = datetime.now().strftime("%Y.%m.%d.")
    index_text = re.sub(
        r"(<span>업데이트:\s*)\d{4}\.\d{2}\.\d{2}\.(</span>)",
        rf"\g<1>{today}\g<2>",
        index_text,
    )
    app_text = app_path.read_text(encoding="utf-8")
    app_text, replacements = re.subn(
        r'const APP_VERSION = "[^"]+";',
        f'const APP_VERSION = "{version}";',
        app_text,
        count=1,
    )
    if replacements != 1:
        raise RuntimeError("app.js의 APP_VERSION 선언을 찾지 못했습니다.")

    index_path.write_text(index_text, encoding="utf-8")
    app_path.write_text(app_text, encoding="utf-8")
    return version


def validate_outputs(region_ids: list[str], skip_bento: bool) -> list[str]:
    expected = [
        ROOT / ("restaurant-catalog.js" if region_id == "guyeong" else f"restaurant-catalog-{region_id}.js")
        for region_id in region_ids
    ]
    expected.append(ROOT / "restaurant-ranking.js")
    if not skip_bento:
        expected.append(ROOT / "bento-restaurants.js")

    missing = [path.name for path in expected if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise RuntimeError(f"생성 결과가 없거나 비어 있습니다: {', '.join(missing)}")
    return [path.name for path in expected]


def main() -> None:
    args = parse_args()
    excel_path = resolve_excel(args.excel)
    region_ids = list(dict.fromkeys(args.regions))
    validate_environment(excel_path, region_ids, args.dry_run, args.skip_bento)

    steps = list(command_steps(excel_path, region_ids, args.use_cache, args.skip_bento))
    if args.dry_run:
        print("\n실행 예정 명령")

    started_at = datetime.now()
    timings = []
    for index, (region_id, label, command) in enumerate(steps, start=1):
        elapsed = run_step(index, len(steps), region_id, label, command, args.dry_run)
        timings.append({"region": region_id, "step": label, "seconds": round(elapsed, 2)})

    if args.dry_run:
        print("\n검증 완료: 실제 파일은 변경하지 않았습니다.")
        return

    outputs = validate_outputs(region_ids, args.skip_bento)
    version = update_asset_version()
    finished_at = datetime.now()
    summary = {
        "inputType": "local-private-input",
        "regions": region_ids,
        "kakaoCacheReused": args.use_cache,
        "foodSafetyApiUsed": bool(os.environ.get(FOODSAFETY_KEY_ENV, "").strip()),
        "startedAt": started_at.isoformat(timespec="seconds"),
        "finishedAt": finished_at.isoformat(timespec="seconds"),
        "assetVersion": version,
        "outputs": outputs,
        "steps": timings,
    }
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n전체 업데이트 완료: {version}")
    print(f"결과 요약: {SUMMARY_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
