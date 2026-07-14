const config = window.APP_CONFIG || {};
const APP_VERSION = "20260714-170114-privacy";
const urlParams = new URLSearchParams(window.location.search);
const requestedRegionId = urlParams.get("region");
const requestedMode = urlParams.get("mode");
const requestedFocusId = urlParams.get("focus");
const isRestaurantMode = requestedMode === "guyeong" || requestedMode === "region";
const viewMode = requestedMode === "bento" ? "bento" : isRestaurantMode ? "region" : "gate";
const activeMode = viewMode === "gate" ? "region" : viewMode;
const activeRegion =
  (config.regions || []).find((region) => region.id === (requestedRegionId || config.activeRegionId)) ||
  (config.regions || [])[0] ||
  { name: "구영리", center: { lat: 35.5724, lng: 129.2417 } };
const center = activeRegion.center;
const basePoint = config.basePoint || { lat: 35.5761, lng: 129.1896 };
const basePointLabel = config.basePointLabel || "UNIST 기준";
const usageTrendConfig = config.usageTrend || {};
const usageTrendStartMonth = usageTrendConfig.startMonth || "2025-01";
const configuredUsageTrendEndMonth = usageTrendConfig.endMonth || "2026-06";
const bentoScope = config.bentoScope || {};
const bentoMaxDistanceKm = Number(bentoScope.maxDistanceKm) || 15;
const bentoExcludedDistricts = new Set(bentoScope.excludedDistricts || ["북구", "동구"]);
const usageScoreBase = 65;
const unknownLabel = "확인필요";
const mapTileUrl = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const mapTileOptions = {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
};
const categoryDisplayNames = new Map((config.categoryFilters || []).map((filter) => [filter.value, filter.label]));
const restaurantCatalog = Array.isArray(window.restaurantCatalog) ? window.restaurantCatalog : [];
const bentoRestaurants = Array.isArray(window.bentoRestaurants) ? window.bentoRestaurants : [];
const restaurantRanking = window.restaurantRanking && Array.isArray(window.restaurantRanking.items)
  ? window.restaurantRanking
  : { items: [] };

const externalDetails = activeRegion.id === "guyeong" && Array.isArray(window.restaurantExternalDetails)
  ? window.restaurantExternalDetails
  : [];
const externalDetailByName = new Map();
externalDetails.forEach((detail) => {
  [detail.name, ...(detail.aliases || [])].forEach((name) => {
    externalDetailByName.set(normalizeText(name), detail);
  });
});
const baseRestaurantData = restaurantCatalog;

function isLunchboxRestaurant(item) {
  const nameText = String(item.name || "");
  if (/도시락|한솥|본도시락/.test(nameText)) return true;

  const typeText = [item.category, item.menu].filter(Boolean).join(" ");
  return /케이터링|출장조리|출장요리|배달전문/.test(typeText);
}

function isKimbapShop(item) {
  const nameText = String(item.name || "");
  return /김밥/.test(nameText) && !/도시락/.test(nameText);
}

function categoryOverrideFor(item) {
  const configuredOverride = activeRegion.categoryOverrides?.[item.publicId];
  if (configuredOverride) return configuredOverride;
  return isLunchboxRestaurant(item) ? { category: "도시락" } : null;
}

function normalizeRestaurantItem(item) {
  const categoryOverride = categoryOverrideFor(item);
  const normalizedItem = categoryOverride
    ? {
        ...item,
        category: categoryOverride.category,
        menu: categoryOverride.menu || item.menu,
      }
    : item;
  const detail = externalDetailByName.get(normalizeText(normalizedItem.name)) || null;
  if (!detail) return normalizedItem;
  return {
    ...normalizedItem,
    menu: detail.externalMenu || normalizedItem.menu,
    hours: detail.externalHours || normalizedItem.hours,
    phone: normalizedItem.phone || detail.externalPhone,
    externalDetail: detail,
  };
}

const excludedRestaurantNames = new Set((activeRegion.excludedNames || []).map(normalizeText));
const allRestaurantData = baseRestaurantData
  .map(normalizeRestaurantItem)
  .filter((item) => !excludedRestaurantNames.has(normalizeText(item.name)));

function latestUsageTrendMonth(items) {
  return items.reduce((latest, item) => {
    const itemLatest = (Array.isArray(item.trend) ? item.trend : []).reduce((lastMonth, point) => {
      const month = String(point.month || "");
      return /^\d{4}-\d{2}$/.test(month) && month > lastMonth ? month : lastMonth;
    }, "");
    return itemLatest > latest ? itemLatest : latest;
  }, "");
}

const usageTrendEndMonth =
  latestUsageTrendMonth([...allRestaurantData, ...restaurantRanking.items]) || configuredUsageTrendEndMonth;
const allRestaurantByPublicId = new Map(
  allRestaurantData.filter((item) => item.publicId).map((item) => [item.publicId, item]),
);
const bentoRestaurantData = bentoRestaurants
  .map((item) => {
    const localItem = allRestaurantByPublicId.get(item.publicId);
    return localItem
      ? {
          ...item,
          ...localItem,
          district: item.district,
          schoolDistanceKm: item.schoolDistanceKm,
        }
      : normalizeRestaurantItem(item);
  })
  .filter((item) => {
    const district = item.district || districtFromAddress(item.address);
    return (
      item.category === "도시락" &&
      !isKimbapShop(item) &&
      !bentoExcludedDistricts.has(district) &&
      Number.isFinite(item.lat) &&
      Number.isFinite(item.lng) &&
      distanceKm(basePoint, item) < bentoMaxDistanceKm
    );
  });

