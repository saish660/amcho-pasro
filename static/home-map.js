(function () {
  const mapEl = document.getElementById("home-stores-map");
  if (!mapEl || !window.L) return;

  let stores = [];
  try {
    const raw = mapEl.dataset.stores || "[]";
    stores = JSON.parse(raw);
  } catch (err) {
    console.warn("Failed to parse homepage stores dataset", err);
    stores = [];
  }

  const normalizedStores = stores
    .map((store) => ({
      id: store.id,
      name: store.name || "Store",
      city: store.city || "",
      location: store.location || "",
      image: store.image || "",
      lat: typeof store.lat === "string" ? parseFloat(store.lat) : store.lat,
      lng: typeof store.lng === "string" ? parseFloat(store.lng) : store.lng,
    }))
    .filter(
      (store) => Number.isFinite(store.lat) && Number.isFinite(store.lng)
    );

  function escapeAttr(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function buildStoreIcon(store) {
    const initial = (store.name || "S").trim().charAt(0).toUpperCase() || "S";
    const hasImage = Boolean(store.image);
    const photoHtml = hasImage
      ? `<img src="${escapeAttr(store.image)}" alt="${escapeAttr(
          store.name
        )} thumbnail" loading="lazy" />`
      : `<span>${initial}</span>`;
    const extraClass = hasImage ? " map-pin__inner--photo" : "";
    return L.divIcon({
      className: "map-pin leaflet-div-icon",
      html: `<div class="map-pin__inner${extraClass}">${photoHtml}</div>`,
      iconSize: [34, 44],
      iconAnchor: [17, 44],
      popupAnchor: [0, -42],
    });
  }

  const GOA_CENTER = [15.399, 73.974];
  const DEFAULT_ZOOM = 9;

  const map = L.map(mapEl, {
    zoomControl: true,
    scrollWheelZoom: false,
    worldCopyJump: false,
  }).setView(GOA_CENTER, DEFAULT_ZOOM);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  mapEl.addEventListener("focus", () => map.scrollWheelZoom.enable());
  mapEl.addEventListener("blur", () => map.scrollWheelZoom.disable());

  if (!normalizedStores.length) {
    const emptyState = document.createElement("div");
    emptyState.className = "goa-map__empty";
    emptyState.textContent =
      "Stores with geocoded locations will appear here soon.";
    mapEl.appendChild(emptyState);
    return;
  }

  const bounds = [];
  normalizedStores.forEach((store) => {
    const marker = L.marker([store.lat, store.lng], {
      icon: buildStoreIcon(store),
    }).addTo(map);
    const labelLocation = [store.location, store.city]
      .filter(Boolean)
      .join(", ");
    const popupHtml = `
      <div class="home-map-popup">
        <strong>${store.name}</strong><br />
        ${labelLocation || "Goa"}<br />
        <a href="/store/${
          store.id
        }" target="_blank" rel="noopener">Open store page</a>
      </div>
    `;
    marker.bindPopup(popupHtml.trim());
    bounds.push([store.lat, store.lng]);
  });

  if (bounds.length > 1) {
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: 15 });
  } else {
    map.setView(bounds[0], 13);
  }
})();
