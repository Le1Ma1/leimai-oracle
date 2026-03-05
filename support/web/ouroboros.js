(() => {
  const WEALTH_HUBS = new Set([
    "Asia/Singapore",
    "Asia/Dubai",
    "Europe/Zurich",
    "America/New_York",
    "Europe/Monaco",
  ]);

  const COPY = {
    en: {
      negotiating: "Negotiating Secure Enclave...",
      walletMissing: "Wallet not found. Please install a Web3 wallet.",
      unlockReload: "Access verified. Reloading full intelligence...",
      waitingSync: "Waiting for Model Synced",
      signRejected: "Signature rejected by wallet.",
      unlockNotConfigured: "Unlock service is not configured.",
      invalidSignature: "Invalid signature. Please retry.",
      challengeExpired: "Challenge expired. Please retry.",
      mismatch: "Address mismatch detected.",
      rateLimited: "Too many attempts. Please wait.",
      unlockFailed: "Access verification failed. Please retry.",
      accessGranted: "Access Granted: Synchronizing Sovereign Signals",
      invoiceExpired: "Request expired. Please generate a new authorization request.",
      waitingSettlement: "Awaiting settlement confirmation...",
      invoiceNotFound: "Authorization request not found. Please generate a new one.",
      sessionMismatch: "Session expired or wallet mismatch. Please sign again.",
      polling: "Monitoring settlement status...",
      creatingInvoice: "Preparing sovereign settlement request...",
      invoiceReady: "Request ready. Complete settlement before expiration.",
      unlockRequired: "Signed session required before creating request.",
      paymentCreateFailed: "Failed to prepare settlement request. Please retry.",
      walletGuideTitle: "Sovereign Access Required",
      walletGuideBody:
        "To verify your identity and unlock Alpha intelligence, a Web3 Vault Key is required.",
      walletGuideInstall: "Install MetaMask",
      walletGuideLearn: "Learn More",
      walletGuideClose: "Continue in Preview",
      guidedGatewayTitle: "Obsidian Guided Modal",
      guidedGatewayBody:
        "Connect your hardware-backed wallet, then route settlement to the Oracle Vault over ERC20 or Arbitrum.",
      guidedConnect: "[ CONNECT METAMASK ]",
      guidedGenerate: "[ GENERATE SETTLEMENT REQUEST ]",
      guidedCopyErc20: "[ COPY ERC20 ADDRESS ]",
      guidedCopyArbitrum: "[ COPY ARBITRUM ADDRESS ]",
      guidedSendTx: "[ WEB3 SENDTRANSACTION ]",
      guidedClose: "[ CLOSE ]",
      guidedCopied: "Vault address copied.",
      guidedNoWallet: "Wallet unavailable. Install MetaMask first.",
      guidedNeedSignature: "Please sign the sovereign session before requesting settlement.",
      guidedTxSubmitted: "Transaction submitted",
      guidedTxFailed: "Transaction prompt failed. Use manual transfer.",
      guidedPreparing: "Preparing guided settlement...",
    },
    "zh-tw": {
      negotiating: "安全飛地協商中...",
      walletMissing: "找不到錢包，請安裝 Web3 錢包。",
      unlockReload: "驗證完成，正在載入完整情報...",
      waitingSync: "等待模型同步",
      signRejected: "簽署已被錢包拒絕。",
      unlockNotConfigured: "解鎖服務尚未配置完成。",
      invalidSignature: "簽章無效，請重試。",
      challengeExpired: "挑戰已過期，請重試。",
      mismatch: "偵測到地址不一致。",
      rateLimited: "嘗試次數過多，請稍後再試。",
      unlockFailed: "權限驗證失敗，請重試。",
      accessGranted: "權限通過：主權訊號同步中",
      invoiceExpired: "請求已過期，請重新建立授權請求。",
      waitingSettlement: "等待結算確認...",
      invoiceNotFound: "查無授權請求，請重新建立。",
      sessionMismatch: "會話過期或地址不一致，請重新簽署。",
      polling: "持續監控結算狀態...",
      creatingInvoice: "建立主權結算請求中...",
      invoiceReady: "請求已建立，請在過期前完成結算。",
      unlockRequired: "請先完成簽署再建立請求。",
      paymentCreateFailed: "建立結算請求失敗，請重試。",
      walletGuideTitle: "需要主權金鑰",
      walletGuideBody:
        "為了完成身份驗證並解鎖完整 Alpha 情報，需要先安裝 Web3 錢包金鑰。",
      walletGuideInstall: "安裝 MetaMask",
      walletGuideLearn: "了解流程",
      walletGuideClose: "先維持預覽",
      guidedGatewayTitle: "Obsidian 主權引導",
      guidedGatewayBody: "請先連接硬體錢包，再透過 ERC20 或 Arbitrum 對 Oracle Vault 完成結算。",
      guidedConnect: "[ 連接 METAMASK ]",
      guidedGenerate: "[ 建立結算請求 ]",
      guidedCopyErc20: "[ 複製 ERC20 地址 ]",
      guidedCopyArbitrum: "[ 複製 ARBITRUM 地址 ]",
      guidedSendTx: "[ WEB3 SENDTRANSACTION ]",
      guidedClose: "[ 關閉 ]",
      guidedCopied: "已複製金庫地址。",
      guidedNoWallet: "尚未偵測到錢包，請先安裝 MetaMask。",
      guidedNeedSignature: "請先完成主權簽署，再建立結算請求。",
      guidedTxSubmitted: "交易已送出",
      guidedTxFailed: "交易提示失敗，請改用手動轉帳。",
      guidedPreparing: "正在準備主權結算流程...",
    },
  };

  function getLocaleCopy() {
    const locale = String(document.body?.getAttribute("data-locale") || "en").toLowerCase();
    return COPY[locale] || COPY.en;
  }

  function getActiveLocale() {
    const locale = String(document.body?.getAttribute("data-locale") || "en").toLowerCase();
    return locale === "zh-tw" ? "zh-tw" : "en";
  }

  function setLocaleCookie(locale) {
    const safe = String(locale || "en").toLowerCase() === "zh-tw" ? "zh-tw" : "en";
    document.cookie = `ouroboros_locale=${encodeURIComponent(safe)}; Path=/; Max-Age=31536000; SameSite=Lax`;
  }

  function bindLocaleSwitcher() {
    const links = Array.from(document.querySelectorAll("[data-locale-switch]"));
    if (links.length === 0) return;
    for (const link of links) {
      link.addEventListener("click", (event) => {
        const targetLocale = String(link.getAttribute("data-locale-switch") || "").toLowerCase();
        if (!targetLocale) return;
        setLocaleCookie(targetLocale);
        const href = String(link.getAttribute("href") || "").trim();
        if (!href) return;
        event.preventDefault();
        const nextUrl = `${href}${window.location.search || ""}${window.location.hash || ""}`;
        window.location.assign(nextUrl);
      });
    }
  }

  const ERC20_TOKEN_CONTRACT = {
    eth_l1_erc20: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606EB48",
    l2_usdc: "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
  };

  const CHAIN_ID_BY_RAIL = {
    eth_l1_erc20: "0x1",
    l2_usdc: "0xa4b1",
  };

  function normalizePaymentRail(raw) {
    const value = String(raw || "l2_usdc").trim().toLowerCase();
    if (value === "eth_l1_erc20" || value === "l2_usdc") return value;
    return "l2_usdc";
  }

  function leftPad64(hex) {
    return String(hex || "").replace(/^0x/i, "").padStart(64, "0");
  }

  function encodeErc20TransferData(toAddress, amountUnits) {
    const selector = "a9059cbb";
    const toField = leftPad64(String(toAddress || "").replace(/^0x/i, "").toLowerCase());
    const valueField = leftPad64(BigInt(amountUnits).toString(16));
    return `0x${selector}${toField}${valueField}`;
  }

  function parseUsdcToUnits(amountRaw) {
    const amount = Number.parseFloat(String(amountRaw || "0"));
    if (!Number.isFinite(amount) || amount <= 0) return 0n;
    return BigInt(Math.round(amount * 1_000_000));
  }

  async function ensureWalletChain(ethereum, rail) {
    const target = CHAIN_ID_BY_RAIL[normalizePaymentRail(rail)];
    if (!target) return;
    try {
      await ethereum.request({
        method: "wallet_switchEthereumChain",
        params: [{ chainId: target }],
      });
    } catch {
      // keep current chain and let wallet handle rejection downstream
    }
  }

  function hexToRgb01(hex) {
    const cleaned = String(hex || "").replace("#", "").trim();
    if (!/^[0-9a-fA-F]{6}$/.test(cleaned)) return [0.75, 0.75, 0.75];
    const num = Number.parseInt(cleaned, 16);
    return [
      ((num >> 16) & 255) / 255,
      ((num >> 8) & 255) / 255,
      (num & 255) / 255,
    ];
  }

  function getLuxuryConfig() {
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "Etc/UTC";
      const isElite = WEALTH_HUBS.has(tz);
      const accent = isElite ? "#D4AF37" : "#C0C0C0";
      const shadow = isElite ? "rgba(212,175,55,0.22)" : "rgba(192,192,192,0.22)";
      const hub = String(tz).split("/").slice(-1)[0] || "Global";
      return { tz, isElite, accent, shadow, hub };
    } catch {
      return {
        tz: "Etc/UTC",
        isElite: false,
        accent: "#C0C0C0",
        shadow: "rgba(192,192,192,0.22)",
        hub: "Global",
      };
    }
  }

  function applyLuxuryTheme(config) {
    const root = document.documentElement;
    const rgb = hexToRgb01(config.accent).map((v) => Math.round(v * 255));
    root.style.setProperty("--accent", config.accent);
    root.style.setProperty("--accent-rgb", `${rgb[0]}, ${rgb[1]}, ${rgb[2]}`);
    root.style.setProperty("--accent-shadow", config.shadow);

    if (config.isElite) {
      document.body.classList.add("elite-hub");
    } else {
      document.body.classList.remove("elite-hub");
    }

    const hubNode = document.getElementById("geoHub");
    const tierNode = document.getElementById("geoTier");
    if (hubNode) hubNode.textContent = config.hub;
    if (tierNode) tierNode.textContent = config.isElite ? "24K Gold Node" : "Platinum Node";
  }

  function formatUtcNodes() {
    const nodes = Array.from(document.querySelectorAll("[data-utc]"));
    for (const node of nodes) {
      const iso = String(node.getAttribute("data-utc") || "").trim();
      if (!iso) continue;
      const ts = Date.parse(iso);
      if (!Number.isFinite(ts)) continue;
      node.textContent =
        new Intl.DateTimeFormat("en-GB", {
          dateStyle: "medium",
          timeStyle: "short",
          hour12: false,
          timeZone: "UTC",
        }).format(new Date(ts)) + " UTC";
    }
  }

  function bindSearch() {
    const searchInput = document.getElementById("analysisSearch");
    const cardsWrap = document.getElementById("analysisCards");
    if (!searchInput || !cardsWrap) return;

    const cards = Array.from(cardsWrap.querySelectorAll(".matrix-card"));
    const applyFilter = () => {
      const q = String(searchInput.value || "").trim().toLowerCase();
      let visible = 0;
      for (const card of cards) {
        const hay = String(card.getAttribute("data-filter") || "").toLowerCase();
        const show = !q || hay.includes(q);
        card.style.display = show ? "" : "none";
        if (show) visible += 1;
      }
      cardsWrap.setAttribute("data-visible-count", String(visible));
    };

    searchInput.addEventListener("input", applyFilter);
    applyFilter();
  }

  async function fetchJson(url, payload, options = {}) {
    const method = String(options.method || "POST").toUpperCase();
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    const init = {
      method,
      headers,
      credentials: "same-origin",
    };
    if (method !== "GET" && method !== "HEAD") {
      init.body = JSON.stringify(payload || {});
    }
    const resp = await fetch(url, init);
    let data = {};
    try {
      data = await resp.json();
    } catch {
      data = {};
    }
    if (!resp.ok || data?.ok === false) {
      const err = data?.error ? String(data.error) : `http_${resp.status}`;
      throw new Error(err);
    }
    return data;
  }

  function getAnalysisSlugFromLocation() {
    const match = String(window.location.pathname || "").match(/^\/analysis\/([^/?#]+)$/i);
    if (match) return String(match[1]).trim().toLowerCase();
    const isVault = /^\/vault\/?$/i.test(String(window.location.pathname || ""));
    if (isVault) return "vault";
    const shell = document.querySelector(".paywall-shell");
    const fromAttr = shell?.getAttribute("data-slug") || "";
    return String(fromAttr).trim().toLowerCase();
  }

  function setLockMessage(text) {
    const nodes = Array.from(document.querySelectorAll(".lock-message"));
    for (const node of nodes) {
      node.textContent = text;
    }
  }

  function closeWeb3GuideModal() {
    const modal = document.getElementById("web3GuideModal");
    if (!modal) return;
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
  }

  function ensureWeb3GuideModal() {
    let modal = document.getElementById("web3GuideModal");
    if (modal) return modal;
    const copy = getLocaleCopy();
    modal = document.createElement("div");
    modal.id = "web3GuideModal";
    modal.className = "web3-guide-modal";
    modal.setAttribute("aria-hidden", "true");
    modal.innerHTML = `
      <div class="web3-guide-card glass-panel cyber-border">
        <h3 class="web3-guide-title neon-text">${copy.walletGuideTitle}</h3>
        <p class="web3-guide-body">${copy.walletGuideBody}</p>
        <div class="web3-guide-actions">
          <a class="btn btn-main" target="_blank" rel="noopener noreferrer" href="https://metamask.io/download/">${copy.walletGuideInstall}</a>
          <a class="btn" target="_blank" rel="noopener noreferrer" href="https://support.metamask.io/start/getting-started-with-metamask/">${copy.walletGuideLearn}</a>
          <button class="unlock-btn sign-btn" type="button" id="web3GuideCloseBtn">${copy.walletGuideClose}</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    const closeBtn = modal.querySelector("#web3GuideCloseBtn");
    if (closeBtn) {
      closeBtn.addEventListener("click", (event) => {
        event.preventDefault();
        closeWeb3GuideModal();
      });
    }
    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        closeWeb3GuideModal();
      }
    });
    return modal;
  }

  function openWeb3GuideModal() {
    const modal = ensureWeb3GuideModal();
    if (!modal) return;
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
  }

  let guidedGateContext = null;

  function closeObsidianGuidedModal() {
    const modal = document.getElementById("obsidianGuidedModal");
    if (!modal) return;
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
  }

  function setGuidedResult(text, isOk = true) {
    const node = document.getElementById("guidedInlineResult");
    if (!node) return;
    node.textContent = String(text || "");
    node.style.color = isOk ? "#d8e2ea" : "#ffb3b3";
  }

  function buildGateConfigFromButton(button) {
    const safe = button || document.body;
    const plan = String(safe?.getAttribute?.("data-plan") || "sovereign").trim().toLowerCase();
    const paymentRail = normalizePaymentRail(safe?.getAttribute?.("data-payment-rail") || "l2_usdc");
    const slug = String(safe?.getAttribute?.("data-slug") || "vault").trim().toLowerCase();
    const amountUsdc = Number.parseFloat(String(safe?.getAttribute?.("data-amount-usdc") || "199"));
    const erc20Address = String(safe?.getAttribute?.("data-erc20-address") || "").trim();
    const arbitrumAddress = String(safe?.getAttribute?.("data-arbitrum-address") || "").trim();
    const l2Network = String(safe?.getAttribute?.("data-l2-network") || "arbitrum").trim().toLowerCase();
    return {
      plan,
      paymentRail,
      slug,
      amountUsdc: Number.isFinite(amountUsdc) && amountUsdc > 0 ? amountUsdc : 199,
      erc20Address,
      arbitrumAddress,
      l2Network,
    };
  }

  function ensureObsidianGuidedModal() {
    let modal = document.getElementById("obsidianGuidedModal");
    if (modal) return modal;
    const copy = getLocaleCopy();
    modal = document.createElement("div");
    modal.id = "obsidianGuidedModal";
    modal.className = "obsidian-guided-modal";
    modal.setAttribute("aria-hidden", "true");
    modal.innerHTML = `
      <div class="obsidian-guided-card glass-panel cyber-border">
        <button id="guidedCloseBtn" class="payment-close-btn guided-close-btn" type="button">${copy.guidedClose}</button>
        <h3 class="neon-text">${copy.guidedGatewayTitle}</h3>
        <p class="web3-guide-body">${copy.guidedGatewayBody}</p>
        <div class="guided-step-grid">
          <div class="guided-step">
            <span>STEP 1</span>
            <strong id="guidedWalletState">MetaMask / Hardware Mode</strong>
          </div>
          <div class="guided-step">
            <span>ERC20 (ETHEREUM)</span>
            <strong id="guidedErc20Address" class="mono-value">-</strong>
          </div>
          <div class="guided-step">
            <span id="guidedL2Label">ARBITRUM (USDC)</span>
            <strong id="guidedArbitrumAddress" class="mono-value">-</strong>
          </div>
        </div>
        <div id="guidedTransferCopy" class="guided-cta-copy">-</div>
        <div class="guided-actions">
          <button id="guidedConnectBtn" class="unlock-btn sign-btn pulse-glow" type="button">${copy.guidedConnect}</button>
          <button id="guidedCopyErc20Btn" class="btn" type="button">${copy.guidedCopyErc20}</button>
          <button id="guidedCopyArbitrumBtn" class="btn" type="button">${copy.guidedCopyArbitrum}</button>
          <button id="guidedSendTxBtn" class="btn btn-main" type="button">${copy.guidedSendTx}</button>
          <button id="guidedGenerateBtn" class="sovereign-gate-btn pulse-glow" type="button">${copy.guidedGenerate}</button>
        </div>
        <div id="guidedInlineResult" class="guided-inline-result"></div>
      </div>
    `;
    document.body.appendChild(modal);

    const closeBtn = modal.querySelector("#guidedCloseBtn");
    if (closeBtn) {
      closeBtn.addEventListener("click", (event) => {
        event.preventDefault();
        closeObsidianGuidedModal();
      });
    }
    modal.addEventListener("click", (event) => {
      if (event.target === modal) {
        closeObsidianGuidedModal();
      }
    });

    const connectBtn = modal.querySelector("#guidedConnectBtn");
    if (connectBtn) {
      connectBtn.addEventListener("click", async (event) => {
        event.preventDefault();
        if (!guidedGateContext) return;
        const copyNow = getLocaleCopy();
        setGuidedResult(copyNow.guidedPreparing, true);
        await connectWalletAndUnlock(guidedGateContext.slug || "vault");
      });
    }

    const copyErc20Btn = modal.querySelector("#guidedCopyErc20Btn");
    if (copyErc20Btn) {
      copyErc20Btn.addEventListener("click", async (event) => {
        event.preventDefault();
        const copyNow = getLocaleCopy();
        const value = String(guidedGateContext?.erc20Address || "").trim();
        if (!value) return;
        try {
          await navigator.clipboard.writeText(value);
          setGuidedResult(copyNow.guidedCopied, true);
        } catch {
          setGuidedResult(copyNow.guidedTxFailed, false);
        }
      });
    }

    const copyL2Btn = modal.querySelector("#guidedCopyArbitrumBtn");
    if (copyL2Btn) {
      copyL2Btn.addEventListener("click", async (event) => {
        event.preventDefault();
        const copyNow = getLocaleCopy();
        const value = String(guidedGateContext?.arbitrumAddress || "").trim();
        if (!value) return;
        try {
          await navigator.clipboard.writeText(value);
          setGuidedResult(copyNow.guidedCopied, true);
        } catch {
          setGuidedResult(copyNow.guidedTxFailed, false);
        }
      });
    }

    const sendBtn = modal.querySelector("#guidedSendTxBtn");
    if (sendBtn) {
      sendBtn.addEventListener("click", async (event) => {
        event.preventDefault();
        const copyNow = getLocaleCopy();
        const ethereum = window.ethereum;
        if (!ethereum || typeof ethereum.request !== "function") {
          setGuidedResult(copyNow.guidedNoWallet, false);
          openWeb3GuideModal();
          return;
        }
        try {
          if (!guidedGateContext) return;
          const rail = normalizePaymentRail(guidedGateContext.paymentRail);
          const toAddress = rail === "eth_l1_erc20"
            ? guidedGateContext.erc20Address
            : guidedGateContext.arbitrumAddress;
          const tokenContract = ERC20_TOKEN_CONTRACT[rail];
          if (!toAddress || !tokenContract) {
            throw new Error("guided_target_missing");
          }
          await ensureWalletChain(ethereum, rail);
          const accounts = await ethereum.request({ method: "eth_requestAccounts" });
          const from = Array.isArray(accounts) ? String(accounts[0] || "") : "";
          if (!from) throw new Error("wallet_address_missing");
          const units = parseUsdcToUnits(guidedGateContext.amountUsdc);
          const txHash = await ethereum.request({
            method: "eth_sendTransaction",
            params: [
              {
                from,
                to: tokenContract,
                data: encodeErc20TransferData(toAddress, units),
                value: "0x0",
              },
            ],
          });
          setGuidedResult(`${copyNow.guidedTxSubmitted}: ${String(txHash || "")}`, true);
        } catch {
          setGuidedResult(copyNow.guidedTxFailed, false);
        }
      });
    }

    const generateBtn = modal.querySelector("#guidedGenerateBtn");
    if (generateBtn) {
      generateBtn.addEventListener("click", async (event) => {
        event.preventDefault();
        const copyNow = getLocaleCopy();
        if (!guidedGateContext) return;
        const walletAddress = getVaultUnlockedAddress();
        generateBtn.disabled = true;
        setGuidedResult(copyNow.creatingInvoice, true);
        try {
          const invoice = await fetchJson("/api/v1/payment/create", {
            plan_code: guidedGateContext.plan || "sovereign",
            payment_rail: guidedGateContext.paymentRail || "l2_usdc",
            wallet_address: walletAddress,
            slug: guidedGateContext.slug || "vault",
          });
          setGuidedResult(copyNow.invoiceReady, true);
          closeObsidianGuidedModal();
          openPaymentModal(invoice);
        } catch (err) {
          const message = String(err?.message || "").toLowerCase();
          if (message.includes("unlock_required")) {
            setGuidedResult(copyNow.guidedNeedSignature, false);
          } else {
            setGuidedResult(mapPaymentError(err), false);
          }
        } finally {
          generateBtn.disabled = false;
        }
      });
    }
    return modal;
  }

  function openObsidianGuidedModal(config) {
    const modal = ensureObsidianGuidedModal();
    if (!modal) return;
    const copy = getLocaleCopy();
    guidedGateContext = {
      ...config,
      paymentRail: normalizePaymentRail(config?.paymentRail || "l2_usdc"),
    };
    const l2Label = String(guidedGateContext?.l2Network || "arbitrum").toUpperCase();
    const erc20Node = modal.querySelector("#guidedErc20Address");
    const l2Node = modal.querySelector("#guidedArbitrumAddress");
    const l2LabelNode = modal.querySelector("#guidedL2Label");
    const transferNode = modal.querySelector("#guidedTransferCopy");
    const walletNode = modal.querySelector("#guidedWalletState");
    if (erc20Node) erc20Node.textContent = String(guidedGateContext?.erc20Address || "-");
    if (l2Node) l2Node.textContent = String(guidedGateContext?.arbitrumAddress || "-");
    if (l2LabelNode) l2LabelNode.textContent = `${l2Label} (USDC)`;
    if (walletNode) {
      const unlocked = Boolean(getVaultUnlockedAddress());
      walletNode.textContent = unlocked ? "Session Signed / Wallet Verified" : "MetaMask / Hardware Mode";
    }
    if (transferNode) {
      transferNode.textContent = `Transfer ${guidedGateContext.amountUsdc} USDC to the Oracle Vault to decrypt the true Alpha.`;
    }
    setGuidedResult(copy.guidedPreparing, true);
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
  }

  function revealUnlockedContent() {
    const shells = Array.from(document.querySelectorAll(".paywall-shell"));
    for (const shell of shells) {
      shell.classList.add("is-unlocked");
      shell.setAttribute("data-unlocked", "1");
    }
  }

  function mapUnlockError(err) {
    const copy = getLocaleCopy();
    const message = String(err?.message || "").toLowerCase();
    if (message.includes("user rejected")) return copy.signRejected;
    if (message.includes("unlock_not_configured")) return copy.unlockNotConfigured;
    if (message.includes("invalid_signature")) return copy.invalidSignature;
    if (message.includes("challenge")) return copy.challengeExpired;
    if (message.includes("mismatch")) return copy.mismatch;
    if (message.includes("rate_limited")) return copy.rateLimited;
    return copy.unlockFailed;
  }

  async function connectWalletAndUnlock(slugOverride = "") {
    const slug = String(slugOverride || getAnalysisSlugFromLocation() || "analysis")
      .trim()
      .toLowerCase();
    if (!slug) return;
    const shell = document.querySelector(".paywall-shell");
    const alreadyUnlocked = shell?.getAttribute("data-unlocked") === "1";
    if (alreadyUnlocked) return;

    const ethereum = window.ethereum;
    if (!ethereum || typeof ethereum.request !== "function") {
      const copy = getLocaleCopy();
      setLockMessage(copy.walletMissing);
      openWeb3GuideModal();
      return;
    }

    try {
      const copy = getLocaleCopy();
      setLockMessage(copy.negotiating);
      const accounts = await ethereum.request({ method: "eth_requestAccounts" });
      const address = Array.isArray(accounts) ? String(accounts[0] || "") : "";
      if (!address) {
        throw new Error("wallet_address_missing");
      }

      const challenge = await fetchJson("/api/v1/auth/wallet/challenge", { slug });
      const message = String(challenge?.message || "");
      if (!message) throw new Error("challenge_empty");

      const signature = await ethereum.request({
        method: "personal_sign",
        params: [message, address],
      });
      if (!signature) throw new Error("signature_missing");

      await fetchJson("/api/v1/auth/wallet/verify", {
        address,
        signature,
        message,
        slug,
      });

      revealUnlockedContent();
      const pageType = String(document.body?.getAttribute("data-page") || "").toLowerCase();
      setLockMessage(pageType === "vault" ? copy.waitingSync : copy.unlockReload);
      window.setTimeout(() => window.location.reload(), 520);
    } catch (err) {
      setLockMessage(mapUnlockError(err));
    }
  }

  function bindUnlockButton() {
    const buttons = Array.from(document.querySelectorAll(".unlock-btn"));
    if (buttons.length === 0) return;
    for (const button of buttons) {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        void connectWalletAndUnlock();
      });
    }
  }

  function setPaymentResult(text, isOk = true) {
    const node = document.getElementById("paymentResult");
    if (!node) return;
    node.textContent = String(text || "");
    node.style.color = isOk ? "" : "#ffb3b3";
  }

  let paymentPollTimer = null;
  let paymentPollInvoiceId = "";

  function stopPaymentPolling() {
    if (paymentPollTimer) {
      window.clearInterval(paymentPollTimer);
      paymentPollTimer = null;
    }
    paymentPollInvoiceId = "";
  }

  function onPaymentGranted(statusPayload) {
    const copy = getLocaleCopy();
    revealUnlockedContent();
    setLockMessage(copy.accessGranted);
    const syncNodes = Array.from(document.querySelectorAll(".vault-sync-state"));
    for (const node of syncNodes) {
      node.textContent = copy.accessGranted;
    }
    setPaymentResult(
      `${copy.accessGranted} (${String(statusPayload?.status || "paid").toUpperCase()})`,
      true,
    );
  }

  async function pollInvoiceStatus(invoiceId) {
    const copy = getLocaleCopy();
    const cleaned = String(invoiceId || "").trim();
    if (!cleaned) return;
    try {
      const status = await fetchJson(`/api/v1/payment/status?invoice_id=${encodeURIComponent(cleaned)}`, null, { method: "GET" });
      const current = String(status?.status || "pending").toLowerCase();
      if (current === "paid") {
        stopPaymentPolling();
        onPaymentGranted(status);
        window.setTimeout(() => {
          closePaymentModal();
          window.location.reload();
        }, 900);
        return;
      }
      if (current === "expired" || current === "cancelled") {
        stopPaymentPolling();
        setPaymentResult(copy.invoiceExpired, false);
        return;
      }
      setPaymentResult(copy.waitingSettlement, true);
    } catch (err) {
      const msg = String(err?.message || "");
      if (msg.includes("invoice_not_found")) {
        stopPaymentPolling();
        setPaymentResult(copy.invoiceNotFound, false);
        return;
      }
      if (msg.includes("unlock_required") || msg.includes("wallet_session_mismatch")) {
        stopPaymentPolling();
        setPaymentResult(copy.sessionMismatch, false);
        return;
      }
      setPaymentResult(copy.polling, true);
    }
  }

  function startPaymentPolling(invoiceId) {
    const copy = getLocaleCopy();
    const cleaned = String(invoiceId || "").trim();
    if (!cleaned) return;
    stopPaymentPolling();
    paymentPollInvoiceId = cleaned;
    setPaymentResult(copy.waitingSettlement, true);
    void pollInvoiceStatus(cleaned);
    paymentPollTimer = window.setInterval(() => {
      void pollInvoiceStatus(cleaned);
    }, 10000);
  }

  function closePaymentModal() {
    const modal = document.getElementById("paymentModal");
    if (!modal) return;
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    stopPaymentPolling();
  }

  function openPaymentModal(invoice) {
    const modal = document.getElementById("paymentModal");
    if (!modal) return;
    const setText = (id, value) => {
      const node = document.getElementById(id);
      if (node) node.textContent = String(value ?? "-");
    };
    setText("invoiceIdField", invoice.invoice_id);
    const rail = String(invoice.payment_rail || "trc20_usdt");
    setText("invoicePlanField", `${invoice.plan_code} / ${rail}`);
    setText("invoiceAmountField", `${invoice.amount_usdt} USDT`);
    setText("invoiceAddressField", invoice.pay_to_address);
    setText("invoiceNonceField", invoice.nonce);
    setText("invoiceExpiryField", invoice.expires_at_utc);
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    startPaymentPolling(invoice.invoice_id);
  }

  function bindPaymentModalClose() {
    const closeBtn = document.getElementById("paymentModalCloseBtn");
    const modal = document.getElementById("paymentModal");
    if (closeBtn) {
      closeBtn.addEventListener("click", (event) => {
        event.preventDefault();
        closePaymentModal();
      });
    }
    if (modal) {
      modal.addEventListener("click", (event) => {
        if (event.target === modal) {
          closePaymentModal();
        }
      });
    }
  }

  function getVaultUnlockedAddress() {
    const stage = document.querySelector(".vault-stage");
    const fromStage = String(stage?.getAttribute("data-unlocked-address") || "").trim();
    if (fromStage) return fromStage;
    const shell = document.querySelector(".paywall-shell");
    const fromShell = String(shell?.getAttribute("data-unlocked-address") || "").trim();
    return fromShell;
  }

  function mapPaymentError(err) {
    const copy = getLocaleCopy();
    const message = String(err?.message || "").toLowerCase();
    if (message.includes("unlock_required")) return copy.unlockRequired;
    if (message.includes("wallet_session_mismatch")) return copy.sessionMismatch;
    if (message.includes("rate_limited")) return copy.rateLimited;
    return copy.paymentCreateFailed;
  }

  function bindUpgradeButton() {
    const buttons = Array.from(document.querySelectorAll(".upgrade-btn, .sovereign-gate-btn"));
    if (buttons.length === 0) return;
    for (const button of buttons) {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        const config = buildGateConfigFromButton(button);
        openObsidianGuidedModal(config);
      });
    }
  }

  function initVaultSequence() {
    const overlay = document.getElementById("vaultOverlay");
    if (!overlay) return;
    const trigger = document.getElementById("vaultEnterBtn");

    const openVault = () => {
      if (overlay.classList.contains("opening") || overlay.classList.contains("opened")) return;
      overlay.classList.add("opening");
      window.setTimeout(() => {
        overlay.classList.add("opened");
        overlay.setAttribute("aria-hidden", "true");
      }, 3000);
    };

    if (trigger) {
      trigger.addEventListener("click", openVault);
    }

    window.setTimeout(openVault, 800);
  }

  function initForgeCanvas() {
    const canvas = document.getElementById("forgeMatrixCanvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const activeLocale = getActiveLocale();
    const isZh = activeLocale === "zh-tw";
    const forgeText = isZh
      ? {
          noLiveData: "暫無即時資料。",
          waitingHistory: "等待完整歷史資料...",
          passLabel: "通過率（上）",
          alphaLabel: "Alpha 相對現貨（下）",
          reachProb: "達標機率",
          etaRounds: "預估輪次",
          etaUtc: "預估時間",
          passNext: "下一輪通過率區間",
          alphaNext: "下一輪 Alpha 區間",
          deployNext: "下一輪部署區間",
          shadowStatus: "狀態",
          shadowReason: "原因",
          reward: "獎勵代理值",
          returnEst: "回報估計",
          ddEst: "回撤估計",
          tradesEst: "交易筆數估計",
          topAction: "最高權重動作",
          fullHistoryOk: "完整歷史通過",
          fullHistoryGap: "完整歷史缺口",
          observed: "觀測起點",
          required: "要求起點",
          deployOnlyLegacy: "僅舊模型可部署",
          deployDual: "雙軌模式",
          unknown: "未知",
          leaderShadow: "影子領先",
          leaderLegacy: "舊模型領先",
          leaderParity: "平手",
          phaseRecovery: "修復期",
          phaseStabilize: "穩定期",
          phaseCandidate: "候選期",
        }
      : {
          noLiveData: "No live data.",
          waitingHistory: "Waiting full history data...",
          passLabel: "PASS RATE (top)",
          alphaLabel: "ALPHA vs SPOT (bottom)",
          reachProb: "REACH PROBABILITY",
          etaRounds: "ETA ROUNDS",
          etaUtc: "ETA UTC",
          passNext: "PASS NEXT",
          alphaNext: "ALPHA NEXT",
          deployNext: "DEPLOY NEXT",
          shadowStatus: "STATUS",
          shadowReason: "REASON",
          reward: "REWARD PROXY",
          returnEst: "RETURN EST",
          ddEst: "DD EST",
          tradesEst: "TRADES EST",
          topAction: "TOP ACTION",
          fullHistoryOk: "FULL HISTORY OK",
          fullHistoryGap: "FULL HISTORY GAP",
          observed: "observed",
          required: "required",
          deployOnlyLegacy: "LEGACY-ONLY DEPLOY",
          deployDual: "DUAL TRACK",
          unknown: "unknown",
          leaderShadow: "SHADOW LEADS",
          leaderLegacy: "LEGACY LEADS",
          leaderParity: "PARITY",
          phaseRecovery: "recovery",
          phaseStabilize: "stabilize",
          phaseCandidate: "candidate",
        };
    const epochNode = document.getElementById("forgeEpoch");
    const convNode = document.getElementById("forgeConvergence");
    const statusNode = document.getElementById("forgeStatus");
    const priorityNode = document.getElementById("forgePriorityMode");
    const legacyNode = document.getElementById("forgeLegacyTrack");
    const newNode = document.getElementById("forgeNewTrack");
    const updatedNode = document.getElementById("forgeUpdated");
    const rolesNode = document.getElementById("forgeRoleDecisions");
    const featuresNode = document.getElementById("forgeFeatureActions");
    const historyNode = document.getElementById("forgeHistory");
    const historyCanvas = document.getElementById("forgeHistoryCanvas");
    const historyCtx = historyCanvas ? historyCanvas.getContext("2d") : null;
    const historyMetaNode = document.getElementById("forgeHistoryMeta");
    const expectationNode = document.getElementById("forgeExpectation");
    const rlShadowNode = document.getElementById("forgeRlShadow");
    const comparePassNode = document.getElementById("forgeComparePass");
    const compareAlphaNode = document.getElementById("forgeCompareAlpha");
    const compareDeployNode = document.getElementById("forgeCompareDeploy");
    const compareLeaderNode = document.getElementById("forgeCompareLeader");
    const reachProbNode = document.getElementById("forgeReachProb");
    const etaNode = document.getElementById("forgeEta");
    const deployModeNode = document.getElementById("forgeDeployMode");

    const points = Array.from({ length: 96 }, (_, i) => {
      const t = i / 95;
      const baseline = 0.78 - (t * 0.56);
      const wobble = Math.sin((t * 11.2) + 1.3) * 0.028;
      return baseline + wobble;
    });
    const matrixNodes = Array.from({ length: 46 }, (_, i) => ({
      x: ((i * 37) % 320) / 320,
      y: ((i * 53) % 190) / 190,
      r: 0.8 + (i % 3) * 0.4,
    }));

    let rafId = 0;
    let tick = 0;
    let liveTimer = 0;
    let historyRowsState = [];
    let targetsState = {
      validation_pass_rate: 0.4,
      all_window_alpha_vs_spot: -3.0,
      deploy_symbols: 1,
      deploy_rules: 2,
    };

    const forgeState = {
      epochCurrent: 4592,
      epochTotal: 5000,
      convergence: 94.2,
      status: isZh ? "訓練中，尚未授權部署" : "UNAUTHORIZED TO DEPLOY (TRAINING)",
      priority: isZh ? "舊模型優先（修復期）" : "LEGACY PRIORITY ACTIVE (RECOVERY)",
      legacy: isZh ? "通過率=0.0000 | alpha=-0.0000" : "pass=0.0000 | alpha=-0.0000",
      next: isZh ? "影子暖機中" : "shadow warming",
      updated: "-",
    };

    function asFixed(value, digits, fallback = 0) {
      const n = Number(value);
      return Number.isFinite(n) ? n.toFixed(digits) : Number(fallback).toFixed(digits);
    }

    function setList(node, rows) {
      if (!node) return;
      const safeRows = Array.isArray(rows) ? rows.filter((v) => String(v || "").trim()) : [];
      if (safeRows.length === 0) {
        node.innerHTML = `<li>${forgeText.noLiveData}</li>`;
        return;
      }
      node.innerHTML = safeRows
        .slice(0, 8)
        .map((row) => `<li>${String(row).replaceAll("<", "&lt;").replaceAll(">", "&gt;")}</li>`)
        .join("");
    }

    function signed(value, digits = 4) {
      const n = Number(value);
      if (!Number.isFinite(n)) return "0";
      const fixed = n.toFixed(digits);
      return n > 0 ? `+${fixed}` : fixed;
    }

    function applyDeltaTone(node, value) {
      if (!node) return;
      node.classList.remove("delta-pos", "delta-neg", "delta-flat");
      const n = Number(value);
      if (!Number.isFinite(n) || Math.abs(n) < 1e-9) {
        node.classList.add("delta-flat");
        return;
      }
      node.classList.add(n > 0 ? "delta-pos" : "delta-neg");
    }

    function drawHistoryChart() {
      if (!historyCtx || !historyCanvas) return;
      const ratio = window.devicePixelRatio || 1;
      const rect = historyCanvas.getBoundingClientRect();
      const w = Math.max(600, Math.floor(rect.width * ratio));
      const h = Math.max(220, Math.floor(rect.height * ratio));
      historyCanvas.width = w;
      historyCanvas.height = h;
      historyCtx.clearRect(0, 0, w, h);

      const rows = Array.isArray(historyRowsState) ? historyRowsState : [];
      if (rows.length < 2) {
        historyCtx.fillStyle = "rgba(219,229,235,0.72)";
        historyCtx.font = `${12 * ratio}px JetBrains Mono, monospace`;
        historyCtx.fillText(forgeText.waitingHistory, 14 * ratio, 22 * ratio);
        return;
      }

      const left = 42 * ratio;
      const right = 16 * ratio;
      const top = 14 * ratio;
      const midTop = Math.floor(h * 0.50);
      const gap = 8 * ratio;
      const passTop = top;
      const passBottom = midTop - gap;
      const alphaTop = midTop + gap;
      const alphaBottom = h - 18 * ratio;
      const innerW = Math.max(1, w - left - right);

      const passValues = rows.map((r) => Number.parseFloat(String(r?.validation_pass_rate ?? "0"))).map((v) => (Number.isFinite(v) ? v : 0));
      const alphaValues = rows.map((r) => Number.parseFloat(String(r?.all_window_alpha_vs_spot ?? "0"))).map((v) => (Number.isFinite(v) ? v : 0));
      const passTarget = Number.parseFloat(String(targetsState.validation_pass_rate ?? "0.4"));
      const alphaTarget = Number.parseFloat(String(targetsState.all_window_alpha_vs_spot ?? "-3"));
      const alphaMin = Math.min(...alphaValues, alphaTarget) - 0.5;
      const alphaMax = Math.max(...alphaValues, alphaTarget) + 0.5;
      const safeAlphaSpan = Math.max(0.8, alphaMax - alphaMin);

      historyCtx.strokeStyle = "rgba(192,192,192,0.12)";
      historyCtx.lineWidth = 1;
      for (let i = 0; i <= 10; i += 1) {
        const x = left + (i / 10) * innerW;
        historyCtx.beginPath();
        historyCtx.moveTo(x, passTop);
        historyCtx.lineTo(x, alphaBottom);
        historyCtx.stroke();
      }

      const yPassTarget = passBottom - Math.max(0, Math.min(1, passTarget)) * (passBottom - passTop);
      historyCtx.strokeStyle = "rgba(212,175,55,0.35)";
      historyCtx.setLineDash([5 * ratio, 4 * ratio]);
      historyCtx.beginPath();
      historyCtx.moveTo(left, yPassTarget);
      historyCtx.lineTo(left + innerW, yPassTarget);
      historyCtx.stroke();

      const alphaTargetNorm = (alphaTarget - alphaMin) / safeAlphaSpan;
      const yAlphaTarget = alphaBottom - alphaTargetNorm * (alphaBottom - alphaTop);
      historyCtx.strokeStyle = "rgba(255,69,0,0.35)";
      historyCtx.beginPath();
      historyCtx.moveTo(left, yAlphaTarget);
      historyCtx.lineTo(left + innerW, yAlphaTarget);
      historyCtx.stroke();
      historyCtx.setLineDash([]);

      historyCtx.strokeStyle = "rgba(212,175,55,0.85)";
      historyCtx.lineWidth = 2;
      historyCtx.beginPath();
      passValues.forEach((value, idx) => {
        const x = left + (idx / Math.max(1, passValues.length - 1)) * innerW;
        const y = passBottom - Math.max(0, Math.min(1, value)) * (passBottom - passTop);
        if (idx === 0) historyCtx.moveTo(x, y);
        else historyCtx.lineTo(x, y);
      });
      historyCtx.stroke();

      historyCtx.strokeStyle = "rgba(255,69,0,0.85)";
      historyCtx.beginPath();
      alphaValues.forEach((value, idx) => {
        const x = left + (idx / Math.max(1, alphaValues.length - 1)) * innerW;
        const norm = (value - alphaMin) / safeAlphaSpan;
        const y = alphaBottom - Math.max(0, Math.min(1, norm)) * (alphaBottom - alphaTop);
        if (idx === 0) historyCtx.moveTo(x, y);
        else historyCtx.lineTo(x, y);
      });
      historyCtx.stroke();

      historyCtx.fillStyle = "rgba(219,229,235,0.82)";
      historyCtx.font = `${10 * ratio}px JetBrains Mono, monospace`;
      historyCtx.fillText(forgeText.passLabel, left, 10 * ratio);
      historyCtx.fillText(forgeText.alphaLabel, left, (midTop + 2 * ratio));
    }

    function applyLivePayload(payload) {
      if (!payload || typeof payload !== "object") return;
      const forge = payload.forge && typeof payload.forge === "object" ? payload.forge : {};
      const legacy = payload.legacy_status && typeof payload.legacy_status === "object" ? payload.legacy_status : {};
      const next = payload.new_model_status && typeof payload.new_model_status === "object" ? payload.new_model_status : {};
      const roles = payload.role_decisions && typeof payload.role_decisions === "object" ? payload.role_decisions : {};
      const featureActions = payload.feature_actions && typeof payload.feature_actions === "object" ? payload.feature_actions : {};
      const historyRows = Array.isArray(payload.history) ? payload.history : [];
      const expectation = payload.expectation && typeof payload.expectation === "object" ? payload.expectation : {};
      const rlShadow = payload.rl_shadow_status && typeof payload.rl_shadow_status === "object" ? payload.rl_shadow_status : {};
      const compare = payload.compare && typeof payload.compare === "object" ? payload.compare : {};
      const progress = payload.progress && typeof payload.progress === "object" ? payload.progress : {};
      const targets = payload.targets && typeof payload.targets === "object" ? payload.targets : {};
      const historyContract = payload.history_contract && typeof payload.history_contract === "object" ? payload.history_contract : {};
      historyRowsState = historyRows;
      targetsState = {
        validation_pass_rate: Number.isFinite(Number(targets.validation_pass_rate)) ? Number(targets.validation_pass_rate) : targetsState.validation_pass_rate,
        all_window_alpha_vs_spot: Number.isFinite(Number(targets.all_window_alpha_vs_spot)) ? Number(targets.all_window_alpha_vs_spot) : targetsState.all_window_alpha_vs_spot,
        deploy_symbols: Number.isFinite(Number(targets.deploy_symbols)) ? Number(targets.deploy_symbols) : targetsState.deploy_symbols,
        deploy_rules: Number.isFinite(Number(targets.deploy_rules)) ? Number(targets.deploy_rules) : targetsState.deploy_rules,
      };

      const epochTotal = Number.parseInt(String(forge.epoch_total || forgeState.epochTotal), 10);
      const epochCurrent = Number.parseInt(String(forge.epoch_current || forgeState.epochCurrent), 10);
      forgeState.epochTotal = Number.isFinite(epochTotal) && epochTotal > 0 ? epochTotal : forgeState.epochTotal;
      forgeState.epochCurrent = Number.isFinite(epochCurrent) && epochCurrent > 0 ? Math.min(epochCurrent, forgeState.epochTotal) : forgeState.epochCurrent;
      forgeState.convergence = Number.isFinite(Number(forge.alpha_convergence_pct))
        ? Math.max(0, Math.min(99.9, Number(forge.alpha_convergence_pct)))
        : forgeState.convergence;
      const priorityRaw = String(payload.priority_mode || "").toLowerCase();
      if (isZh) {
        forgeState.priority = priorityRaw === "legacy_recovery"
          ? "舊模型優先（修復期）"
          : priorityRaw === "dual_train"
            ? "雙軌訓練"
            : "待命";
        forgeState.status = priorityRaw === "legacy_recovery"
          ? "訓練中，尚未授權部署"
          : priorityRaw === "dual_train"
            ? "訓練中，雙軌評估運行"
            : "等待下一輪訓練";
      } else {
        forgeState.priority = String(payload.priority_mode || forgeState.priority).toUpperCase();
        forgeState.status = String(forge.status_text || forgeState.status);
      }
      forgeState.legacy = isZh
        ? `通過率=${asFixed(legacy.validation_pass_rate, 4)} | alpha=${asFixed(legacy.all_window_alpha_vs_spot, 4)} | 部署=${String(legacy.deploy_symbols || 0)}/${String(legacy.deploy_rules || 0)}`
        : `pass=${asFixed(legacy.validation_pass_rate, 4)} | alpha=${asFixed(legacy.all_window_alpha_vs_spot, 4)} | deploy=${String(legacy.deploy_symbols || 0)}/${String(legacy.deploy_rules || 0)}`;
      const nextStatusRaw = String(next.status || "unknown");
      const nextStatusZh = nextStatusRaw === "shadow_blocked_by_legacy_priority"
        ? "受舊模型優先策略限制"
        : nextStatusRaw === "shadow_running"
          ? "影子評估進行中"
          : "未知";
      forgeState.next = isZh
        ? `狀態=${nextStatusZh} | 回報=${String(next.total_return_pct || "-")} | 回撤=${String(next.max_drawdown_pct || "-")}`
        : `status=${String(next.status || "unknown")} | return=${String(next.total_return_pct || "-")} | dd=${String(next.max_drawdown_pct || "-")}`;
      forgeState.updated = String(payload.generated_at_utc || "-");

      if (priorityNode) priorityNode.textContent = forgeState.priority;
      if (legacyNode) legacyNode.textContent = forgeState.legacy;
      if (newNode) newNode.textContent = forgeState.next;
      if (updatedNode) updatedNode.textContent = forgeState.updated;
      const reachProb = Number.isFinite(Number(progress.reach_target_probability))
        ? Number(progress.reach_target_probability)
        : Number(expectation.reach_target_probability || 0);
      if (reachProbNode) {
        reachProbNode.textContent = `${(Math.max(0, Math.min(1, reachProb)) * 100).toFixed(1)}%`;
      }
      if (etaNode) {
        etaNode.textContent = String(progress.eta_utc || expectation.eta_utc || forgeText.unknown);
      }
      if (deployModeNode) {
        const legacyOnly = Boolean(progress.legacy_only_deploy ?? payload.legacy_only_deploy);
        deployModeNode.textContent = legacyOnly ? forgeText.deployOnlyLegacy : forgeText.deployDual;
      }
      const passGap = Number(compare.pass_gap_to_target ?? 0);
      const alphaGap = Number(compare.alpha_gap_to_target ?? 0);
      const deploySymbolsGap = Number(compare.deploy_symbols_gap_to_target ?? 0);
      const deployRulesGap = Number(compare.deploy_rules_gap_to_target ?? 0);
      const rewardGap = Number(compare.shadow_reward_gap ?? 0);
      if (comparePassNode) {
        comparePassNode.textContent = signed(passGap, 4);
        applyDeltaTone(comparePassNode, passGap);
      }
      if (compareAlphaNode) {
        compareAlphaNode.textContent = signed(alphaGap, 4);
        applyDeltaTone(compareAlphaNode, alphaGap);
      }
      if (compareDeployNode) {
        compareDeployNode.textContent = `${signed(deploySymbolsGap, 0)} / ${signed(deployRulesGap, 0)}`;
        applyDeltaTone(compareDeployNode, deploySymbolsGap + deployRulesGap);
      }
      if (compareLeaderNode) {
        const leaderRaw = String(compare.leader || "parity").toLowerCase();
        const leaderText = leaderRaw === "shadow"
          ? forgeText.leaderShadow
          : leaderRaw === "legacy"
            ? forgeText.leaderLegacy
            : forgeText.leaderParity;
        compareLeaderNode.textContent = `${leaderText} (${signed(rewardGap, 4)})`;
        applyDeltaTone(compareLeaderNode, rewardGap);
      }

      const roleRows = isZh
        ? [
          `管線狀態：${String(roles.pipeline_state || "-")}`,
          `優先模式：${forgeState.priority}`,
          `部署策略：${deployModeNode ? String(deployModeNode.textContent || forgeText.deployOnlyLegacy) : forgeText.deployOnlyLegacy}`,
        ]
        : Object.values(roles).map((value) => String(value || "").trim()).filter(Boolean);
      setList(rolesNode, roleRows);

      const featureRows = [];
      for (const key of ["boost", "prune", "watch"]) {
        const rows = Array.isArray(featureActions[key]) ? featureActions[key] : [];
        for (const row of rows.slice(0, 3)) {
          featureRows.push(`${key.toUpperCase()}: ${String(row)}`);
        }
      }
      setList(featuresNode, featureRows);

      const historyView = historyRows
        .slice(-10)
        .reverse()
        .map((row) => {
          const ts = String(row?.ts_utc || "-").replace("T", " ").replace("Z", " UTC");
          const pass = asFixed(row?.validation_pass_rate, 3);
          const alpha = asFixed(row?.all_window_alpha_vs_spot, 3);
          const score = asFixed(row?.quality_score, 3);
          const phaseRaw = String(row?.phase || "unknown");
          const phase = phaseRaw === "recovery"
            ? forgeText.phaseRecovery
            : phaseRaw === "stabilize"
              ? forgeText.phaseStabilize
              : phaseRaw === "candidate"
                ? forgeText.phaseCandidate
                : phaseRaw;
          const tags = Array.isArray(row?.improvement_tags) ? row.improvement_tags.join(",") : "";
          return isZh
            ? `${ts} | ${phase} | 通過率 ${pass} | alpha ${alpha} | 品質 ${score}${tags ? ` | ${tags}` : ""}`
            : `${ts} | ${phase} | pass ${pass} | alpha ${alpha} | score ${score}${tags ? ` | ${tags}` : ""}`;
        });
      setList(historyNode, historyView);

      const expectationRows = [];
      const p = Number.parseFloat(String(expectation.reach_target_probability || "0"));
      const etaRounds = expectation.eta_rounds;
      expectationRows.push(`${forgeText.reachProb}: ${Number.isFinite(p) ? (p * 100).toFixed(1) : "0.0"}%`);
      expectationRows.push(`${forgeText.etaRounds}: ${etaRounds == null ? forgeText.unknown : String(etaRounds)}`);
      expectationRows.push(`${forgeText.etaUtc}: ${String(expectation.eta_utc || forgeText.unknown)}`);
      const passRange = Array.isArray(expectation.pass_rate_next_range) ? expectation.pass_rate_next_range : [];
      if (passRange.length === 2) expectationRows.push(`${forgeText.passNext}: ${asFixed(passRange[0], 4)} ~ ${asFixed(passRange[1], 4)}`);
      const alphaRange = Array.isArray(expectation.alpha_next_range) ? expectation.alpha_next_range : [];
      if (alphaRange.length === 2) expectationRows.push(`${forgeText.alphaNext}: ${asFixed(alphaRange[0], 4)} ~ ${asFixed(alphaRange[1], 4)}`);
      const deployRange = Array.isArray(expectation.deploy_next_range) ? expectation.deploy_next_range : [];
      if (deployRange.length === 2) expectationRows.push(`${forgeText.deployNext}: ${asFixed(deployRange[0], 2)} ~ ${asFixed(deployRange[1], 2)}`);
      setList(expectationNode, expectationRows);

      const rlRows = [];
      rlRows.push(`${forgeText.shadowStatus}: ${String(rlShadow.status || "hold_shadow")}`);
      rlRows.push(`${forgeText.shadowReason}: ${String(rlShadow.reason || "-")}`);
      rlRows.push(`${forgeText.reward}: ${asFixed(rlShadow.reward_proxy, 6)}`);
      rlRows.push(`${forgeText.returnEst}: ${asFixed(rlShadow.friction_adjusted_return_est, 6)}`);
      rlRows.push(`${forgeText.ddEst}: ${asFixed(rlShadow.max_drawdown_est, 6)}`);
      rlRows.push(`${forgeText.tradesEst}: ${asFixed(rlShadow.trades_est, 2)}`);
      const topActions = Array.isArray(rlShadow.top_actions) ? rlShadow.top_actions : [];
      if (topActions.length > 0) {
        const top = topActions[0] || {};
        rlRows.push(`${forgeText.topAction}: ${String(top.rule_key || "n/a")} @ ${String(top.core_id || "n/a")} (${asFixed(top.probability, 3)})`);
      }
      setList(rlShadowNode, rlRows);

      if (historyMetaNode) {
        const fullOk = Boolean(historyContract.full_history_ok);
        const observed = String(historyContract.observed_start_utc || "-");
        const required = String(historyContract.required_start_utc || "2020-01-01T00:00:00Z");
        historyMetaNode.textContent = `${fullOk ? forgeText.fullHistoryOk : forgeText.fullHistoryGap} | ${forgeText.observed}=${observed} | ${forgeText.required}=${required}`;
      }
      drawHistoryChart();
    }

    async function refreshLiveState() {
      try {
        const payload = await fetchJson("/api/v1/ml/live", null, { method: "GET" });
        applyLivePayload(payload);
      } catch {
        // Keep latest known local state if network fails.
      }
    }

    function resize() {
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(600, Math.floor(rect.width * (window.devicePixelRatio || 1)));
      canvas.height = Math.max(220, Math.floor(rect.height * (window.devicePixelRatio || 1)));
      drawHistoryChart();
    }

    function drawGrid() {
      const w = canvas.width;
      const h = canvas.height;
      ctx.strokeStyle = "rgba(192,192,192,0.08)";
      ctx.lineWidth = 1;
      for (let x = 0; x <= 12; x += 1) {
        const px = (x / 12) * w;
        ctx.beginPath();
        ctx.moveTo(px, 0);
        ctx.lineTo(px, h);
        ctx.stroke();
      }
      for (let y = 0; y <= 8; y += 1) {
        const py = (y / 8) * h;
        ctx.beginPath();
        ctx.moveTo(0, py);
        ctx.lineTo(w, py);
        ctx.stroke();
      }
    }

    function drawNeuralMatrix(timeSec) {
      const w = canvas.width;
      const h = canvas.height;
      for (const node of matrixNodes) {
        const pulse = 0.4 + (Math.sin((timeSec * 1.7) + (node.x * 9.3) + (node.y * 4.1)) * 0.3);
        const x = node.x * w;
        const y = node.y * h;
        ctx.fillStyle = `rgba(212,175,55,${Math.max(0.08, pulse)})`;
        ctx.beginPath();
        ctx.arc(x, y, node.r * (window.devicePixelRatio || 1), 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.strokeStyle = "rgba(212,175,55,0.16)";
      ctx.lineWidth = 1;
      for (let i = 1; i < matrixNodes.length; i += 2) {
        const a = matrixNodes[i - 1];
        const b = matrixNodes[i];
        ctx.beginPath();
        ctx.moveTo(a.x * w, a.y * h);
        ctx.lineTo(b.x * w, b.y * h);
        ctx.stroke();
      }
    }

    function drawLossCurve(timeSec) {
      const w = canvas.width;
      const h = canvas.height;
      const leftPad = w * 0.04;
      const rightPad = w * 0.04;
      const topPad = h * 0.10;
      const botPad = h * 0.14;
      const innerW = Math.max(1, w - leftPad - rightPad);
      const innerH = Math.max(1, h - topPad - botPad);

      ctx.strokeStyle = "rgba(255,69,0,0.75)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      points.forEach((value, idx) => {
        const x = leftPad + (idx / Math.max(1, points.length - 1)) * innerW;
        const micro = Math.sin((idx * 0.6) + (timeSec * 1.5)) * 0.007;
        const y = topPad + Math.max(0.04, Math.min(0.98, value + micro)) * innerH;
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      const nowProgress = ((tick % 420) / 420);
      const pulseIndex = Math.floor(nowProgress * (points.length - 1));
      const px = leftPad + (pulseIndex / Math.max(1, points.length - 1)) * innerW;
      const py = topPad + points[pulseIndex] * innerH;
      ctx.fillStyle = "rgba(255,69,0,0.82)";
      ctx.beginPath();
      ctx.arc(px, py, 5 * (window.devicePixelRatio || 1), 0, Math.PI * 2);
      ctx.fill();
    }

    function frame(now) {
      const t = now * 0.001;
      tick += 1;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      drawGrid();
      drawNeuralMatrix(t);
      drawLossCurve(t);

      if (epochNode) {
        epochNode.textContent = `${forgeState.epochCurrent}/${forgeState.epochTotal}`;
      }
      if (convNode) {
        const drift = Math.sin(tick * 0.018) * 0.08;
        const convergence = Math.max(0, Math.min(99.9, forgeState.convergence + drift));
        convNode.textContent = `${convergence.toFixed(1)}%`;
      }
      if (statusNode) {
        statusNode.textContent = forgeState.status;
      }
      rafId = window.requestAnimationFrame(frame);
    }

    resize();
    void refreshLiveState();
    liveTimer = window.setInterval(() => {
      void refreshLiveState();
    }, 5000);
    frame(0);
    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("beforeunload", () => {
      window.cancelAnimationFrame(rafId);
      window.clearInterval(liveTimer);
      window.removeEventListener("resize", resize);
    });
  }

  window.addEventListener("beforeunload", stopPaymentPolling);

  function initObsidianBackground(config) {
    const canvas = document.getElementById("matrix-bg");
    if (!canvas) return;
    const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) {
      document.body.classList.add("low-gpu");
      return;
    }

    const gl = canvas.getContext("webgl", { antialias: true, alpha: true });
    if (!gl) {
      document.body.classList.add("low-gpu");
      return;
    }

    const vsSource = `
      attribute vec4 aVertexPosition;
      void main() {
        gl_Position = aVertexPosition;
      }
    `;

    const fsSource = `
      precision highp float;
      uniform vec2 u_resolution;
      uniform float u_time;
      uniform vec2 u_mouse;
      uniform vec3 u_accent;

      float random(vec2 st) {
        return fract(sin(dot(st.xy, vec2(12.9898,78.233))) * 43758.5453123);
      }

      float noise(vec2 st) {
        vec2 i = floor(st);
        vec2 f = fract(st);
        float a = random(i);
        float b = random(i + vec2(1.0, 0.0));
        float c = random(i + vec2(0.0, 1.0));
        float d = random(i + vec2(1.0, 1.0));
        vec2 u = f * f * (3.0 - 2.0 * f);
        return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
      }

      #define OCTAVES 5
      float fbm(vec2 st) {
        float value = 0.0;
        float amplitude = 0.5;
        for (int i = 0; i < OCTAVES; i++) {
          value += amplitude * noise(st);
          st *= 2.0;
          amplitude *= 0.5;
        }
        return value;
      }

      void main() {
        vec2 st = gl_FragCoord.xy / u_resolution.xy;
        st.x *= u_resolution.x / u_resolution.y;

        vec2 mouse = u_mouse.xy / u_resolution.xy;
        float dist = distance(st, mouse);

        vec2 q = vec2(0.0);
        q.x = fbm(st + 0.00 * u_time);
        q.y = fbm(st + vec2(1.0));

        vec2 r = vec2(0.0);
        r.x = fbm(st + 1.0 * q + vec2(1.7, 9.2) + 0.15 * u_time + dist * 0.1);
        r.y = fbm(st + 1.0 * q + vec2(8.3, 2.8) + 0.126 * u_time);

        float f = fbm(st + r);

        vec3 color = mix(vec3(0.02, 0.02, 0.03), vec3(0.08, 0.08, 0.09), clamp((f * f) * 4.0, 0.0, 1.0));
        color = mix(color, u_accent * 0.4, clamp(length(q), 0.0, 1.0));
        color = mix(color, u_accent * 0.8, clamp(abs(r.x), 0.0, 1.0));

        float interaction = smoothstep(0.4, 0.0, dist);
        color += u_accent * interaction * 0.14;

        gl_FragColor = vec4((f * f * f + 0.6 * f * f + 0.5 * f) * color, 1.0);
      }
    `;

    function compileShader(type, source) {
      const shader = gl.createShader(type);
      if (!shader) return null;
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        gl.deleteShader(shader);
        return null;
      }
      return shader;
    }

    const vertexShader = compileShader(gl.VERTEX_SHADER, vsSource);
    const fragmentShader = compileShader(gl.FRAGMENT_SHADER, fsSource);
    if (!vertexShader || !fragmentShader) return;

    const program = gl.createProgram();
    if (!program) return;
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      return;
    }
    gl.useProgram(program);

    const positionBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([
        -1.0, -1.0,
         1.0, -1.0,
        -1.0,  1.0,
        -1.0,  1.0,
         1.0, -1.0,
         1.0,  1.0,
      ]),
      gl.STATIC_DRAW,
    );

    const positionLocation = gl.getAttribLocation(program, "aVertexPosition");
    gl.enableVertexAttribArray(positionLocation);
    gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);

    const resolutionLocation = gl.getUniformLocation(program, "u_resolution");
    const timeLocation = gl.getUniformLocation(program, "u_time");
    const mouseLocation = gl.getUniformLocation(program, "u_mouse");
    const accentLocation = gl.getUniformLocation(program, "u_accent");

    const accentRgb = hexToRgb01(config.accent);
    let mouseX = window.innerWidth / 2;
    let mouseY = window.innerHeight / 2;
    let rafId = 0;
    let fpsFrames = 0;
    let fpsStart = performance.now();
    let fpsChecked = false;
    let disabled = false;

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      gl.viewport(0, 0, canvas.width, canvas.height);
    }

    function onMouseMove(event) {
      mouseX = event.clientX;
      mouseY = window.innerHeight - event.clientY;
    }

    function disableToStatic() {
      if (disabled) return;
      disabled = true;
      document.body.classList.add("low-gpu");
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", onMouseMove);
      canvas.style.display = "none";
    }

    function frame(time) {
      if (disabled) return;
      gl.uniform2f(resolutionLocation, canvas.width, canvas.height);
      gl.uniform1f(timeLocation, time * 0.001);
      gl.uniform2f(mouseLocation, mouseX, mouseY);
      gl.uniform3f(accentLocation, accentRgb[0], accentRgb[1], accentRgb[2]);
      gl.drawArrays(gl.TRIANGLES, 0, 6);

      fpsFrames += 1;
      if (!fpsChecked) {
        const elapsedMs = Math.max(1, time - fpsStart);
        if (elapsedMs >= 3000) {
          const fps = (fpsFrames * 1000) / elapsedMs;
          fpsChecked = true;
          if (fps < 30) {
            disableToStatic();
            return;
          }
        }
      }
      rafId = requestAnimationFrame(frame);
    }

    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("mousemove", onMouseMove, { passive: true });
    resize();
    frame(0);

    window.addEventListener("beforeunload", () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", onMouseMove);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindLocaleSwitcher();
    const config = getLuxuryConfig();
    applyLuxuryTheme(config);
    formatUtcNodes();
    bindSearch();
    bindUnlockButton();
    bindUpgradeButton();
    bindPaymentModalClose();
    initVaultSequence();
    initForgeCanvas();
    initObsidianBackground(config);
  });
})();