const restaurantData = activeMode === "bento"
  ? bentoRestaurantData
  : allRestaurantData;
const restaurantById = new Map(restaurantData.map((item) => [item.id, item]));
let state = {
  category: "all",
  query: "",
  sort: "visits",
  compare: new Set(),
  focusedId: restaurantData.some((item) => item.id === requestedFocusId) ? requestedFocusId : null,
};

function addBaseMapTiles(targetMap) {
  L.tileLayer(mapTileUrl, mapTileOptions).addTo(targetMap);
}

const map = L.map("map", { zoomControl: false }).setView([center.lat, center.lng], 14);
let bentoOverviewFitted = false;
L.control.zoom({ position: "bottomleft" }).addTo(map);
addBaseMapTiles(map);

function refreshMapSize() {
  window.requestAnimationFrame(() => {
    map.invalidateSize({ pan: false });
  });
}

function scheduleMapRefresh() {
  refreshMapSize();
  [120, 350, 900].forEach((delay) => window.setTimeout(refreshMapSize, delay));
}

scheduleMapRefresh();
window.addEventListener("load", refreshMapSize);
window.addEventListener("resize", scheduleMapRefresh);
window.addEventListener("orientationchange", () => {
  window.setTimeout(scheduleMapRefresh, 250);
});

if (window.ResizeObserver) {
  new ResizeObserver(scheduleMapRefresh).observe(document.querySelector(".map-pane"));
}

const markerLayer = L.layerGroup().addTo(map);

const listEl = document.querySelector("#restaurantList");
const categoryFilterEl = document.querySelector("#categoryFilters");
const searchInput = document.querySelector("#searchInput");
const sortSelect = document.querySelector("#sortSelect");
const mapCount = document.querySelector("#mapCount");
const compareCount = document.querySelector("#compareCount");
const comparePanel = document.querySelector("#comparePanel");
const compareTable = document.querySelector("#compareTable");
const clearCompareBtn = document.querySelector("#clearCompare");
const compareLimitNotice = document.querySelector("#compareLimitNotice");
const noticeBtn = document.querySelector("#noticeBtn");
const noticePopover = document.querySelector("#noticePopover");
const trendPanel = document.querySelector("#trendPanel");
const trendTitle = document.querySelector("#trendTitle");
const trendChart = document.querySelector("#trendChart");
const trendSummary = document.querySelector("#trendSummary");
const gateScreen = document.querySelector("#gateScreen");
const rankingBtn = document.querySelector("#rankingBtn");
const rankingPanel = document.querySelector("#rankingPanel");
const rankingList = document.querySelector("#rankingList");
const closeRankingBtn = document.querySelector("#closeRanking");
const inquiryBtn = document.querySelector("#inquiryBtn");
const inquiryPanel = document.querySelector("#inquiryPanel");
const inquiryForm = document.querySelector("#inquiryForm");
const inquiryType = document.querySelector("#inquiryType");
const inquiryRegion = document.querySelector("#inquiryRegion");
const inquiryStatus = document.querySelector("#inquiryStatus");
const closeInquiryBtn = document.querySelector("#closeInquiry");
let compareLimitNoticeTimer;

function showCompareLimitNotice() {
  window.clearTimeout(compareLimitNoticeTimer);
  compareLimitNotice.hidden = false;
  compareLimitNoticeTimer = window.setTimeout(() => {
    compareLimitNotice.hidden = true;
  }, 2000);
}
const gateMapElement = document.querySelector("#gateMap");
const appShell = document.querySelector(".app-shell");
const homeNavBtn = document.querySelector("#homeNavBtn");
const mainNavBtn = document.querySelector("#mainNavBtn");
const backNavBtn = document.querySelector("#backNavBtn");
const forwardNavBtn = document.querySelector("#forwardNavBtn");

const gateMap = gateMapElement
  ? L.map(gateMapElement, {
      attributionControl: true,
      boxZoom: false,
      doubleClickZoom: false,
      dragging: false,
      keyboard: false,
      scrollWheelZoom: false,
      tap: false,
      touchZoom: false,
      zoomControl: false,
    }).setView([basePoint.lat, basePoint.lng], 16)
  : null;

if (gateMap) {
  addBaseMapTiles(gateMap);

  L.circleMarker([basePoint.lat, basePoint.lng], {
    radius: 6,
    color: "#fff",
    weight: 2,
    fillColor: "#186a5e",
    fillOpacity: 1,
    interactive: false,
  })
    .addTo(gateMap)
    .bindTooltip("UNIST", {
      permanent: true,
      direction: "top",
      offset: [0, -5],
      className: "gate-map-label",
    });
}

sortSelect.value = state.sort;

