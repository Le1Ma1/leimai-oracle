(() => {
  const WEALTH_HUBS = new Set([
    "Asia/Singapore",
    "Asia/Dubai",
    "Europe/Zurich",
    "America/New_York",
    "Europe/Monaco",
  ]);

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

  function revealUnlockedContent() {
    const shells = Array.from(document.querySelectorAll(".paywall-shell"));
    for (const shell of shells) {
      shell.classList.add("is-unlocked");
      shell.setAttribute("data-unlocked", "1");
    }
  }

  function mapUnlockError(err) {
    const message = String(err?.message || "").toLowerCase();
    if (message.includes("user rejected")) return "Signature rejected by wallet.";
    if (message.includes("unlock_not_configured")) return "Unlock service is not configured.";
    if (message.includes("invalid_signature")) return "Invalid signature. Please retry.";
    if (message.includes("challenge")) return "Challenge expired. Please retry.";
    if (message.includes("mismatch")) return "Address mismatch detected.";
    if (message.includes("rate_limited")) return "Too many attempts. Please wait.";
    return "Unlock failed. Please retry.";
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
      setLockMessage("Wallet not found. Please install a Web3 wallet.");
      return;
    }

    try {
      setLockMessage("Negotiating Secure Enclave...");
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
      setLockMessage(pageType === "vault" ? "Waiting for Model Synced" : "Access verified. Reloading full report...");
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
    revealUnlockedContent();
    setLockMessage("Access Granted: Synchronizing Sovereign Signals");
    const syncNodes = Array.from(document.querySelectorAll(".vault-sync-state"));
    for (const node of syncNodes) {
      node.textContent = "Access Granted: Synchronizing Sovereign Signals";
    }
    setPaymentResult(
      `Payment confirmed (${String(statusPayload?.status || "paid").toUpperCase()}). Access Granted: Synchronizing Sovereign Signals`,
      true,
    );
  }

  async function pollInvoiceStatus(invoiceId) {
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
        setPaymentResult(`Invoice ${current}. Please create a new invoice.`, false);
        return;
      }
      setPaymentResult("Awaiting on-chain confirmation...", true);
    } catch (err) {
      const msg = String(err?.message || "");
      if (msg.includes("invoice_not_found")) {
        stopPaymentPolling();
        setPaymentResult("Invoice not found. Please create a new one.", false);
        return;
      }
      if (msg.includes("unlock_required") || msg.includes("wallet_session_mismatch")) {
        stopPaymentPolling();
        setPaymentResult("Session expired or wallet mismatch. Please sign again.", false);
        return;
      }
      setPaymentResult("Polling payment status...", true);
    }
  }

  function startPaymentPolling(invoiceId) {
    const cleaned = String(invoiceId || "").trim();
    if (!cleaned) return;
    stopPaymentPolling();
    paymentPollInvoiceId = cleaned;
    setPaymentResult("Awaiting on-chain confirmation...", true);
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
    const message = String(err?.message || "").toLowerCase();
    if (message.includes("unlock_required")) return "Unlock session required before creating invoice.";
    if (message.includes("wallet_session_mismatch")) return "Wallet mismatch. Re-sign wallet contract and retry.";
    if (message.includes("rate_limited")) return "Too many payment requests. Please wait.";
    return "Payment invoice creation failed. Please retry.";
  }

  function bindUpgradeButton() {
    const buttons = Array.from(document.querySelectorAll(".upgrade-btn"));
    if (buttons.length === 0) return;
    for (const button of buttons) {
      button.addEventListener("click", async (event) => {
        event.preventDefault();
        const plan = String(button.getAttribute("data-plan") || "sovereign").trim().toLowerCase();
        const paymentRail = String(button.getAttribute("data-payment-rail") || "trc20_usdt").trim().toLowerCase();
        const walletAddress = getVaultUnlockedAddress();
        button.disabled = true;
        setPaymentResult("Creating payment invoice...", true);
        try {
          const invoice = await fetchJson("/api/v1/payment/create", {
            plan_code: plan,
            payment_rail: paymentRail,
            wallet_address: walletAddress,
            slug: "vault",
          });
          setPaymentResult("Invoice ready. Transfer to the designated address before expiry.", true);
          openPaymentModal(invoice);
        } catch (err) {
          setPaymentResult(mapPaymentError(err), false);
        } finally {
          button.disabled = false;
        }
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

  window.addEventListener("beforeunload", stopPaymentPolling);

  function initObsidianBackground(config) {
    const canvas = document.getElementById("matrix-bg");
    if (!canvas) return;
    const gl = canvas.getContext("webgl", { antialias: true, alpha: true });
    if (!gl) return;

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

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      gl.viewport(0, 0, canvas.width, canvas.height);
    }

    function onMouseMove(event) {
      mouseX = event.clientX;
      mouseY = window.innerHeight - event.clientY;
    }

    function frame(time) {
      gl.uniform2f(resolutionLocation, canvas.width, canvas.height);
      gl.uniform1f(timeLocation, time * 0.001);
      gl.uniform2f(mouseLocation, mouseX, mouseY);
      gl.uniform3f(accentLocation, accentRgb[0], accentRgb[1], accentRgb[2]);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
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
    const config = getLuxuryConfig();
    applyLuxuryTheme(config);
    formatUtcNodes();
    bindSearch();
    bindUnlockButton();
    bindUpgradeButton();
    bindPaymentModalClose();
    initVaultSequence();
    initObsidianBackground(config);
  });
})();
