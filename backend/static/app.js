const API = "";
let token = localStorage.getItem("token") || "";
let currentProject = null;
let currentPath = "";
let editor = null;
let lastAIUpdated = "";

const authCard = document.getElementById("auth");
const workspace = document.getElementById("workspace");
const authMsg = document.getElementById("auth-msg");
const aiMsg = document.getElementById("ai-msg");
const aiDiff = document.getElementById("ai-diff");
const aiApply = document.getElementById("ai-apply");

function setMsg(el, msg) {
  el.textContent = msg || "";
}

function authHeaders() {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Ошибка запроса");
  }
  return res.json();
}

function showWorkspace(user) {
  authCard.classList.add("hidden");
  workspace.classList.remove("hidden");
  document.getElementById("user-email").textContent = user.email;
}

async function bootstrap() {
  if (!token) return;
  try {
    const me = await api("/api/me");
    showWorkspace(me);
    await loadProjects();
  } catch (e) {
    token = "";
    localStorage.removeItem("token");
  }
}

function initAuthTabs() {
  const loginTab = document.getElementById("tab-login");
  const registerTab = document.getElementById("tab-register");
  const loginForm = document.getElementById("login-form");
  const registerForm = document.getElementById("register-form");

  loginTab.addEventListener("click", () => {
    loginTab.classList.add("active");
    registerTab.classList.remove("active");
    loginForm.classList.remove("hidden");
    registerForm.classList.add("hidden");
  });

  registerTab.addEventListener("click", () => {
    registerTab.classList.add("active");
    loginTab.classList.remove("active");
    registerForm.classList.remove("hidden");
    loginForm.classList.add("hidden");
  });

  document.getElementById("login-btn").addEventListener("click", async () => {
    setMsg(authMsg, "");
    try {
      const email = document.getElementById("login-email").value;
      const password = document.getElementById("login-password").value;
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      token = data.token;
      localStorage.setItem("token", token);
      const me = await api("/api/me");
      showWorkspace(me);
      await loadProjects();
    } catch (e) {
      setMsg(authMsg, e.message);
    }
  });

  document.getElementById("register-btn").addEventListener("click", async () => {
    setMsg(authMsg, "");
    try {
      const email = document.getElementById("register-email").value;
      const password = document.getElementById("register-password").value;
      await api("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setMsg(authMsg, "Пользователь создан. Можно войти.");
    } catch (e) {
      setMsg(authMsg, e.message);
    }
  });
}

async function loadProjects() {
  const list = await api("/api/projects");
  const container = document.getElementById("projects");
  container.innerHTML = "";
  list.forEach((p) => {
    const item = document.createElement("div");
    item.className = "item" + (currentProject && currentProject.id === p.id ? " active" : "");
    item.textContent = p.name;
    item.addEventListener("click", async () => {
      currentProject = p;
      currentPath = "";
      aiDiff.textContent = "";
      aiApply.disabled = true;
      await loadProjects();
      await loadTree();
      setCurrentPath("Файл не выбран");
      if (editor) editor.setValue("");
    });
    const del = document.createElement("span");
    del.textContent = "×";
    del.style.color = "#ef4444";
    del.style.marginLeft = "8px";
    del.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Удалить проект?")) return;
      await api(`/api/projects/${p.id}`, { method: "DELETE" });
      if (currentProject && currentProject.id === p.id) currentProject = null;
      await loadProjects();
      await loadTree();
    });
    item.appendChild(del);
    container.appendChild(item);
  });
}

async function loadTree() {
  const container = document.getElementById("tree");
  container.innerHTML = "";
  if (!currentProject) return;
  const tree = await api(`/api/projects/${currentProject.id}/tree`);
  if (!tree.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "Нет файлов";
    container.appendChild(empty);
    return;
  }
  tree.filter((n) => n.type === "file").forEach((node) => {
    const item = document.createElement("div");
    item.className = "item" + (currentPath === node.path ? " active" : "");
    item.textContent = node.path;
    item.addEventListener("click", async () => {
      await openFile(node.path);
      await loadTree();
    });
    container.appendChild(item);
  });
}

function setCurrentPath(path) {
  document.getElementById("current-path").textContent = path;
}

async function openFile(path) {
  if (!currentProject) return;
  const data = await api(`/api/projects/${currentProject.id}/file?path=${encodeURIComponent(path)}`);
  currentPath = path;
  setCurrentPath(path);
  if (editor) editor.setValue(data.content);
}

async function saveFile() {
  if (!currentProject || !currentPath) return;
  await api(`/api/projects/${currentProject.id}/file`, {
    method: "PUT",
    body: JSON.stringify({ path: currentPath, content: editor.getValue() }),
  });
}

function initWorkspaceActions() {
  document.getElementById("logout").addEventListener("click", () => {
    token = "";
    localStorage.removeItem("token");
    location.reload();
  });

  document.getElementById("new-project").addEventListener("click", async () => {
    const name = prompt("Название проекта");
    if (!name) return;
    await api("/api/projects", { method: "POST", body: JSON.stringify({ name }) });
    await loadProjects();
  });

  document.getElementById("save-file").addEventListener("click", async () => {
    try {
      await saveFile();
    } catch (e) {
      alert(e.message);
    }
  });

  document.getElementById("new-file").addEventListener("click", async () => {
    if (!currentProject) return alert("Выберите проект");
    const path = prompt("Путь файла, например index.html");
    if (!path) return;
    await api(`/api/projects/${currentProject.id}/file`, {
      method: "PUT",
      body: JSON.stringify({ path, content: "" }),
    });
    await loadTree();
  });

  document.getElementById("upload-zip").addEventListener("change", async (e) => {
    if (!currentProject) return alert("Выберите проект");
    const file = e.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`/api/projects/${currentProject.id}/upload`, {
      method: "POST",
      headers: { ...authHeaders() },
      body: form,
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      alert(data.detail || "Ошибка загрузки");
      return;
    }
    await loadTree();
  });

  document.getElementById("ai-preview").addEventListener("click", async () => {
    setMsg(aiMsg, "");
    aiDiff.textContent = "";
    aiApply.disabled = true;
    if (!currentProject || !currentPath) return setMsg(aiMsg, "Выберите файл");
    const instruction = document.getElementById("ai-instruction").value.trim();
    if (!instruction) return setMsg(aiMsg, "Введите задачу");
    try {
      const data = await api(`/api/projects/${currentProject.id}/ai/edit`, {
        method: "POST",
        body: JSON.stringify({ path: currentPath, instruction, apply: false }),
      });
      lastAIUpdated = data.updated;
      aiDiff.textContent = data.diff || "(без изменений)";
      aiApply.disabled = !data.diff;
    } catch (e) {
      setMsg(aiMsg, e.message);
    }
  });

  aiApply.addEventListener("click", async () => {
    if (!lastAIUpdated) return;
    try {
      await api(`/api/projects/${currentProject.id}/ai/patch`, {
        method: "POST",
        body: JSON.stringify({ path: currentPath, updated: lastAIUpdated }),
      });
      if (editor) editor.setValue(lastAIUpdated);
      aiApply.disabled = true;
    } catch (e) {
      setMsg(aiMsg, e.message);
    }
  });
}

function initEditor() {
  window.require.config({ paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs" } });
  window.require(["vs/editor/editor.main"], () => {
    editor = monaco.editor.create(document.getElementById("editor"), {
      value: "",
      language: "plaintext",
      theme: "vs-dark",
      fontFamily: "Source Code Pro",
      fontSize: 14,
      automaticLayout: true,
    });
  });
}

initAuthTabs();
initWorkspaceActions();
initEditor();
bootstrap();
