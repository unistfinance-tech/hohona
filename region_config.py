REGIONS = {
    "guyeong": {
        "name": "구영리",
        "area_label": "울산광역시 울주군 범서읍",
        "center": {"lat": 35.5724, "lng": 129.2417},
        "bounds": (129.2325, 35.5620, 129.2515, 35.5790),
        "scope_tokens": ["구영리"],
        "usage_tokens": ["구영", "구영로", "구영앞길", "점촌", "대리3길"],
        "usage_admin_tokens": ["범서읍"],
        "query_terms": ["구영리", "범서읍 구영리"],
        "excluded_names": ["막끌리네", "갓포HERO"],
        "public_fallback_ids": ["3730000-104-2026-00043"],
        "search_tokens": ["구영", "구영로", "구영앞길", "점촌", "대리3길"],
        "address_key_pattern": r"(구영로|구영앞길|점촌[0-9]*길|대리3길|구영리)\s*([0-9-]+)?",
        "marker_center": (35.5719, 129.2415),
        "localdata_files": [
            ("일반음식점", "data/ulju_general_restaurants.csv"),
            ("휴게음식점", "data/ulju_rest_cafes.csv"),
        ],
    },
    "cheonsang": {
        "name": "천상리",
        "area_label": "울산광역시 울주군 범서읍",
        "center": {"lat": 35.5628, "lng": 129.2297},
        "bounds": (129.2160, 35.5510, 129.2425, 35.5735),
        "scope_tokens": ["천상리"],
        "usage_tokens": ["천상"],
        "usage_admin_tokens": ["범서읍"],
        "query_terms": ["천상리", "범서읍 천상리"],
        "search_tokens": ["천상", "천상리", "천상중앙길"],
        "address_key_pattern": r"(천상중앙길|천상[0-9]*길|천상리)\s*([0-9-]+)?",
        "marker_center": (35.5628, 129.2297),
        "localdata_files": [
            ("일반음식점", "data/ulju_general_restaurants.csv"),
            ("휴게음식점", "data/ulju_rest_cafes.csv"),
        ],
    },
    "gulhwa": {
        "name": "굴화리",
        "area_label": "울산광역시 울주군 범서읍",
        "center": {"lat": 35.5503, "lng": 129.2564},
        "bounds": (129.2440, 35.5390, 129.2700, 35.5600),
        "scope_tokens": ["굴화리"],
        "usage_tokens": ["굴화"],
        "usage_admin_tokens": ["범서읍"],
        "query_terms": ["굴화리", "범서읍 굴화리"],
        "search_tokens": ["굴화", "굴화리"],
        "address_key_pattern": r"(굴화[0-9]*길|굴화리)\s*([0-9-]+)?",
        "marker_center": (35.5503, 129.2564),
        "localdata_files": [
            ("일반음식점", "data/ulju_general_restaurants.csv"),
            ("휴게음식점", "data/ulju_rest_cafes.csv"),
        ],
    },
    "mugeo": {
        "name": "무거동",
        "area_label": "울산광역시 남구",
        "center": {"lat": 35.5438, "lng": 129.2609},
        "bounds": (129.2450, 35.5280, 129.2780, 35.5590),
        "scope_tokens": ["무거동"],
        "usage_tokens": ["무거동", "대학로"],
        "usage_admin_tokens": ["울산 남구"],
        "query_terms": ["무거동", "울산 남구 무거동"],
        "search_tokens": ["무거", "무거동", "대학로"],
        "address_key_pattern": r"(대학로|무거[0-9]*길|무거동)\s*([0-9-]+)?",
        "marker_center": (35.5438, 129.2609),
        "localdata_files": [
            ("일반음식점", "data/namgu_general_restaurants.csv"),
            ("휴게음식점", "data/namgu_rest_cafes.csv"),
        ],
    },
    "eonyang": {
        "name": "언양·삼남",
        "area_label": "울산광역시 울주군",
        "center": {"lat": 35.5550, "lng": 129.1300},
        "bounds": (129.0500, 35.4900, 129.2100, 35.6200),
        "scope_tokens": ["언양읍", "삼남읍"],
        "usage_tokens": ["언양읍", "삼남읍", "삼남면"],
        "usage_admin_tokens": ["언양읍", "삼남읍", "삼남면"],
        "query_terms": ["언양읍", "삼남읍"],
        "excluded_names": ["교동민속주점", "복순도가 울산역점"],
        "search_tokens": ["언양읍", "삼남읍"],
        "address_key_pattern": r"(언양읍|삼남읍|언양로|울산역로|교동로|반구대로|유니스트길)\s*([0-9-]+)?",
        "marker_center": (35.5550, 129.1300),
        "localdata_files": [
            ("일반음식점", "data/ulju_general_restaurants.csv"),
            ("휴게음식점", "data/ulju_rest_cafes.csv"),
        ],
    },
}


DEFAULT_REGION_ID = "guyeong"


def get_region(region_id: str | None):
    selected_id = region_id or DEFAULT_REGION_ID
    if selected_id not in REGIONS:
        available = ", ".join(REGIONS)
        raise SystemExit(f"Unknown region id: {selected_id}. Available: {available}")
    return selected_id, REGIONS[selected_id]