const resolvedAppTitle = activeMode === "bento" ? "울산 도시락 업체" : `${activeRegion.name} 음식점`;
const mapHeadingTitle = activeMode === "bento" ? "울산 도시락" : activeRegion.name;
document.title = resolvedAppTitle;
document.querySelector("#appTitle").textContent = mapHeadingTitle;
document.querySelector(".map-pane")?.setAttribute("aria-label", `${resolvedAppTitle} 지도`);
document.querySelector(".control-pane")?.setAttribute("aria-label", `${resolvedAppTitle} 검색과 비교`);
if (activeMode === "bento") {
  searchInput.placeholder = "도시락 업체, 메뉴, 주소 검색";
  noticePopover.textContent = `울산 내 영업 중인 도시락·배달·케이터링 업체(${bentoMaxDistanceKm}km 내외) 기준`;
}

function setGateOpen(isOpen) {
  gateScreen?.classList.toggle("open", isOpen);
  appShell?.classList.toggle("is-gated", isOpen);
  if (!isOpen) return;

  requestAnimationFrame(() => {
    gateMap?.invalidateSize(false);
    gateMap?.setView([basePoint.lat, basePoint.lng], 16, { animate: false });
  });
}

function enterMode(mode) {
  const params = new URLSearchParams(window.location.search);
  params.set("region", mode === "bento" ? "guyeong" : activeRegion.id || requestedRegionId || "guyeong");
  params.set("mode", mode);
  params.delete("focus");
  params.set("v", APP_VERSION);
  window.location.search = params.toString();
}

function enterRegion(regionId) {
  const params = new URLSearchParams(window.location.search);
  params.set("region", regionId);
  params.set("mode", "region");
  params.delete("focus");
  params.set("v", APP_VERSION);
  window.location.search = params.toString();
}

function enterRankedRestaurant(regionId, restaurantId) {
  const params = new URLSearchParams(window.location.search);
  params.set("region", regionId);
  params.set("mode", "region");
  params.set("focus", restaurantId);
  params.set("v", APP_VERSION);
  window.location.search = params.toString();
}

let gateNavigationPending = false;

function beginGateNavigation(button, navigate) {
  if (gateNavigationPending) return;
  gateNavigationPending = true;
  button.classList.add("is-activating");
  button.setAttribute("aria-pressed", "true");
  const gateActions = button.closest(".gate-actions");
  gateActions?.classList.add("is-navigating");
  gateActions?.setAttribute("aria-busy", "true");
  window.setTimeout(navigate, 200);
}

function goHome() {
  const params = new URLSearchParams();
  params.set("region", "guyeong");
  params.set("mode", "region");
  params.set("v", APP_VERSION);
  window.location.search = params.toString();
}

setGateOpen(viewMode === "gate");

function formatPlaceCount(count) {
  return `${String(count).padStart(2, "0")}곳`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderRanking() {
  if (!rankingList) return;
  const items = restaurantRanking.items.slice(0, Number(restaurantRanking.limit) || 50);
  if (!items.length) {
    rankingList.innerHTML = '<li class="ranking-state">랭킹 데이터가 없습니다.</li>';
    return;
  }

  rankingList.innerHTML = items
    .map((item) => {
      const rankClass = item.rank <= 3 ? ` top-${item.rank}` : "";
      return `
        <li class="ranking-item${rankClass}">
          <button
            type="button"
            data-ranking-region="${escapeHtml(item.regionId)}"
            data-ranking-id="${escapeHtml(item.id)}"
            aria-label="${item.rank}위 ${escapeHtml(item.name)}, ${escapeHtml(item.regionName)}에서 보기"
          >
            <span class="ranking-position">${item.rank}</span>
            <span class="ranking-place">
              <strong>${escapeHtml(item.name)}</strong>
              <small>${escapeHtml(item.regionName)} · ${escapeHtml(displayCategory(item.category))}</small>
            </span>
            <span class="ranking-trend">${usageTrendTemplate(item)}</span>
            <span class="ranking-chevron" data-lucide="chevron-right" aria-hidden="true"></span>
          </button>
        </li>
      `;
    })
    .join("");

  window.lucide?.createIcons();
}

function openRankingPanel() {
  if (!rankingPanel) return;
  closeInquiryPanel(false);
  renderRanking();
  setGateOverlay(rankingPanel, "ranking-open", true, closeRankingBtn);
  rankingList?.scrollTo({ top: 0 });
}

function closeRankingPanel(restoreFocus = true) {
  setGateOverlay(rankingPanel, "ranking-open", false, restoreFocus ? rankingBtn : null);
}

function openInquiryPanel() {
  if (!inquiryPanel) return;
  closeRankingPanel(false);
  inquiryStatus.textContent = "";
  setGateOverlay(inquiryPanel, "inquiry-open", true, inquiryType);
}

function closeInquiryPanel(restoreFocus = true) {
  setGateOverlay(inquiryPanel, "inquiry-open", false, restoreFocus ? inquiryBtn : null);
}

function setGateOverlay(panel, stateClass, isOpen, focusTarget) {
  if (!panel) return;
  panel.hidden = !isOpen;
  panel.setAttribute("aria-hidden", String(!isOpen));
  gateScreen?.classList.toggle(stateClass, isOpen);
  focusTarget?.focus();
}

function renderCategoryFilters() {
  const categoryCounts = restaurantData.reduce((counts, item) => {
    counts[item.category] = (counts[item.category] || 0) + 1;
    return counts;
  }, {});
  const filters = (config.categoryFilters || [{ label: "전체", value: "all" }]).filter(
    (filter) => filter.value === "all" || categoryCounts[filter.value] > 0
  );
  categoryFilterEl.innerHTML = filters
    .map(
      (filter, index) => {
        const categoryClass = filter.value === "all" ? "cat-all" : markerCategoryClass(filter.value);
        return `<button class="chip ${categoryClass} ${index === 0 ? "active" : ""}" type="button" data-filter="category" data-value="${filter.value}">${filter.label}<span>${filter.value === "all" ? restaurantData.length : categoryCounts[filter.value]}</span></button>`;
      }
    )
    .join("");
}

function distanceKm(a, b) {
  const rad = Math.PI / 180;
  const r = 6371;
  const dLat = (b.lat - a.lat) * rad;
  const dLng = (b.lng - a.lng) * rad;
  const lat1 = a.lat * rad;
  const lat2 = b.lat * rad;
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(h));
}

