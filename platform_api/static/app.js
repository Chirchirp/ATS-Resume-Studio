const state = {
  token: sessionStorage.getItem("ats_token") || "",
  user: null,
  applications: [],
  activeApplication: null,
  resume: "",
  jobDescription: "",
  activeDocument: "resume",
  authMode: "login",
  currentJob: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && !path.startsWith("/v1/auth/")) {
    signOut();
    throw new Error("Your session expired. Please sign in again.");
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") {
        detail = data.detail;
      } else if (Array.isArray(data.detail)) {
        detail = data.detail
          .map((item) => item.msg || "Invalid value")
          .join(". ");
      }
    } catch (_) {}
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

function setMessage(id, text, success = false) {
  const element = $(id);
  element.textContent = text;
  element.style.color = success ? "var(--green)" : "var(--red)";
}

function showStudio() {
  $("auth-view").hidden = true;
  $("studio-view").hidden = false;
}

function showAuth() {
  $("studio-view").hidden = true;
  $("auth-view").hidden = false;
}

function signOut() {
  state.token = "";
  state.user = null;
  sessionStorage.removeItem("ats_token");
  showAuth();
}

async function authenticate(event) {
  event.preventDefault();
  setMessage("auth-message", "");
  const payload = {
    email: $("auth-email").value.trim(),
    password: $("auth-password").value,
  };
  try {
    const result = await api(`/v1/auth/${state.authMode}`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.token = result.access_token;
    sessionStorage.setItem("ats_token", state.token);
    await initializeStudio();
  } catch (error) {
    setMessage("auth-message", error.message);
  }
}

async function initializeStudio() {
  state.user = await api("/v1/me");
  const profile = await api("/v1/profile");
  state.resume = profile.master_resume || "";
  state.applications = await api("/v1/applications");
  showStudio();
  renderApplications();
  if (state.applications.length) {
    await selectApplication(state.applications[0].id);
  } else {
    newApplication();
  }
}

function renderApplications() {
  const container = $("application-list");
  container.replaceChildren();
  state.applications.forEach((application) => {
    const button = document.createElement("button");
    button.className = `application-item ${state.activeApplication?.id === application.id ? "active" : ""}`;
    button.type = "button";
    const role = document.createElement("strong");
    role.textContent = application.role;
    const company = document.createElement("small");
    company.textContent = application.company || "Company not set";
    button.append(role, company);
    button.addEventListener("click", () => selectApplication(application.id));
    container.append(button);
  });
}

function newApplication() {
  state.activeApplication = null;
  state.jobDescription = "";
  $("company").value = "";
  $("role").value = "";
  $("application-status").value = "draft";
  $("workspace-title").textContent = "New application";
  $("save-state").textContent = "Not saved";
  state.activeDocument = "job";
  setActiveDocument("job", true);
  renderVersions([]);
  clearAnalysis();
  renderApplications();
}

async function selectApplication(id) {
  state.activeApplication = await api(`/v1/applications/${id}`);
  state.jobDescription = state.activeApplication.job_description;
  $("company").value = state.activeApplication.company;
  $("role").value = state.activeApplication.role;
  $("application-status").value = state.activeApplication.status;
  $("workspace-title").textContent = state.activeApplication.role;
  $("save-state").textContent = "Saved";
  setActiveDocument("resume", true);
  const versions = await api(`/v1/applications/${id}/versions`);
  renderVersions(versions);
  renderApplications();
  clearAnalysis();
}

function currentEditorContent() {
  return $("document-editor").value;
}

function persistEditorDraft() {
  if (state.activeDocument === "resume") {
    state.resume = currentEditorContent();
  } else {
    state.jobDescription = currentEditorContent();
    if (state.activeApplication) {
      state.activeApplication.job_description = state.jobDescription;
    }
  }
}

function setActiveDocument(documentType, skipPersist = false) {
  if (!skipPersist) persistEditorDraft();
  state.activeDocument = documentType;
  document.querySelectorAll(".doc-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.document === documentType);
  });
  $("document-editor").value =
    documentType === "resume"
      ? state.resume
      : state.jobDescription;
  updateEditorStats(false);
}

