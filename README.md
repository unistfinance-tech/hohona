# 지역 맛집 비교 MVP

구영리·천상리·굴화리·무거동·언양읍·삼남읍 일대 식당을 지도와 목록에서 비교하는 정적 모바일 웹앱입니다.

## 실행

현재 작업 세션에서는 아래 주소로 확인할 수 있습니다.

```text
http://127.0.0.1:5173/
```

정적 파일만 사용하는 구조라 `index.html` 파일을 브라우저에서 직접 열어도 됩니다. 지도 타일이나 아이콘 CDN이 차단되는 환경에서는 로컬 서버 방식이 더 안정적입니다.

## 포함 기능

- 지역별 지도와 음식점 위치 표시
- 식당 검색
- 음식 종류 필터
- 방문순, 거리순, 추세순, 신규진입 정렬
- 최대 4개 식당 비교
- 로컬 비공개 Excel을 분석해 만든 점수·순위·상대 추세 지표 기본 탑재

## 데이터 처리 순서

### 엑셀 한 파일로 전체 업데이트

1. 최신 `.xlsx` 파일을 [`input`](./input) 폴더에 넣습니다.
2. `update_data.cmd`를 실행합니다.

파일을 폴더에 넣지 않고 `update_data.cmd` 위로 끌어 놓아도 됩니다. 입력 파일은
Git에서 제외되며, 파일이 여러 개면 수정 시각이 가장 최근인 파일을 자동 선택합니다.
이 한 번의 실행으로 5개 지역의 공공 인허가 대조, 식약처 변경정보 대조, 엑셀 이용
집계, 카카오 장소 재조회, 지역 카탈로그, 도시락 목록, 통합 랭킹을 순서대로 다시
생성합니다. 성공한 경우에만 화면 자산 버전과 메인 하단의 업데이트 날짜가 바뀝니다.

### 원본 Excel 보호

- Excel 원본은 로컬 `input` 폴더에서만 데이터 생성 스크립트가 읽습니다.
- Excel 확장자는 위치와 관계없이 Git 추적 대상에서 제외됩니다.
- GitHub Actions는 데이터 생성 스크립트를 실행하지 않고, 명시된 화면 파일만 `_site`에 복사해 Pages에 배포합니다.
- 배포 단계에서 Excel 파일 또는 Excel 파일명 참조가 발견되면 배포가 중단됩니다.

### 이용자료 역추적 방지

- 정확한 누적 이용횟수, 총사용금액, 월별 건수는 Git에서 제외된 `data/processed/*_private.json`에만 저장합니다.
- 브라우저에는 카테고리별 이용점수, 지역 내 정렬 순위, 신규진입 순위와 월별 상대 수준(0~4)만 전달합니다.
- 공개 카탈로그나 랭킹 파일에서 정확한 이용 필드가 발견되면 GitHub Pages 빌드가 중단됩니다.
- 공개 Git 이력은 민감값이 들어가기 전의 단일 정리 커밋부터 유지합니다.

### 배포 용량 관리

- 브라우저용 음식점 파일에는 비가역 파생 필드만 저장하고 계산용 원본은 `data/processed`에 유지합니다.
- GitHub Pages 생성 단계에서 전체 공개 파일은 2MB, 개별 파일은 512KB를 넘지 않는지 자동 검사합니다.
- 배포 작업에는 원본 용량과 gzip 예상 전송량이 함께 출력됩니다.

실행 전 `KAKAO_REST_API_KEY` 환경변수가 필요합니다. `FOODSAFETY_API_KEY`가 있으면
식약처 변경정보 API도 병합하고, 없으면 보유한 행안부 인허가 상태 자료만 사용합니다.
행안부 파일데이터는 인증 없이 안정적으로 자동 내려받을 수 있는 공개 엔드포인트가
아니므로 `data` 폴더의 최신 CSV 스냅샷을 사용합니다.

명령으로 실행하거나 일부 지역만 시험할 때는 다음 형식을 사용합니다.