function normalizeText(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/\s+/g, "")
    .replace(/\(주\)|㈜|주식회사/g, "")
    .replace(/[^0-9a-z가-힣]/g, "");
}

function restaurantDescription(item) {
  const detail = item.externalDetail || {};
  const parts = [
    detail.externalTags || restaurantMenu(item),
  ].filter(Boolean);
  return parts.join(" · ");
}

function restaurantMenu(item) {
  return item.menu || displayCategory(item.category);
}

function combinedScoreLabel(item) {
  return item.combinedScore ?? "준비중";
}

function pointLabel(value) {
  return Number.isFinite(Number(value)) ? `${value}점` : value;
}

function usageScore(item) {
  const score = Number(item.usageScore);
  return Number.isFinite(score) ? Math.round(score) : usageScoreBase;
}

function rankValue(item, field) {
  const rank = Number(item[field]);
  return Number.isInteger(rank) && rank > 0 ? rank : Number.MAX_SAFE_INTEGER;
}

function distanceLabel(item) {
  const km = distanceKm(basePoint, item);
  const precision = activeMode === "bento" && km >= bentoMaxDistanceKm - 0.05 ? 2 : 1;
  return `${basePointLabel} ${km.toFixed(precision)}km`;
}

function districtFromAddress(address) {
  const match = String(address || "").match(/울산(?:광역시)?\s+(울주군|남구|중구|북구|동구)/);
  return match?.[1] || "";
}

function shortAddress(address) {
  const value = String(address || "").trim();
  const parts = value.split(/\s+/);
  if (activeMode === "bento") {
    const districtIndex = parts.findIndex((part) => /(?:울주군|남구|중구|북구|동구)$/.test(part));
    return districtIndex >= 0 ? parts.slice(districtIndex).join(" ") : value;
  }
  const start = parts.findIndex((part) => /[\uC74D\uBA74\uB3D9\uB9AC]$/.test(part));
  return start >= 0 ? parts.slice(start).join(" ") : value;
}