function updateEditorStats(markDirty = true) {
  const text = currentEditorContent().trim();
  const words = text ? text.split(/\s+/).length : 0;
  $("editor-stats").textContent = `${words.toLocaleString()} words · ${text.length.toLocaleString()} characters`;
  if (markDirty) $("save-state").textContent = "Unsaved changes";
}

async function saveApplication() {
  persistEditorDraft();
  const payload = {
    company: $("company").value.trim(),
    role: $("role").value.trim(),
    status: $("application-status").value,
    job_description: state.jobDescription,
  };
  if (!payload.role || payload.job_description.length < 20) {
    alert("Add a target role and a complete job description first.");
    return;
  }
  try {
    if (state.activeApplication) {
      state.activeApplication = await api(`/v1/applications/${state.activeApplication.id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    } else {
      const { status: _, ...createPayload } = payload;
      state.activeApplication = await api("/v1/applications", {
        method: "POST",
        body: JSON.stringify(createPayload),
      });
    }
    state.jobDescription = state.activeApplication.job_description;
    $("workspace-title").textContent = state.activeApplication.role;
    $("save-state").textContent = "Saved";
    await saveProfileResume();
    state.applications = await api("/v1/applications");
    renderApplications();
  } catch (error) {
    alert(error.message);
  }
}

async function saveProfileResume() {
  const profile = await api("/v1/profile");
  await api("/v1/profile", {
    method: "PUT",
    body: JSON.stringify({
      display_name: profile.display_name || "",
      headline: profile.headline || "",
      master_resume: state.resume,
      preferences: profile.preferences || {},
    }),
  });
}

async function saveVersion() {
  persistEditorDraft();
  if (!state.activeApplication) {
    alert("Save the application before creating a document version.");
    return;
  }
  const content = state.activeDocument === "resume"
    ? state.resume
    : state.jobDescription;
  const label = $("version-label").value.trim() || `${state.activeDocument} version`;
  try {
    await api(`/v1/applications/${state.activeApplication.id}/versions`, {
      method: "POST",
      body: JSON.stringify({
        kind: state.activeDocument === "resume" ? "resume" : "notes",
        label,
        content,
        metadata: { source: "platform-editor" },
      }),
    });
    $("version-label").value = "";
    renderVersions(await api(`/v1/applications/${state.activeApplication.id}/versions`));
  } catch (error) {
    alert(error.message);
  }
}

function renderVersions(versions) {
  $("version-count").textContent = String(versions.length);
  const container = $("version-list");
  container.replaceChildren();
  versions.slice(0, 8).forEach((version) => {
    const item = document.createElement("div");
    item.className = "version-item";
    const title = document.createElement("strong");
    title.textContent = version.label;
    const meta = document.createElement("span");
    meta.textContent = `${version.kind} · ${new Date(version.created_at).toLocaleString()}`;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Open";
    button.addEventListener("click", async () => {
      const full = await api(`/v1/versions/${version.id}`);
      state.activeDocument = full.kind === "resume" ? "resume" : "job";
      if (state.activeDocument === "resume") state.resume = full.content;
      setActiveDocument(state.activeDocument, true);
      $("document-editor").value = full.content;
      updateEditorStats();
    });
    item.append(title, meta, button);
    container.append(item);
  });
  if (!versions.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No saved versions.";
    container.append(empty);
  }
}

async function runAnalysis() {
  persistEditorDraft();
  if (!state.activeApplication) {
    await saveApplication();
    if (!state.activeApplication) return;
  }
  if (state.resume.length < 20) {
    alert("Add your master resume before running alignment.");
    return;
  }
  $("job-status").textContent = "Queued";
  try {
    const job = await api("/v1/jobs/alignment", {
      method: "POST",
      body: JSON.stringify({
        application_id: state.activeApplication.id,
        job_description: state.jobDescription,
        resume: state.resume,
      }),
    });
    state.currentJob = job.id;
    pollJob(job.id);
  } catch (error) {
    $("job-status").textContent = "Failed";
    alert(error.message);
  }
}

async function pollJob(id) {
  try {
    const job = await api(`/v1/jobs/${id}`);
    $("job-status").textContent = job.status;
    if (job.status === "complete") {
      renderAnalysis(job.result);
      return;
    }
    if (job.status === "failed") {
      throw new Error(job.error || "Analysis failed.");
    }
    window.setTimeout(() => pollJob(id), 700);
  } catch (error) {
    $("job-status").textContent = "Failed";
    alert(error.message);
  }
}

function clearAnalysis() {
  $("alignment-score").textContent = "—";
  $("alignment-confidence").textContent = "Run analysis to calculate";
  $("job-status").textContent = "Idle";
  $("dimension-list").innerHTML = '<p class="empty-state">Your explainable score will appear here.</p>';
  $("gap-list").innerHTML = '<li class="empty-state">No analysis yet.</li>';
}

function renderAnalysis(result) {
  const report = result.alignment;
  $("alignment-score").textContent = `${report.score}%`;
  $("alignment-confidence").textContent = `${report.confidence} confidence`;
  const dimensions = $("dimension-list");
  dimensions.replaceChildren();
  report.dimensions.forEach((dimension) => {
    const row = document.createElement("div");
    row.className = "dimension";
    const label = document.createElement("span");
    label.textContent = dimension.label;
    const value = document.createElement("strong");
    value.textContent = `${dimension.score.toFixed(1)}/${dimension.maximum}`;
    const bar = document.createElement("div");
    bar.className = "dimension-bar";
    const fill = document.createElement("i");
    fill.style.width = `${Math.min(100, dimension.score / dimension.maximum * 100)}%`;
    bar.append(fill);
    row.append(label, value, bar);
    dimensions.append(row);
  });
  const gaps = $("gap-list");
  gaps.replaceChildren();
  const missing = [...report.missing_required, ...report.missing_preferred];
  missing.slice(0, 8).forEach((gap) => {
    const item = document.createElement("li");
    item.textContent = gap;
    gaps.append(item);
  });
  if (!missing.length) {
    const item = document.createElement("li");
    item.textContent = "No extracted requirement gaps.";
    gaps.append(item);
  }
}

async function updateRetention() {
  try {
    await api("/v1/privacy/retention", {
      method: "PUT",
      body: JSON.stringify({ retention_days: Number($("retention-days").value) }),
    });
    setMessage("privacy-message", "Retention preference updated.", true);
  } catch (error) {
    setMessage("privacy-message", error.message);
  }
}

async function exportData() {
  try {
    const data = await api("/v1/privacy/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "ats-resume-studio-export.json";
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) {
    setMessage("privacy-message", error.message);
  }
}

async function deleteAccount() {
  try {
    await api("/v1/privacy/account", {
      method: "DELETE",
      body: JSON.stringify({
        password: $("delete-password").value,
        confirmation: $("delete-confirmation").value,
      }),
    });
    signOut();
  } catch (error) {
    setMessage("privacy-message", error.message);
  }
}

$("auth-form").addEventListener("submit", authenticate);
$("auth-mode").addEventListener("click", () => {
  state.authMode = state.authMode === "login" ? "register" : "login";
  $("auth-heading").textContent = state.authMode === "login" ? "Sign in" : "Create account";
  $("auth-mode").textContent = state.authMode === "login" ? "Create a new account" : "I already have an account";
  $("auth-password").autocomplete = state.authMode === "login" ? "current-password" : "new-password";
  setMessage("auth-message", "");
});
$("sign-out").addEventListener("click", signOut);
$("new-application").addEventListener("click", newApplication);
$("save-application").addEventListener("click", saveApplication);
$("save-version").addEventListener("click", saveVersion);
$("run-analysis").addEventListener("click", runAnalysis);
$("document-editor").addEventListener("input", updateEditorStats);
["company", "role", "application-status"].forEach((id) => {
  $(id).addEventListener("input", () => {
    $("save-state").textContent = "Unsaved changes";
  });
});
document.querySelectorAll(".doc-tab").forEach((button) => {
  button.addEventListener("click", () => setActiveDocument(button.dataset.document));
});
$("privacy-button").addEventListener("click", () => $("privacy-dialog").showModal());
$("save-retention").addEventListener("click", updateRetention);
$("export-data").addEventListener("click", exportData);
$("delete-account").addEventListener("click", deleteAccount);

if (state.token) {
  initializeStudio().catch(() => signOut());
} else {
  showAuth();
}
