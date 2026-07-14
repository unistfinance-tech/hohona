from __future__ import annotations

from pathlib import Path

from runtime_payload import (
    compact_bento_restaurant,
    compact_restaurants,
    private_catalog_path,
    read_private_catalog,
    read_window_value,
    write_private_catalog,
    write_window_values,
)


ROOT = Path(__file__).resolve().parent
CATALOG_FILES = (
    ("guyeong", "restaurant-catalog.js"),
    ("cheonsang", "restaurant-catalog-cheonsang.js"),
    ("gulhwa", "restaurant-catalog-gulhwa.js"),
    ("mugeo", "restaurant-catalog-mugeo.js"),
    ("eonyang", "restaurant-catalog-eonyang.js"),
)


def optimize(path: Path, variable_name: str, transform) -> tuple[int, int]:
    before = path.stat().st_size
    value = read_window_value(path, variable_name)
    optimized = transform(value)
    write_window_values(path, {variable_name: optimized})
    return before, path.stat().st_size


def optimize_catalog(region_id: str, path: Path) -> tuple[int, int]:
    before = path.stat().st_size
    public_value = read_window_value(path, "restaurantCatalog")
    if not isinstance(public_value, list):
        raise ValueError(f"Catalog must be a list: {path.name}")

    private_path = private_catalog_path(ROOT, region_id)
    contains_exact_usage = any(
        isinstance(item, dict)
        and any(key in item for key in ("usageCount", "usageAmount", "usageTrend"))
        for item in public_value
    )
    if contains_exact_usage:
        write_private_catalog(private_path, public_value)
        private_value = public_value
    elif private_path.exists():
        private_value = read_private_catalog(private_path)
    else:
        raise FileNotFoundError(f"Private source catalog is missing: {private_path}")

    write_window_values(path, {"restaurantCatalog": compact_restaurants(private_value)})
    return before, path.stat().st_size


def main() -> None:
    total_before = 0
    total_after = 0

    for region_id, filename in CATALOG_FILES:
        path = ROOT / filename
        before, after = optimize_catalog(region_id, path)
        total_before += before
        total_after += after
        print(f"{filename}: {before:,} -> {after:,} bytes")

    assets = (
        (
            ROOT / "bento-restaurants.js",
            "bentoRestaurants",
            lambda rows: [compact_bento_restaurant(item) for item in rows],
        ),
        (ROOT / "external-details.js", "restaurantExternalDetails", lambda rows: rows),
    )
    for path, variable_name, transform in assets:
        before, after = optimize(path, variable_name, transform)
        total_before += before
        total_after += after
        print(f"{path.name}: {before:,} -> {after:,} bytes")

    from build_restaurant_ranking import write_ranking

    ranking_path = ROOT / "restaurant-ranking.js"
    ranking_before = ranking_path.stat().st_size
    write_ranking()
    ranking_after = ranking_path.stat().st_size
    total_before += ranking_before
    total_after += ranking_after
    print(f"{ranking_path.name}: {ranking_before:,} -> {ranking_after:,} bytes")

    reduction = 100 * (total_before - total_after) / max(total_before, 1)
    print(f"total: {total_before:,} -> {total_after:,} bytes ({reduction:.1f}% reduction)")


if __name__ == "__main__":
    main()