function formatPhoneNumber(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";

  const digits = raw.replace(/\D/g, "");
  if (!digits) return raw;

  if (digits.startsWith("050") && digits.length === 12) {
    return `${digits.slice(0, 4)}-${digits.slice(4, 8)}-${digits.slice(8)}`;
  }

  if (digits.startsWith("02")) {
    if (digits.length === 9) {
      return `${digits.slice(0, 2)}-${digits.slice(2, 5)}-${digits.slice(5)}`;
    }
    if (digits.length === 10) {
      return `${digits.slice(0, 2)}-${digits.slice(2, 6)}-${digits.slice(6)}`;
    }
  }

  if (digits.length === 11) {
    return `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7)}`;
  }
  if (digits.length === 10) {
    return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}`;
  }
  if (digits.length === 8 && /^(15|16|18)/.test(digits)) {
    return `${digits.slice(0, 4)}-${digits.slice(4)}`;
  }

  return raw;
}

function restaurantPhone(item) {
  const phone = item.phone || item.externalDetail?.externalPhone;
  return phone ? formatPhoneNumber(phone) : unknownLabel;
}

function restaurantHours(item) {
  const hours = String(item.hours || "").trim();
  return !hours || hours === "영업시간 확인 필요" ? unknownLabel : hours;
}

function usageTrendPoints(item) {
  return Array.isArray(item.trend)
    ? item.trend
        .map((point) => ({
          month: String(point.month || ""),
          level: Math.max(0, Math.min(4, Math.round(Number(point.level) || 0))),
        }))
    : [];
}

function visibleUsageTrendPoints(item) {
  return usageTrendPoints(item)
    .filter((point) => point.month >= usageTrendStartMonth && point.month <= usageTrendEndMonth)
    .sort((a, b) => a.month.localeCompare(b.month));
}

function trendMonthLabel(month) {
  const [year, rawMonth] = String(month).split("-");
  return `${year}.${Number(rawMonth)}`;
}

function usageTrendTemplate(item) {
  const points = visibleUsageTrendPoints(item);
  if (!points.some((point) => point.level > 0)) {
    return `<span class="usage-trend-empty" aria-label="월별 이용 데이터 없음">no data</span>`;
  }
  const firstMonth = points[0].month;
  const lastMonth = points[points.length - 1].month;
  const maxLevel = Math.max(...points.map((point) => point.level), 1);
  const minLevel = Math.min(...points.map((point) => point.level));
  const range = Math.max(maxLevel - minLevel, 1);
  const pathPoints = points
    .map((point, index) => {
      const x = points.length === 1 ? 24 : Math.round((index / (points.length - 1)) * 48);
      const y = Math.round(22 - ((point.level - minLevel) / range) * 18);
      return `${x},${y}`;
    })
    .join(" ");
  const title = points.map((point) => `${point.month} 상대 수준 ${point.level}`).join(" / ");
  return `
    <span class="usage-trend" aria-label="${trendMonthLabel(firstMonth)}부터 ${trendMonthLabel(lastMonth)}까지 월별 이용 추세">
      <svg class="usage-sparkline" viewBox="0 0 48 24" role="img" aria-label="${title}">
        <polyline points="${pathPoints}"></polyline>
      </svg>
    </span>
  `;
}

function fullUsageTrendTemplate(item) {
  const points = visibleUsageTrendPoints(item);
  if (!points.length || !points.some((point) => point.level > 0)) {
    return `<div class="trend-empty-state">no data</div>`;
  }
  const firstMonth = points[0].month;
  const lastMonth = points[points.length - 1].month;

  const maxLevel = Math.max(...points.map((point) => point.level), 1);
  const minLevel = Math.min(...points.map((point) => point.level));
  const range = Math.max(maxLevel - minLevel, 1);
  const width = Math.max(320, points.length * 18);
  const height = 132;
  const leftPad = 20;
  const rightPad = 20;
  const topPad = 12;
  const bottomPad = 25;
  const chartWidth = width - leftPad - rightPad;
  const chartHeight = height - topPad - bottomPad;
  const coords = points.map((point, index) => {
    const x = leftPad + (points.length === 1 ? chartWidth / 2 : (index / (points.length - 1)) * chartWidth);
    const y = topPad + chartHeight - ((point.level - minLevel) / range) * chartHeight;
    return { ...point, x: Math.round(x), y: Math.round(y) };
  });
  const linePoints = coords.map((point) => `${point.x},${point.y}`).join(" ");
  const areaPoints = `${leftPad},${height - bottomPad} ${linePoints} ${width - rightPad},${height - bottomPad}`;
  const markers = coords
    .map((point) => `<circle cx="${point.x}" cy="${point.y}" r="1.9"><title>${point.month} 상대 수준 ${point.level}</title></circle>`)
    .join("");
  const labels = coords
    .filter((_, index) => index % 2 === 0 || index === coords.length - 1)
    .map((point) => `<text x="${point.x}" y="${height - 8}" text-anchor="middle">${point.month.slice(2).replace("-", ".")}</text>`)
    .join("");

  return `
    <div class="trend-chart-scroll">
      <svg class="trend-line-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${item.name} ${trendMonthLabel(firstMonth)}부터 ${trendMonthLabel(lastMonth)}까지 월별 이용 추세">
        <polygon points="${areaPoints}"></polygon>
        <polyline points="${linePoints}"></polyline>
        ${markers}
        ${labels}
      </svg>
    </div>
  `;
}

function openTrendPanel(restaurantId) {
  const item = restaurantById.get(restaurantId);
  if (!item) return;
  const points = visibleUsageTrendPoints(item);
  const activePoints = points.filter((point) => point.level > 0);
  const peak = activePoints.reduce((best, point) => (point.level > best.level ? point : best), { month: "", level: 0 });
  const firstMonth = points[0]?.month;
  const lastMonth = points[points.length - 1]?.month;

  trendTitle.textContent = `${item.name} 월별 이용 추세`;
  trendChart.innerHTML = fullUsageTrendTemplate(item);
  trendSummary.textContent = activePoints.length
    ? `${trendMonthLabel(firstMonth)}~${trendMonthLabel(lastMonth)} · 최고 ${trendMonthLabel(peak.month)}`
    : "no data";
  trendPanel.classList.add("open");
}

function closeTrendPanel() {
  trendPanel.classList.remove("open");
}

function platformQuery(item) {
  const locality = activeMode === "bento"
    ? item.district || districtFromAddress(item.address)
    : String(item.address || "").match(/(구영리|천상리|굴화리|무거동|언양읍|삼남읍)/)?.[1] || activeRegion.name;
  return [item.name, locality, "울산"].filter(Boolean).join(" ");
}

function platformLinks(item) {
  const query = encodeURIComponent(platformQuery(item));
  const tablingQuery = encodeURIComponent(item.name);
  const verifiedTablingUrl = item.externalDetail?.detailSource === "테이블링"
    ? item.externalDetail.detailUrl
    : "";
  return [
    {
      label: "네이버",
      url: `https://map.naver.com/p/search/${query}`,
    },
    {
      label: "카카오",
      url: `https://map.kakao.com/?q=${query}`,
    },
    {
      label: "다이닝코드",
      url: `https://www.diningcode.com/list.dc?query=${query}`,
    },
    {
      label: "테이블링",
      url: verifiedTablingUrl || `https://www.tabling.co.kr/search?keyword=${tablingQuery}`,
    },
  ];
}

function platformLinksTemplate(item) {
  return `
    <div class="platform-links" aria-label="${item.name} 외부 링크">
      ${platformLinks(item)
        .map((link) => `<a href="${link.url}" target="_blank" rel="noreferrer">${link.label}</a>`)
        .join("")}
    </div>
  `;
}

