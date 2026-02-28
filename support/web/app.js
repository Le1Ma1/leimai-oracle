(function bootstrap() {
  const initialNode = document.getElementById("initial-data");
  if (!initialNode) return;

  let state = {};
  try {
    state = JSON.parse(initialNode.textContent || "{}");
  } catch (error) {
    // eslint-disable-next-line no-console
    console.error("[support-ui] invalid initial state", error);
    state = {};
  }

  const content = state.content || {};
  const locale = state.locale || "en";
  const supportAddress = String(state.supportAddress || "");

  const leaderboardBody = document.getElementById("leaderboardBody");
  const kingBlock = document.getElementById("kingBlock");
  const adsList = document.getElementById("adsList");
  const copyBtn = document.getElementById("copyAddressBtn");
  const qrCode = document.getElementById("qrCode");
  const declarationForm = document.getElementById("declarationForm");
  const declarationResult = document.getElementById("declarationResult");
  const statusInput = document.getElementById("statusIdInput");
  const statusBtn = document.getElementById("statusCheckBtn");
  const statusResult = document.getElementById("statusResult");
  const throneEvent = document.getElementById("throneEvent");
  const lastRefresh = document.getElementById("lastRefresh");
  const refreshCountdown = document.getElementById("refreshCountdown");

  let currentKingTxHash = normalizeTx(state.king?.tx_hash || "");
  let nextLeaderboardPollAt = Date.now() + 30_000;

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function normalizeTx(value) {
    return String(value || "").trim().toLowerCase();
  }

  function shortHash(value) {
    const hash = String(value || "");
    if (!hash) return "-";
    if (hash.length <= 14) return hash;
    return `${hash.slice(0, 8)}...${hash.slice(-6)}`;
  }

  function formatMoney(v) {
    const n = Number(v || 0);
    if (!Number.isFinite(n)) return "0.00";
    return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function setResult(node, text, ok) {
    if (!node) return;
    node.textContent = text;
    node.classList.remove("ok", "err");
    node.classList.add(ok ? "ok" : "err");
  }

  function setThroneEvent(text, mode = "ok") {
    if (!throneEvent) return;
    throneEvent.textContent = text;
    throneEvent.classList.remove("mode-ok", "mode-alert", "mode-err");
    if (mode === "alert") throneEvent.classList.add("mode-alert");
    else if (mode === "err") throneEvent.classList.add("mode-err");
    else throneEvent.classList.add("mode-ok");
  }

  function setLastRefreshLabel(ts) {
    if (!lastRefresh) return;
    lastRefresh.textContent = ts || new Date().toISOString();
  }

  function renderKing(king) {
    if (!kingBlock) return;
    if (!king) {
      kingBlock.innerHTML = `<div class="king-empty">${escapeHtml(content.noKing || "No king yet.")}</div>`;
      return;
    }
    kingBlock.innerHTML = `
      <div class="king-amount">${formatMoney(king.amount_usdt)} <span>USDT</span></div>
      <div class="king-meta">${escapeHtml(content.walletLabel || "Wallet")}: ${escapeHtml(king.wallet_masked || "-")}</div>
      <div class="king-meta">${escapeHtml(content.timeLabel || "Time")}: ${escapeHtml(king.confirmed_at_utc || "-")}</div>
      <div class="king-meta">${escapeHtml(content.txLabel || "Tx")}: ${escapeHtml(shortHash(king.tx_hash || "-"))}</div>
    `;
  }

  function rankClass(rank) {
    if (rank === 1) return "rank-top";
    if (rank <= 3) return "rank-high";
    return "rank-normal";
  }

  function renderLeaderboard(rows) {
    if (!leaderboardBody) return;
    const items = Array.isArray(rows) ? rows.slice(0, 10) : [];
    if (!items.length) {
      leaderboardBody.innerHTML = `
        <tr>
          <td colspan="4" class="table-empty">${escapeHtml(content.noKing || "No data yet.")}</td>
        </tr>
      `;
      return;
    }
    leaderboardBody.innerHTML = items
      .map((row) => {
        const rank = Number(row.rank || 0);
        return `
          <tr>
            <td><span class="rank-chip ${rankClass(rank)}">#${rank}</span></td>
            <td>${escapeHtml(row.wallet_masked || "-")}</td>
            <td class="amount-cell">${formatMoney(row.amount_usdt)} USDT</td>
            <td>${escapeHtml(row.confirmed_at_utc || "-")}</td>
          </tr>
        `;
      })
      .join("");
  }

  function renderAds(rows) {
    if (!adsList) return;
    const ads = Array.isArray(rows) ? rows : [];
    if (!ads.length) {
      adsList.innerHTML = `<li class="ad-empty">${escapeHtml(content.noAds || "No approved ads yet.")}</li>`;
      return;
    }
    adsList.innerHTML = ads
      .map(
        (row) => `
      <li class="ad-item">
        <div class="ad-wallet">${escapeHtml(row.wallet_masked || "-")}</div>
        <div class="ad-content">${escapeHtml(row.content || "-")}</div>
      </li>
    `,
      )
      .join("");
  }

  async function loadLeaderboard() {
    try {
      const res = await fetch(`/api/v1/leaderboard?lang=${encodeURIComponent(locale)}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP_${res.status}`);
      const payload = await res.json();
      if (!payload.ok) throw new Error(payload.error || "unknown_error");
      renderKing(payload.king || null);
      renderLeaderboard(payload.rows || []);

      const newKingTxHash = normalizeTx(payload.king?.tx_hash || "");
      if (newKingTxHash && currentKingTxHash && newKingTxHash !== currentKingTxHash) {
        setThroneEvent(`${content.throneReplacedText || "THRONE REPLACED"} | ${shortHash(newKingTxHash)}`, "alert");
      } else {
        setThroneEvent(content.liveSyncText || "Dual-source sync active.", "ok");
      }
      if (newKingTxHash) {
        currentKingTxHash = newKingTxHash;
      }
      setLastRefreshLabel(payload.generated_at_utc || new Date().toISOString());
      nextLeaderboardPollAt = Date.now() + 30_000;
    } catch (error) {
      setThroneEvent(`${content.loadErrorText || "Live update interrupted"} | ${String(error?.message || error)}`, "err");
      // eslint-disable-next-line no-console
      console.error("[support-ui] leaderboard load error", error);
    }
  }

  async function loadAds() {
    try {
      const res = await fetch("/api/v1/ads/slots", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP_${res.status}`);
      const payload = await res.json();
      if (!payload.ok) throw new Error(payload.error || "unknown_error");
      renderAds(payload.rows || []);
    } catch (error) {
      // eslint-disable-next-line no-console
      console.error("[support-ui] ads load error", error);
    }
  }

  async function submitDeclaration(evt) {
    evt.preventDefault();
    if (!declarationForm) return;
    const formData = new FormData(declarationForm);
    const body = {
      tx_hash: String(formData.get("tx_hash") || "").trim(),
      wallet: String(formData.get("wallet") || "").trim(),
      lang: String(formData.get("lang") || locale).trim().toLowerCase(),
      type: String(formData.get("type") || "personal").trim().toLowerCase(),
      content: String(formData.get("content") || "").trim(),
    };

    try {
      const res = await fetch("/api/v1/declarations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok || !payload.ok) {
        throw new Error(payload.error || `HTTP_${res.status}`);
      }
      setResult(
        declarationResult,
        `${content.pendingText || "Pending"} | ID: ${payload.declaration_id}`,
        true,
      );
      declarationForm.reset();
      await loadAds();
    } catch (error) {
      setResult(declarationResult, String(error?.message || error), false);
    }
  }

  async function checkDeclarationStatus() {
    const id = String(statusInput?.value || "").trim();
    if (!id) {
      setResult(statusResult, "missing_declaration_id", false);
      return;
    }
    try {
      const res = await fetch(`/api/v1/declarations/${encodeURIComponent(id)}/status?lang=${encodeURIComponent(locale)}`, {
        cache: "no-store",
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok || !payload.ok) throw new Error(payload.error || `HTTP_${res.status}`);
      const msg = payload.note
        ? `${payload.status_label} | ${payload.note}`
        : `${payload.status_label}`;
      setResult(statusResult, msg, payload.status !== "rejected");
    } catch (error) {
      setResult(statusResult, String(error?.message || error), false);
    }
  }

  function updateCountdown() {
    if (!refreshCountdown) return;
    const remainMs = Math.max(0, nextLeaderboardPollAt - Date.now());
    const sec = Math.ceil(remainMs / 1000);
    refreshCountdown.textContent = `${sec}s`;
  }

  copyBtn?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(supportAddress);
      copyBtn.textContent = content.copied || "Copied";
      setTimeout(() => {
        copyBtn.textContent = content.copyAddress || "Copy";
      }, 1200);
    } catch {
      copyBtn.textContent = content.copyFailed || "Copy failed";
      setTimeout(() => {
        copyBtn.textContent = content.copyAddress || "Copy";
      }, 1500);
    }
  });

  declarationForm?.addEventListener("submit", submitDeclaration);
  statusBtn?.addEventListener("click", checkDeclarationStatus);

  if (supportAddress && qrCode) {
    qrCode.src = `https://api.qrserver.com/v1/create-qr-code/?size=220x220&margin=0&data=${encodeURIComponent(supportAddress)}`;
  }

  renderKing(state.king || null);
  renderLeaderboard(state.leaderboard || []);
  renderAds(state.ads || []);
  setLastRefreshLabel(new Date().toISOString());
  setThroneEvent(content.liveSyncText || "Dual-source sync active.", "ok");
  updateCountdown();

  loadLeaderboard();
  loadAds();
  setInterval(loadLeaderboard, 30_000);
  setInterval(loadAds, 45_000);
  setInterval(updateCountdown, 1000);
})();
