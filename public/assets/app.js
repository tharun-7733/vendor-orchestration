(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const elements = {
    rows: byId("case-rows"), search: byId("search-input"), filter: byId("status-filter"),
    form: byId("screening-form"), formBackdrop: byId("form-backdrop"),
    detailBackdrop: byId("detail-backdrop"), detail: byId("detail-content"),
    formAlert: byId("form-alert"), submit: byId("submit-button"),
  };
  let cases = [];
  let selectedCaseId = null;
  let loading = false;
  let csrfToken = null;
  let authenticated = false;
  let authMode = "login";

  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };

  function toast(message, kind = "success") {
    const node = make("div", `toast ${kind}`, message);
    byId("toast-region").append(node);
    window.setTimeout(() => node.remove(), 4200);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(csrfToken && options.method && options.method !== "GET" ? { "X-CSRF-Token": csrfToken } : {}),
        ...options.headers,
      },
      credentials: "same-origin",
      cache: "no-store",
      signal: AbortSignal.timeout(12000),
    });
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try {
        const body = await response.json();
        if (typeof body.detail === "string") message = body.detail;
      } catch { /* Keep the generic HTTP error when the server did not return JSON. */ }
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return response.status === 204 ? null : response.json();
  }

  const prettyStatus = (status) => ({
    PENDING: "Pending", CLEARED: "Cleared", NEEDS_REVIEW: "Needs review", REJECTED: "Rejected",
    queued: "Pending", processing: "Pending", clear: "Cleared", review: "Needs review", rejected: "Rejected", failed: "Pending",
  }[status] || "Pending");

  function vendorState(check) {
    if (!check) return { text: "Pending", className: "" };
    if (check.error) return { text: "Error", className: "hit" };
    return check.matched ? { text: "Review", className: "hit" } : { text: "Clear", className: "pass" };
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
  }

  function avatarText(name) {
    return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
  }

  function makeStatus(status) {
    const tone = { PENDING: "queued", CLEARED: "clear", NEEDS_REVIEW: "review", REJECTED: "rejected" }[status] || status;
    const badge = make("span", `status-badge status-${tone}`);
    badge.textContent = prettyStatus(status);
    return badge;
  }

  function renderRows() {
    const query = elements.search.value.trim().toLocaleLowerCase();
    const status = elements.filter.value;
    const filtered = cases.filter((item) => {
      const matchesQuery = !query || `${item.subject_name} ${item.external_reference}`.toLocaleLowerCase().includes(query);
      return matchesQuery && (status === "all" || item.decision === status);
    });
    elements.rows.replaceChildren();
    if (!filtered.length) {
      const row = make("tr");
      const cell = make("td", "empty-cell", cases.length ? "No cases match these filters." : "No screening cases yet. Create one to get started.");
      cell.colSpan = 6;
      row.append(cell);
      elements.rows.append(row);
      byId("results-count").textContent = cases.length ? "No matching cases" : "Showing 0 cases";
      return;
    }
    for (const item of filtered) {
      const row = make("tr");
      const subjectCell = make("td");
      const subject = make("div", "subject-cell");
      subject.append(make("span", "subject-avatar", avatarText(item.subject_name)), make("span", "", item.subject_name));
      subjectCell.append(subject);
      const reference = make("td", "reference", item.external_reference);
      const statusCell = make("td");
      statusCell.append(makeStatus(item.decision || item.status));
      const vendors = Object.fromEntries((item.results || []).map((result) => [result.vendor, result]));
      const vendorCell = make("td");
      const chips = make("div", "vendor-mini");
      for (const [key, label] of [["kyc", "KYC"], ["sanctions", "Sanctions"]]) {
        const state = vendorState(vendors[key]);
        chips.append(make("span", `vendor-chip ${state.className}`, `${label}: ${state.text}`));
      }
      vendorCell.append(chips);
      const created = make("td", "", formatDate(item.created_at));
      const actionCell = make("td");
      const openButton = make("button", "row-open", "›");
      openButton.type = "button";
      openButton.setAttribute("aria-label", `View ${item.subject_name}`);
      openButton.addEventListener("click", () => openDetails(item.id));
      actionCell.append(openButton);
      row.append(subjectCell, reference, statusCell, vendorCell, created, actionCell);
      elements.rows.append(row);
    }
    byId("results-count").textContent = `Showing ${filtered.length} of ${cases.length} cases`;
  }

  function renderMetrics() {
    byId("total-count").textContent = cases.length;
    byId("nav-count").textContent = cases.length;
    byId("progress-count").textContent = cases.filter((item) => item.decision === "PENDING").length;
    byId("review-count").textContent = cases.filter((item) => item.decision === "NEEDS_REVIEW").length;
    byId("clear-count").textContent = cases.filter((item) => item.decision === "CLEARED").length;
  }

  async function loadCases({ quiet = false } = {}) {
    if (loading || !authenticated) return;
    loading = true;
    try {
      cases = await api("/v1/cases?limit=100");
      renderMetrics();
      renderRows();
      if (selectedCaseId && !elements.detailBackdrop.classList.contains("hidden")) renderDetails(selectedCaseId);
      if (!quiet) byId("results-count").textContent = cases.length ? `Showing latest ${cases.length} cases` : "Showing 0 cases";
    } catch (error) {
      if (error.status === 401) {
        authenticated = false;
        byId("app-shell").classList.add("hidden");
        byId("auth-screen").classList.remove("hidden");
        toast("Your session expired. Sign in again.", "error");
        return;
      }
      if (!quiet || !cases.length) {
        elements.rows.replaceChildren();
        const row = make("tr");
        const cell = make("td", "empty-cell", `Could not load cases. ${error.message}`);
        cell.colSpan = 6;
        row.append(cell);
        elements.rows.append(row);
        byId("results-count").textContent = "Connection issue";
      }
    } finally {
      loading = false;
    }
  }

  function openForm() {
    elements.formBackdrop.classList.remove("hidden");
    byId("subject-name").focus();
  }

  function closeForm() {
    elements.formBackdrop.classList.add("hidden");
    elements.formAlert.classList.add("hidden");
  }

  function renderDetails(id) {
    const item = cases.find((candidate) => candidate.id === id);
    if (!item) return;
    elements.detail.replaceChildren();
    elements.detail.append(make("div", "detail-kicker", "SCREENING CASE"));
    elements.detail.append(make("h2", "detail-title", item.subject_name));
    elements.detail.append(make("div", "detail-reference", item.external_reference));
    const statusLine = make("div", "detail-status");
    statusLine.append(makeStatus(item.decision || item.status));
    elements.detail.append(statusLine);

    const decision = make("section", "decision-summary");
    decision.append(make("strong", "", item.decision || "PENDING"));
    decision.append(make("p", "", item.reason || "Required provider results are pending or unavailable."));
    decision.append(make("small", "", item.review_required ? "Human review required" : "Automated demo outcome"));
    if (item.confidence !== null && item.confidence !== undefined) {
      decision.append(make("small", "", ` · Confidence ${Math.round(item.confidence * 100)}%`));
    }
    elements.detail.append(decision);

    const metadata = make("section", "detail-section");
    metadata.append(make("h3", "", "Subject details"));
    const grid = make("div", "detail-meta");
    for (const [label, value] of [["Date of birth", item.date_of_birth || "Not provided"], ["Country", item.country || "Not provided"], ["Submitted", formatDate(item.created_at)], ["Attempts", item.attempts]]) {
      const cell = make("div");
      cell.append(make("small", "", label), make("strong", "", value));
      grid.append(cell);
    }
    metadata.append(grid);
    elements.detail.append(metadata);

    const checks = make("section", "detail-section");
    checks.append(make("h3", "", "Vendor results"));
    const results = item.results || [];
    for (const vendorName of ["kyc", "sanctions"]) {
      const result = results.find((candidate) => candidate.vendor === vendorName);
      const card = make("article", "result-card");
      const heading = make("div", "result-head");
      const title = vendorName === "kyc" ? "Identity verification" : "Sanctions screening";
      heading.append(make("span", "result-vendor", title));
      const state = vendorState(result);
      heading.append(make("span", `result-pill ${state.className === "hit" ? "flag" : ""}`, state.text));
      card.append(heading);
      if (result) {
        const outcome = make("small", "", `Outcome: ${result.outcome}${result.confidence === null ? "" : ` · Provider score ${Math.round(result.confidence * 100)}%`}`);
        card.append(outcome);
        const payload = make("pre", "result-payload", JSON.stringify(result.payload, null, 2));
        card.append(payload);
        if (result.error) card.append(make("small", "", `Provider error: ${result.error}`));
      } else {
        card.append(make("small", "", "This check is waiting to run."));
      }
      checks.append(card);
    }
    elements.detail.append(checks);
  }

  function openDetails(id) {
    selectedCaseId = id;
    renderDetails(id);
    elements.detailBackdrop.classList.remove("hidden");
  }

  function closeDetails() {
    elements.detailBackdrop.classList.add("hidden");
    selectedCaseId = null;
  }

  function setAuthMode(mode) {
    authMode = mode;
    const registering = mode === "register";
    byId("auth-title").textContent = registering ? "Create your account" : "Welcome back";
    byId("auth-subtitle").textContent = registering
      ? "Use your work email to set up a private workspace."
      : "Sign in to continue to your workspace.";
    byId("auth-submit").replaceChildren(document.createTextNode(registering ? "Create account " : "Sign in "), make("span", "", "→"));
    byId("confirm-password-wrap").classList.toggle("hidden", !registering);
    byId("auth-password").autocomplete = registering ? "new-password" : "current-password";
    byId("auth-confirm-password").required = registering;
    byId("auth-switch-copy").replaceChildren(
      document.createTextNode(registering ? "Already have an account? " : "New here? "),
      (() => {
        const button = make("button", "", registering ? "Sign in" : "Create an account");
        button.type = "button";
        button.id = "auth-switch";
        return button;
      })(),
    );
    byId("auth-switch").addEventListener("click", () => setAuthMode(registering ? "login" : "register"), { once: true });
    byId("auth-alert").classList.add("hidden");
  }

  function enterWorkspace(user) {
    authenticated = true;
    byId("auth-screen").classList.add("hidden");
    byId("app-shell").classList.remove("hidden");
    const email = user.email || "Account";
    const initials = avatarText(email.split("@")[0]) || "U";
    byId("user-name").textContent = email;
    byId("sidebar-email").textContent = "Signed in";
    byId("user-avatar").textContent = initials;
    byId("top-avatar").textContent = initials;
    loadCases();
  }

  async function bootstrap() {
    try {
      const csrf = await api("/auth/csrf");
      csrfToken = csrf.csrf_token;
      try {
        enterWorkspace(await api("/auth/me"));
      } catch (error) {
        if (error.status !== 401) throw error;
        byId("auth-screen").classList.remove("hidden");
        setAuthMode("login");
        byId("auth-email").focus();
      }
    } catch (error) {
      byId("auth-alert").textContent = `Could not connect to the service. ${error.message}`;
      byId("auth-alert").classList.remove("hidden");
    }
  }

  byId("new-case-button").addEventListener("click", openForm);
  byId("refresh-button").addEventListener("click", () => loadCases());
  elements.search.addEventListener("input", renderRows);
  elements.filter.addEventListener("change", renderRows);
  document.querySelectorAll("[data-close='form']").forEach((button) => button.addEventListener("click", closeForm));
  document.querySelectorAll("[data-close='detail']").forEach((button) => button.addEventListener("click", closeDetails));
  elements.formBackdrop.addEventListener("click", (event) => { if (event.target === elements.formBackdrop) closeForm(); });
  elements.detailBackdrop.addEventListener("click", (event) => { if (event.target === elements.detailBackdrop) closeDetails(); });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { closeForm(); closeDetails(); }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      elements.search.focus();
    }
  });

  byId("auth-switch").addEventListener("click", () => setAuthMode("register"), { once: true });
  byId("auth-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const alert = byId("auth-alert");
    alert.classList.add("hidden");
    const email = byId("auth-email").value.trim().toLowerCase();
    const password = byId("auth-password").value;
    if (authMode === "register" && password !== byId("auth-confirm-password").value) {
      alert.textContent = "Those passwords do not match.";
      alert.classList.remove("hidden");
      return;
    }
    if (authMode === "register" && password.length < 8) {
      alert.textContent = "Choose a password with at least 8 characters.";
      alert.classList.remove("hidden");
      return;
    }
    const button = byId("auth-submit");
    button.disabled = true;
    button.textContent = authMode === "register" ? "Creating account…" : "Signing in…";
    try {
      const path = authMode === "register" ? "/auth/register" : "/auth/login";
      const user = await api(path, { method: "POST", body: JSON.stringify({ email, password }) });
      byId("auth-form").reset();
      enterWorkspace(user);
      toast(authMode === "register" ? "Your account is ready." : "Welcome back.");
    } catch (error) {
      alert.textContent = error.message || "Could not authenticate. Check your connection and try again.";
      alert.classList.remove("hidden");
    } finally {
      button.disabled = false;
      button.replaceChildren(document.createTextNode(authMode === "register" ? "Create account " : "Sign in "), make("span", "", "→"));
    }
  });

  byId("logout-button").addEventListener("click", async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch (error) {
      if (error.status !== 401) toast(error.message || "Could not sign out.", "error");
    }
    authenticated = false;
    cases = [];
    csrfToken = null;
    byId("app-shell").classList.add("hidden");
    byId("auth-screen").classList.remove("hidden");
    setAuthMode("login");
    try {
      const csrf = await api("/auth/csrf");
      csrfToken = csrf.csrf_token;
    } catch { /* The sign-in screen remains available; it will show an error on submit. */ }
  });

  elements.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    elements.formAlert.classList.add("hidden");
    const form = new FormData(elements.form);
    const name = String(form.get("subject_name") || "").trim();
    const reference = String(form.get("external_reference") || "").trim();
    const dob = String(form.get("date_of_birth") || "");
    const country = String(form.get("country") || "").trim().toUpperCase();
    if (!name || !reference) {
      elements.formAlert.textContent = "Full legal name and your reference are required.";
      elements.formAlert.classList.remove("hidden");
      return;
    }
    if (country !== "IN") {
      elements.formAlert.textContent = "This demonstration is scoped to India.";
      elements.formAlert.classList.remove("hidden");
      return;
    }
    elements.submit.disabled = true;
    elements.submit.textContent = "Submitting…";
    try {
      const created = await api("/v1/cases", {
        method: "POST",
        body: JSON.stringify({
          subject_name: name,
          external_reference: reference,
          ...(dob ? { date_of_birth: dob } : {}),
          ...(country ? { country } : {}),
        }),
      });
      elements.form.reset();
      closeForm();
      await loadCases({ quiet: true });
      openDetails(created.id);
      toast("Screening case submitted to the queue.");
    } catch (error) {
      elements.formAlert.textContent = error.message || "Could not submit the case. Check the connection and retry.";
      elements.formAlert.classList.remove("hidden");
    } finally {
      elements.submit.disabled = false;
      elements.submit.replaceChildren(document.createTextNode("Run screening "));
      elements.submit.append(make("span", "", "→"));
    }
  });

  document.querySelectorAll("[data-demo]").forEach((button) => button.addEventListener("click", () => {
    const scenarios = {
      clear: ["Asha Demo Kumar", "demo-cleared"],
      review: ["Sanction Demo Match", "demo-possible-match"],
      reject: ["Unverified Demo Applicant", "demo-identity-failed"],
    };
    const [name, reference] = scenarios[button.dataset.demo];
    byId("subject-name").value = name;
    byId("external-reference").value = `${reference}-${Date.now().toString(36)}`;
    byId("country").value = "IN";
  }));

  bootstrap();
  window.setInterval(() => loadCases({ quiet: true }), 5000);
})();