function filteredRestaurants() {
  const query = state.query.trim().toLowerCase();
  return restaurantData
    .filter((item) => {
      const matchesCategory = state.category === "all" || item.category === state.category;
      const detail = item.externalDetail || {};
      const haystack = [
        item.name,
        item.category,
        item.address,
        restaurantMenu(item),
        detail.externalTags,
        detail.reservationHint,
        detail.parkingHint,
      ]
        .join(" ")
        .toLowerCase();
      const matchesQuery = !query || haystack.includes(query);
      const matchesNewEntry = state.sort !== "newEntry" || rankValue(item, "newEntryRank") < Number.MAX_SAFE_INTEGER;
      return matchesCategory && matchesQuery && matchesNewEntry;
    })
    .sort((a, b) => {
      if (state.focusedId) {
        if (a.id === state.focusedId) return -1;
        if (b.id === state.focusedId) return 1;
      }
      if (state.sort === "distance") {
        return distanceKm(basePoint, a) - distanceKm(basePoint, b);
      }
      if (state.sort === "trend") return rankValue(a, "trendRank") - rankValue(b, "trendRank") || a.name.localeCompare(b.name, "ko");
      if (state.sort === "newEntry") return rankValue(a, "newEntryRank") - rankValue(b, "newEntryRank") || a.name.localeCompare(b.name, "ko");
      return rankValue(a, "visitRank") - rankValue(b, "visitRank") || a.name.localeCompare(b.name, "ko");
    });
}

function displayCategory(category) {
  return categoryDisplayNames.get(category) || category;
}

function syncCategoryButtons() {
  document.querySelectorAll("[data-filter='category']").forEach((button) => {
    button.classList.toggle("active", button.dataset.value === state.category);
  });
}

function moveMapToRestaurant(restaurantId) {
  const restaurant = restaurantById.get(restaurantId);
  if (!restaurant || !Number.isFinite(restaurant.lat) || !Number.isFinite(restaurant.lng)) return;

  const focusZoom = Math.max(map.getZoom(), 17);
  map.flyTo([restaurant.lat, restaurant.lng], focusZoom, {
    animate: true,
    duration: 0.45,
  });
}

function focusRestaurant(restaurantId, { scrollToCard = true } = {}) {
  if (!restaurantById.has(restaurantId)) return;

  state.focusedId = restaurantId;
  render();
  window.requestAnimationFrame(() => {
    moveMapToRestaurant(restaurantId);
    if (!scrollToCard) return;

    const focusedCard = document.querySelector(`[data-restaurant-id="${restaurantId}"]`);
    if (!focusedCard) return;
    const listTop = listEl.getBoundingClientRect().top;
    const cardTop = focusedCard.getBoundingClientRect().top;
    listEl.scrollTo({
      top: listEl.scrollTop + cardTop - listTop,
      behavior: "smooth",
    });
  });
}

function markerCategoryClass(category) {
  const classes = {
    "한식": "cat-korean",
    "고기/구이": "cat-meat",
    "국밥/탕": "cat-soup",
    "중식": "cat-chinese",
    "일식": "cat-japanese",
    "해산물/횟집": "cat-seafood",
    "치킨/피자/버거": "cat-fastfood",
    "도시락": "cat-bento",
    "분식/김밥": "cat-snack",
    "카페/디저트": "cat-cafe",
    "베이커리": "cat-bakery",
    "양식": "cat-western",
  };
  return classes[category] || "cat-etc";
}

function renderMarkers(items) {
  markerLayer.clearLayers();

  const shouldHighlightMarkers = state.category !== "all" || state.query.trim();
  const shouldFitBentoOverview =
    activeMode === "bento" && !bentoOverviewFitted && state.category === "all" && !state.query.trim();
  const markerPoints = [];

  items.forEach((item) => {
    if (!Number.isFinite(item.lat) || !Number.isFinite(item.lng)) return;

    const markerColor = markerCategoryClass(item.category);
    const markerSize = 24;
    const markerAnchor = markerSize / 2;
    markerPoints.push([item.lat, item.lng]);
    const isFocusedMarker = state.focusedId === item.id;
    const isDeemphasizedMarker = Boolean(state.focusedId) && !isFocusedMarker;
    const marker = L.marker([item.lat, item.lng], {
      icon: L.divIcon({
        className: `restaurant-dot-marker ${markerColor} ${shouldHighlightMarkers ? "filtered" : ""} ${isFocusedMarker ? "focused" : ""} ${isDeemphasizedMarker ? "deemphasized" : ""}`,
        html: "<span></span>",
        iconSize: [markerSize, markerSize],
        iconAnchor: [markerAnchor, markerAnchor],
        popupAnchor: [0, -markerAnchor],
      }),
      title: item.name,
    }).bindPopup(`
      <p class="popup-title">${item.name}</p>
      <div>${displayCategory(item.category)} · ${restaurantMenu(item)}</div>
      <div class="popup-score">이용점수 ${usageScore(item)}</div>
    `);
    marker.addTo(markerLayer);
    marker.on("click", () => focusRestaurant(item.id));
  });

  if (!state.focusedId && (shouldHighlightMarkers || shouldFitBentoOverview) && markerPoints.length) {
    const bounds = L.latLngBounds(markerPoints);
    const isCategoryFilter = state.category !== "all";
    const isBentoOverview = activeMode === "bento" && !shouldHighlightMarkers;
    const minReadableZoom = isBentoOverview ? 9 : isCategoryFilter ? 15 : 14;
    const enforceReadableZoom = () => {
      if (map.getZoom() < minReadableZoom) {
        map.setZoom(minReadableZoom, { animate: true });
      }
    };
    map.once("moveend", enforceReadableZoom);
    map.fitBounds(bounds.pad(isBentoOverview ? 0.06 : isCategoryFilter ? 0.08 : 0.14), {
      animate: true,
      maxZoom: isBentoOverview ? 12 : isCategoryFilter ? 17 : 16,
      paddingTopLeft: [12, 48],
      paddingBottomRight: [12, 12],
    });
    window.setTimeout(enforceReadableZoom, 350);
    if (isBentoOverview) bentoOverviewFitted = true;
  }
}

