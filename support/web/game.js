(function bootstrapWorldforge() {
  const stateNode = document.getElementById("worldforge-data");
  if (!stateNode) return;

  let config = {};
  try {
    config = JSON.parse(stateNode.textContent || "{}");
  } catch (error) {
    // eslint-disable-next-line no-console
    console.error("[worldforge] invalid bootstrap payload", error);
    return;
  }

  const refs = {
    coordLabel: document.getElementById("coordLabel"),
    entropyLabel: document.getElementById("entropyLabel"),
    zoneSeed: document.getElementById("zoneSeed"),
    statusLine: document.getElementById("statusLine"),
    visualTheme: document.getElementById("visualTheme"),
    narrativeText: document.getElementById("narrativeText"),
    physicalRule: document.getElementById("physicalRule"),
    devTask: document.getElementById("devTask"),
    lawList: document.getElementById("lawList"),
    canonZone: document.getElementById("canonZone"),
    canonBtn: document.getElementById("canonBtn"),
    canonModal: document.getElementById("canonModal"),
    canonClose: document.getElementById("canonClose"),
    canonInvoice: document.getElementById("canonInvoice"),
    canonCheck: document.getElementById("canonCheck"),
    orbitBanner: document.getElementById("orbitBanner"),
    orbitText: document.getElementById("orbitText"),
  };

  const world = {
    map: null,
    current: null,
    obeliskMarker: null,
    canonInvoiceId: "",
    canonPollTimer: null,
    orbitPoints: [],
    starsMode: false,
  };

  const entropyWarn = Number(config.entropyWarn || 0.8);
  const entropyMutate = Number(config.entropyMutate || 0.9);
  const spaceZoomGate = Number(config.spaceZoomGate || 3);
  const earthStyle = String(config.earthStyle || "mapbox://styles/mapbox/satellite-v9");
  const starStyle = String(config.starStyle || "mapbox://styles/mapbox/dark-v11");
  const i18n = config.i18n && typeof config.i18n === "object" ? config.i18n : {};

  function t(key, fallback) {
    const value = i18n[key];
    return value == null ? String(fallback || "") : String(value);
  }

  function setStatus(message, tone = "normal") {
    if (!refs.statusLine) return;
    refs.statusLine.textContent = String(message || "");
    refs.statusLine.classList.remove("text-emerald-300", "text-amber-300", "text-rose-300");
    if (tone === "ok") refs.statusLine.classList.add("text-emerald-300");
    else if (tone === "warn") refs.statusLine.classList.add("text-amber-300");
    else if (tone === "err") refs.statusLine.classList.add("text-rose-300");
  }

  function formatCoord(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(6) : "0.000000";
  }

  function updateCoordLabel(lat, lng) {
    if (!refs.coordLabel) return;
    refs.coordLabel.textContent = `${formatCoord(lat)}, ${formatCoord(lng)}`;
  }

  function applyEntropyStyle(entropy) {
    if (!refs.entropyLabel) return;
    refs.entropyLabel.classList.remove("entropy-low", "entropy-mid", "entropy-high");
    if (entropy >= entropyWarn) refs.entropyLabel.classList.add("entropy-high");
    else if (entropy >= 0.45) refs.entropyLabel.classList.add("entropy-mid");
    else refs.entropyLabel.classList.add("entropy-low");
  }

  function setEntropy(entropy) {
    if (!refs.entropyLabel) return;
    refs.entropyLabel.textContent = Number(entropy || 0).toFixed(3);
    applyEntropyStyle(Number(entropy || 0));
  }

  function renderLaws(laws) {
    if (!refs.lawList) return;
    const list = Array.isArray(laws) ? laws.filter(Boolean).slice(0, 4) : [];
    if (!list.length) {
      refs.lawList.innerHTML = `<li class="law-card rounded-md p-3 text-sm text-zinc-300">${escapeHtml(t("no_law", "No law generated yet."))}</li>`;
      return;
    }
    refs.lawList.innerHTML = list
      .map((law) => `<li class="law-card rounded-md p-3 text-sm text-zinc-200">${escapeHtml(String(law))}</li>`)
      .join("");
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function setCanonVisible(show) {
    if (!refs.canonZone) return;
    refs.canonZone.classList.toggle("hidden", !show);
  }

  function setCanonModalVisible(show) {
    if (!refs.canonModal) return;
    refs.canonModal.classList.toggle("hidden", !show);
  }

  function placeObelisk(lat, lng, show) {
    if (!world.map) return;
    if (!show) {
      if (world.obeliskMarker) {
        world.obeliskMarker.remove();
        world.obeliskMarker = null;
      }
      return;
    }
    if (!world.obeliskMarker) {
      const el = document.createElement("div");
      el.className = "obelisk-marker";
      world.obeliskMarker = new mapboxgl.Marker({ element: el, anchor: "bottom" });
    }
    world.obeliskMarker.setLngLat([lng, lat]).addTo(world.map);
  }

  function renderGenesis(payload) {
    world.current = payload;
    const lat = Number(payload?.lat || 0);
    const lng = Number(payload?.lng || 0);
    updateCoordLabel(lat, lng);
    setEntropy(Number(payload?.entropy || 0));
    if (refs.zoneSeed) refs.zoneSeed.textContent = String(payload?.seed_hash || "").slice(0, 16) || "-";
    if (refs.visualTheme) refs.visualTheme.textContent = String(payload?.rules?.visual_theme || "-");
    if (refs.narrativeText) refs.narrativeText.textContent = String(payload?.rules?.narrative || "-");
    if (refs.physicalRule) refs.physicalRule.textContent = String(payload?.rules?.physical_rule || "-");
    if (refs.devTask) refs.devTask.textContent = String(payload?.rules?.dev_task || "-");
    renderLaws(payload?.rules?.heavenly_laws || []);
    const entropy = Number(payload?.entropy || 0);
    const warn = entropy > entropyWarn;
    setCanonVisible(warn && !payload?.is_fixed);
    placeObelisk(lat, lng, Boolean(payload?.is_fixed));

    if (payload?.is_fixed) {
      setStatus(`${t("status_fixed_until", "Zone is canonized until")} ${payload?.fixed_until || t("unknown", "unknown")}`, "ok");
    } else if (entropy >= entropyMutate) {
      setStatus(t("status_mutation_threshold", "Zone reached mutation threshold. Rules are unstable."), "warn");
    } else if (entropy >= entropyWarn) {
      setStatus(t("status_collapse_warning", "Reality collapse warning. Canonization recommended."), "warn");
    } else {
      setStatus(t("status_zone_synced", "Zone synchronized."), "ok");
    }
  }

  async function fetchJson(url, init) {
    const res = await fetch(url, init);
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload?.ok === false) {
      const err = String(payload?.error || `HTTP_${res.status}`);
      throw new Error(err);
    }
    return payload;
  }

  async function loadGenesis(lat, lng) {
    setStatus(t("status_forging", "Forging local law..."), "warn");
    const query = `lat=${encodeURIComponent(String(lat))}&lng=${encodeURIComponent(String(lng))}`;
    const payload = await fetchJson(`/api/genesis?${query}`, { method: "GET", cache: "no-store" });
    renderGenesis(payload);
    return payload;
  }

  async function createCanonInvoice() {
    if (!world.current?.seed_hash) return;
    const payload = await fetchJson("/api/canonize/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        seed_hash: world.current.seed_hash,
        lat: world.current.lat,
        lng: world.current.lng,
        payment_rail: "l2_usdc",
      }),
    });
    world.canonInvoiceId = String(payload?.invoice_id || "");
    if (refs.canonInvoice) {
      refs.canonInvoice.innerHTML = [
        `${escapeHtml(t("invoice_label", "Invoice"))}: <b>${escapeHtml(world.canonInvoiceId)}</b>`,
        `${escapeHtml(t("transfer_label", "Transfer"))}: <b>${Number(payload?.amount_usdt || 0).toFixed(2)} USDT</b>`,
        `${escapeHtml(t("to_label", "To"))}: <code>${escapeHtml(payload?.pay_to_address || "-")}</code>`,
      ].join("<br>");
    }
    setCanonModalVisible(true);
    setStatus(t("status_invoice_created", "Invoice created. Waiting on-chain confirmation..."), "warn");
    startCanonPolling();
  }

  async function checkCanonStatus() {
    if (!world.canonInvoiceId || !world.current?.seed_hash) return;
    const query = `invoice_id=${encodeURIComponent(world.canonInvoiceId)}&seed_hash=${encodeURIComponent(world.current.seed_hash)}`;
    const payload = await fetchJson(`/api/canonize/confirm?${query}`, { method: "GET", cache: "no-store" });
    if (payload?.fixed) {
      stopCanonPolling();
      setCanonModalVisible(false);
      setStatus(t("status_canon_complete", "Canonization complete. Mutation locked for 24h."), "ok");
      await loadGenesis(world.current.lat, world.current.lng);
    }
  }

  function startCanonPolling() {
    stopCanonPolling();
    world.canonPollTimer = window.setInterval(() => {
      void checkCanonStatus().catch((error) => {
        setStatus(`${t("status_canon_poll_failed", "Canonization polling failed")}: ${String(error?.message || error)}`, "err");
      });
    }, 6000);
  }

  function stopCanonPolling() {
    if (!world.canonPollTimer) return;
    window.clearInterval(world.canonPollTimer);
    world.canonPollTimer = null;
  }

  function ensureOrbitLayer(points) {
    if (!world.map || !Array.isArray(points) || !points.length) return;
    const coords = points.map((p) => [Number(p.lng || 0), Number(p.lat || 0)]);
    const feature = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "LineString", coordinates: coords },
          properties: {},
        },
      ],
    };
    const sourceId = "worldforge-orbit";
    const layerId = "worldforge-orbit-line";
    if (world.map.getSource(sourceId)) {
      world.map.getSource(sourceId).setData(feature);
      return;
    }
    world.map.addSource(sourceId, { type: "geojson", data: feature });
    world.map.addLayer({
      id: layerId,
      type: "line",
      source: sourceId,
      paint: {
        "line-color": "#8ad6ff",
        "line-opacity": 0.85,
        "line-width": 2.4,
      },
    });
  }

  async function checkSpaceUnlock() {
    if (!world.map) return;
    const center = world.map.getCenter();
    const zoom = world.map.getZoom();
    const query = `lat=${encodeURIComponent(String(center.lat))}&lng=${encodeURIComponent(String(center.lng))}&zoom=${encodeURIComponent(String(zoom))}`;
    const payload = await fetchJson(`/api/space?${query}`, { method: "GET", cache: "no-store" });
    world.orbitPoints = payload?.orbit_points || [];
    if (refs.orbitBanner) refs.orbitBanner.classList.toggle("hidden", !payload?.unlocked);
    if (refs.orbitText) {
      refs.orbitText.textContent = payload?.unlocked
        ? `${t("orbit_opened", "Semantic orbit opened")}: ${String(payload.target || t("unknown", "unknown")).toUpperCase()} | ${t("global_dev", "Global dev")}: ${Number(payload.global_developments || 0)}`
        : `${t("space_locked_need", "Space locked. Need")} ${Number(payload.required || 0)} ${t("global_dev_count", "global developments")} (${t("current", "current")} ${Number(payload.global_developments || 0)}).`;
    }
    if (payload?.unlocked && zoom < spaceZoomGate && !world.starsMode) {
      world.starsMode = true;
      world.map.setStyle(starStyle);
      return;
    }
    if (zoom >= spaceZoomGate && world.starsMode) {
      world.starsMode = false;
      world.map.setStyle(earthStyle);
      return;
    }
    ensureOrbitLayer(world.orbitPoints);
  }

  function configureTerrain() {
    if (!world.map) return;
    if (!world.map.getSource("mapbox-dem")) {
      world.map.addSource("mapbox-dem", {
        type: "raster-dem",
        url: "mapbox://mapbox.terrain-rgb",
        tileSize: 512,
        maxzoom: 14,
      });
    }
    world.map.setTerrain({ source: "mapbox-dem", exaggeration: 1.3 });
    world.map.setFog({
      color: "rgb(12, 12, 24)",
      "high-color": "rgb(28, 16, 49)",
      "horizon-blend": 0.18,
      "space-color": "rgb(2, 2, 8)",
      "star-intensity": 0.65,
    });
    ensureOrbitLayer(world.orbitPoints);
  }

  async function initMap() {
    const token = String(config.mapboxToken || "");
    if (!token || !window.mapboxgl) {
      setStatus(t("status_missing_mapbox", "Mapbox token is missing. Set MAPBOX_PUBLIC_TOKEN."), "err");
      return;
    }
    mapboxgl.accessToken = token;
    world.map = new mapboxgl.Map({
      container: "worldMap",
      style: earthStyle,
      center: [Number(config.defaultLng || 121.5654), Number(config.defaultLat || 25.033)],
      zoom: Number(config.defaultZoom || 11.8),
      pitch: 62,
      bearing: -18,
      antialias: true,
      projection: "globe",
    });
    world.map.addControl(new mapboxgl.NavigationControl({ visualizePitch: true }), "bottom-right");

    world.map.on("style.load", () => {
      configureTerrain();
      void checkSpaceUnlock().catch(() => {});
    });

    world.map.on("mousemove", (event) => {
      updateCoordLabel(event.lngLat.lat, event.lngLat.lng);
    });

    world.map.on("click", (event) => {
      void loadGenesis(event.lngLat.lat, event.lngLat.lng).catch((error) => {
        setStatus(`${t("status_genesis_failed", "Genesis failed")}: ${String(error?.message || error)}`, "err");
      });
    });

    world.map.on("zoomend", () => {
      void checkSpaceUnlock().catch(() => {});
    });

    const center = world.map.getCenter();
    updateCoordLabel(center.lat, center.lng);
    await loadGenesis(center.lat, center.lng);
  }

  refs.canonBtn?.addEventListener("click", () => {
    void createCanonInvoice().catch((error) => {
      setStatus(`${t("status_canon_invoice_failed", "Canonization invoice failed")}: ${String(error?.message || error)}`, "err");
    });
  });

  refs.canonCheck?.addEventListener("click", () => {
    void checkCanonStatus().catch((error) => {
      setStatus(`${t("status_check_failed", "Status check failed")}: ${String(error?.message || error)}`, "err");
    });
  });

  refs.canonClose?.addEventListener("click", () => setCanonModalVisible(false));

  window.addEventListener("beforeunload", () => {
    stopCanonPolling();
  });

  void initMap().catch((error) => {
    setStatus(`${t("status_map_init_failed", "Map init failed")}: ${String(error?.message || error)}`, "err");
  });
})();