```powershell
python .\update_restaurant_data.py "C:\path\to\private-source.xlsx"
python .\update_restaurant_data.py --regions guyeong cheonsang --use-cache
python .\update_restaurant_data.py "C:\path\to\파일.xlsx" --dry-run
```

`--use-cache`는 카카오 장소 검색 결과를 재사용하는 빠른 점검용 옵션입니다. 기본
실행은 카카오 장소를 다시 조회합니다.

최종 화면 데이터는 아래 우선순위로 생성해 `restaurant-catalog-{지역ID}.js`에 저장합니다. 구영리는 기존 주소 호환을 위해 `restaurant-catalog.js`를 사용합니다.

1. **카카오 Local API**: 선택 지역의 음식점(`FD6`)과 카페(`CE7`)를 기준 목록으로 수집합니다. 밀집 구역은 검색 결과 한도를 넘지 않도록 자동 분할하고 카카오 장소 ID로 중복 제거합니다.
2. **행안부 공공데이터**: 카카오 장소와 업체명·주소가 일치할 때 인허가 상태, 업종, 허가일을 보조정보로 붙입니다. 행안부에만 있는 업체는 새 카드로 만들지 않습니다.
3. **엑셀 이용자료**: 업체명·주소·공공데이터 연결값으로 이용횟수, 사용금액, 월별 추세를 마지막에 병합합니다. 기준 목록에 없는 엑셀 업체는 카카오 키워드 검색으로 현재 장소가 확인될 때만 추가합니다.

카카오 REST API 키는 브라우저에 넣지 않고 생성 스크립트의 `KAKAO_REST_API_KEY` 환경변수에서만 사용합니다.

```powershell
python .\build_restaurant_catalog.py cheonsang
python .\build_restaurant_catalog.py cheonsang --refresh
```

`--refresh`는 저장된 카카오 응답 캐시를 무시하고 전체 장소를 다시 조회합니다.

지역 카탈로그를 갱신한 뒤 메인의 통합 랭킹도 다시 생성합니다. 통합 랭킹은 도시락 업체를 제외한 5개 지역에서 비공개 원자료로 방문 순서를 계산한 뒤, 업체 정보·순위·상대 추세만 100위까지 공개 파일에 저장합니다.

```powershell
python .\build_restaurant_ranking.py
```

## 기본 탑재 데이터 기준

`input` 폴더에서 선택한 최신 엑셀의 첫 번째 시트를 읽고 아래 순서로 거래 지역을
판정합니다.

1. `region_config.py`의 지역별 `usage_tokens`와 주소가 일치하는지 확인
2. 도로명과 건물번호가 해당 지역 공공 인허가 주소와 정확히 일치하는지 확인
3. 남은 주소는 `usage_admin_tokens` 범위 안에서 카카오 주소 API의 지번 행정리 확인

따라서 도로명에 `구영리`가 없고 지번만 구영리인 `대리로·대리1길·대리2길` 같은
주소도 자동으로 포함됩니다. 음식점·카페 업종만 포함하고 정육점, 농수산물,
식품잡화 등 비음식점 업종은 제외합니다. 엑셀의 `결제일`은
실제 이용월보다 한 달 뒤에 기록되는 기준이므로, 월별 추세와 최근 이용일에는 항상
한 달 앞당긴 실제 이용일을 사용합니다. 예를 들어 엑셀의 `2026.7` 거래는 화면에서
`2026.6` 이용으로 반영됩니다.

업체 정합성 비교의 주소키는 `도로명+건물번호` 또는 `법정동·리+지번` 단위입니다.
같은 도로나 같은 상가에 있다는 이유만으로 합치지 않으며, 상호 핵심어가 일치하거나
검증된 한글·영문 별칭인 경우에만 카카오 장소와 이용내역을 연결합니다.