function cardTemplate(item) {
  const selected = state.compare.has(item.id);
  const detail = item.externalDetail;
  const categoryClass = markerCategoryClass(item.category);
  const detailBlock = detail
    ? `
        <div class="external-detail">
          <span>${detail.detailSource} 확인</span>
          <span>${detail.externalTags}</span>
          ${detail.reservationHint ? `<span>${detail.reservationHint}</span>` : ""}
          ${detail.parkingHint ? `<span>${detail.parkingHint}</span>` : ""}
        </div>
      `
    : "";
  return `
    <article class="restaurant-card ${categoryClass} ${state.focusedId === item.id ? "focused" : ""}" data-restaurant-id="${item.id}" tabindex="0" aria-label="${escapeHtml(item.name)} 지도에서 보기">
      <div class="restaurant-main">
        <div class="title-row">
          <h3>${item.name} <span class="distance-label">${distanceLabel(item)}</span></h3>
          <span class="badge">${displayCategory(item.category)}</span>
        </div>
        ${platformLinksTemplate(item)}
        <p class="restaurant-description">${restaurantDescription(item)}</p>
        <div class="score-line">
          <div><span>어플평균 <em>|</em> <strong>${pointLabel(combinedScoreLabel(item))}</strong></span></div>
          <div><span>이용점수 <em>|</em> <strong>${pointLabel(usageScore(item))}</strong></span></div>
        </div>
        <div class="restaurant-info">
          <div><span>전화번호</span><strong>${restaurantPhone(item)}</strong></div>
          <div><span>영업시간</span><strong>${restaurantHours(item)}</strong></div>
          <div><span>주소</span><strong>${shortAddress(item.address)}</strong></div>
        </div>
        ${detailBlock}
        <div class="card-actions">
          <button class="data-badge-box" type="button" data-trend="${item.id}" aria-label="${item.name} 월별 이용 추세 보기">
            <div>
              <span>월별추세</span>
            </div>
            ${usageTrendTemplate(item)}
          </button>
          <button class="action-button ${selected ? "selected" : ""}" type="button" data-compare="${item.id}">
            ${selected ? "비교함에서 빼기" : "비교함에 담기"}
          </button>
        </div>
      </div>
    </article>
  `;
}

function renderList(items) {
  mapCount.textContent = formatPlaceCount(items.length);
  listEl.innerHTML = items.length
    ? items.map(cardTemplate).join("")
    : `<p class="source-line">검색 결과가 없습니다. 전체 범례를 선택하거나 검색어를 줄여보세요.</p>`;
}

function renderCompare() {
  const items = restaurantData.filter((item) => state.compare.has(item.id));
  compareCount.textContent = String(items.length);
  clearCompareBtn.disabled = items.length === 0;

  if (!items.length) {
    compareTable.innerHTML = `<p class="source-line">비교할 식당을 최대 4곳까지 담아보세요.</p>`;
    return;
  }

  const rows = [
    ["구분", ...items.map((item) => item.name)],
    ["종류", ...items.map((item) => displayCategory(item.category))],
    ["설명", ...items.map((item) => restaurantDescription(item))],
    ["어플평균", ...items.map((item) => combinedScoreLabel(item))],
    ["이용점수", ...items.map((item) => usageScore(item))],
    ["영업시간", ...items.map((item) => restaurantHours(item))],
    ["외부출처", ...items.map((item) => item.externalDetail?.detailSource || unknownLabel)],
  ];

  compareTable.innerHTML = `
    <div class="compare-grid" style="--cols: ${items.length}">
      ${rows
        .map((row, rowIndex) =>
          row
            .map((cell, cellIndex) => {
              const klass = [rowIndex === 0 ? "header" : "", cellIndex === 0 ? "label" : ""]
                .filter(Boolean)
                .join(" ");
              if (rowIndex === 0 && cellIndex > 0) {
                const item = items[cellIndex - 1];
                return `
                  <div class="compare-cell ${klass} compare-restaurant-header">
                    <span class="compare-restaurant-name">${cell}</span>
                    <button
                      class="compare-remove-button"
                      type="button"
                      data-compare-remove="${item.id}"
                      aria-label="${item.name} 비교함에서 빼기"
                      title="비교함에서 빼기"
                    >
                      <span data-lucide="x"></span>
                    </button>
                  </div>
                `;
              }
              return `<div class="compare-cell ${klass}">${cell}</div>`;
            })
            .join("")
        )
        .join("")}
    </div>
  `;

  if (window.lucide) {
    window.lucide.createIcons();
  }
}

function syncCompareButtons() {
  listEl.querySelectorAll("[data-compare]").forEach((button) => {
    const selected = state.compare.has(button.dataset.compare);
    button.classList.toggle("selected", selected);
    button.textContent = selected ? "비교함에서 빼기" : "비교함에 담기";
  });
}

function refreshComparison() {
  syncCompareButtons();
  renderCompare();
}

function render() {
  const items = filteredRestaurants();
  renderMarkers(items);
  renderList(items);
  renderCompare();
  scheduleMapRefresh();
}

renderCategoryFilters();

document.querySelectorAll("[data-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    state.category = button.dataset.value;
    state.focusedId = null;
    syncCategoryButtons();
    render();
  });
});

searchInput.addEventListener("input", (event) => {
  state.query = event.target.value;
  state.focusedId = null;
  render();
});

sortSelect.addEventListener("change", (event) => {
  state.focusedId = null;
  state.sort = event.target.value;
  render();
});

document.querySelectorAll("[data-gate-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    beginGateNavigation(button, () => enterMode(button.dataset.gateMode));
  });
});

document.querySelectorAll("[data-gate-region]").forEach((button) => {
  button.addEventListener("click", () => {
    beginGateNavigation(button, () => enterRegion(button.dataset.gateRegion));
  });
});

rankingBtn?.addEventListener("click", openRankingPanel);
closeRankingBtn?.addEventListener("click", () => closeRankingPanel());
rankingList?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-ranking-region][data-ranking-id]");
  if (!button) return;
  enterRankedRestaurant(button.dataset.rankingRegion, button.dataset.rankingId);
});

if (inquiryRegion) {
  inquiryRegion.innerHTML = [
    '<option value="">전체 / 해당 없음</option>',
    ...(config.regions || []).map(
      (region) => `<option value="${escapeHtml(region.id)}">${escapeHtml(region.name.replace("·", ""))}</option>`,
    ),
    '<option value="bento">도시락</option>',
  ].join("");
  inquiryRegion.value = activeMode === "bento" ? "bento" : activeRegion.id;
}

inquiryBtn?.addEventListener("click", openInquiryPanel);
closeInquiryBtn?.addEventListener("click", () => closeInquiryPanel());
inquiryForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!inquiryForm.reportValidity()) return;
  inquiryStatus.textContent = "수신 메일 연결 전입니다.";
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (inquiryPanel && !inquiryPanel.hidden) {
    closeInquiryPanel();
    return;
  }
  if (rankingPanel && !rankingPanel.hidden) {
    closeRankingPanel();
    return;
  }
  if (trendPanel.classList.contains("open")) closeTrendPanel();
});

homeNavBtn?.addEventListener("click", goHome);
mainNavBtn?.addEventListener("click", () => setGateOpen(true));
backNavBtn?.addEventListener("click", () => window.history.back());
forwardNavBtn?.addEventListener("click", () => window.history.forward());

listEl.addEventListener("click", (event) => {
  const trendId = event.target.closest("[data-trend]")?.dataset.trend;
  if (trendId) {
    openTrendPanel(trendId);
    return;
  }

  const compareId = event.target.closest("[data-compare]")?.dataset.compare;

  if (compareId) {
    if (state.compare.has(compareId)) {
      state.compare.delete(compareId);
    } else if (state.compare.size < 4) {
      state.compare.add(compareId);
    } else {
      showCompareLimitNotice();
    }
    refreshComparison();
    return;
  }

  if (event.target.closest("a, button")) return;
  const card = event.target.closest("[data-restaurant-id]");
  if (card) focusRestaurant(card.dataset.restaurantId);
});

listEl.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  if (event.target.closest("a, button")) return;

  const card = event.target.closest("[data-restaurant-id]");
  if (!card) return;

  event.preventDefault();
  focusRestaurant(card.dataset.restaurantId);
});

document.querySelector("#compareToggle").addEventListener("click", () => {
  comparePanel.classList.toggle("open");
});

compareTable.addEventListener("click", (event) => {
  const removeId = event.target.closest("[data-compare-remove]")?.dataset.compareRemove;
  if (!removeId || !state.compare.delete(removeId)) return;

  refreshComparison();
  comparePanel.classList.add("open");
});

clearCompareBtn.addEventListener("click", () => {
  if (!state.compare.size) return;
  state.compare.clear();
  refreshComparison();
  comparePanel.classList.add("open");
});

document.querySelector("#closeCompare").addEventListener("click", () => {
  comparePanel.classList.remove("open");
});

document.querySelector("#closeTrend").addEventListener("click", closeTrendPanel);

noticeBtn.addEventListener("click", () => {
  noticePopover.hidden = !noticePopover.hidden;
});

document.addEventListener("click", (event) => {
  if (trendPanel.classList.contains("open") && !event.target.closest("[data-trend]")) {
    closeTrendPanel();
  }

  if (!noticePopover.hidden && !noticeBtn.contains(event.target)) {
    noticePopover.hidden = true;
  }
});

if (window.lucide) {
  window.lucide.createIcons();
}

render();
if (state.focusedId) {
  window.requestAnimationFrame(() => moveMapToRestaurant(state.focusedId));
}