업체 집계는 `가맹점사업자번호`를 우선 사용하고 번호가 없을 때 `업체명 정규화 + 도로/지번 주소키`를 사용합니다. 예를 들어 `호훈테이블(HoHoon Table)`과 `호훈테이블`처럼 표기가 갈린 항목도 동일 사업자번호이면 합칩니다.

이용점수는 데이터 생성 단계에서 카테고리 안의 이용횟수와 총사용금액을 각각 50% 반영해 정규화합니다. 정확한 횟수와 금액은 브라우저로 전달하지 않습니다.

```text
카테고리 1위 95점 / 이용자료 없음 65점
```

## 동네 추가 방법

새 동네를 추가할 때는 프론트 설정과 데이터 생성 설정을 같은 ID로 맞춥니다.

현재 미리 잡아둔 지역 ID는 아래와 같습니다.

```text
guyeong    구영리
cheonsang  천상리
gulhwa     굴화리
mugeo      무거동
eonyang    언양읍·삼남읍
```

1. `region_config.py`에 동네 블록을 추가합니다.
   - `id`: URL과 데이터 생성에서 사용할 영문 ID
   - `name`: 화면에 보여줄 동네명
   - `center`: 지도 중심 좌표
   - `scope_tokens`: 공공·카카오 주소를 제한할 행정구역명
   - `usage_tokens`: 엑셀 도로명주소를 찾을 검색어
   - `usage_admin_tokens`: 누락 주소를 카카오 지번으로 확인할 상위 행정구역명
   - `bounds`: 카카오 장소를 수집할 사각 영역
   - `addressKeyPattern`: 같은 업체를 묶을 때 사용할 도로명/지번 패턴
2. `app-config.js`의 `regions`에도 같은 `id`로 화면용 동네 블록을 추가합니다.
3. 아래처럼 원하는 동네 ID로 데이터를 다시 생성합니다.

```powershell
python .\build_public_restaurant_list.py cheonsang
python .\build_license_status.py cheonsang
python .\build_restaurant_master.py cheonsang "C:\path\to\맛집데이터.xlsx"
python .\build_public_restaurants_js.py cheonsang
python .\build_restaurant_catalog.py cheonsang
```

새 엑셀 파일을 직접 지정해 공공데이터와 정합성을 맞출 때는 아래처럼 실행합니다.

```powershell
python .\build_restaurant_master.py guyeong "C:\path\to\맛집데이터.xlsx"
```

마스터 산출물은 `data/processed/{동네ID}_restaurant_master.csv`에 생성됩니다. 이 파일은 행안부와 엑셀의 중간 대조자료이며, 화면의 최종 기준 목록은 카카오 기반 지역별 카탈로그입니다. 매칭 결과는 `data/processed/{동네ID}_restaurant_catalog_report.json`에서 확인합니다.

외부 세부정보 산출물은 `data/processed/{동네ID}_restaurant_external_details.csv`와 `data/processed/{동네ID}_restaurant_enriched_master.csv`에 생성됩니다. 다이닝코드와 테이블링은 공식 공개 API가 확인되지 않아 자동 수집값으로 확정하지 않고, 검색 URL과 사람이 확인한 공개 상세정보만 분리 저장합니다.

4. URL은 아래처럼 동네별로 나눠 확인할 수 있습니다.

```text
http://127.0.0.1:5173/?region=guyeong&mode=region
http://127.0.0.1:5173/?region=mugeo&mode=region
```

GitHub Pages에 올릴 때도 같은 방식으로 `?region=동네ID` 주소를 공유하면 됩니다. 나중에 여러 동네 데이터를 한 파일로 합치는 구조로 바꿀 수 있도록, 현재 코드는 지역 선택값과 데이터 생성 기준을 분리해 두었습니다.

## 데이터 메모

식당 목록과 일부 영업시간/주소는 공개 검색 결과 기반의 MVP 시드 데이터입니다. 추천 점수, 가성비, 언급량은 실제 리뷰 플랫폼 점수가 아니라 비교 UI 검증을 위한 내부 예시 지표입니다.
