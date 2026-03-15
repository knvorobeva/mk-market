import os
import re
import sqlite3
import json
import shutil
import zipfile
import difflib
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
import jwt
import httpx

APP_SECRET = os.getenv("APP_SECRET", "dev-secret-change")
JWT_ALG = "HS256"
TOKEN_EXPIRE_HOURS = 24
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))
PROJECTS_DIR = os.path.join(DATA_DIR, "projects")
DB_PATH = os.path.join(DATA_DIR, "app.db")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")

os.makedirs(PROJECTS_DIR, exist_ok=True)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

app = FastAPI()

app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


def create_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, APP_SECRET, algorithm=JWT_ALG)


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    token = creds.credentials
    try:
        payload = jwt.decode(token, APP_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_id = int(payload.get("sub", 0))
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, email FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="User not found")
    return {"id": row["id"], "email": row["email"]}


@app.post("/api/auth/register")
async def register(payload: dict):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="Invalid email")
    conn = db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, pwd_context.hash(password), datetime.utcnow().isoformat()),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")
    conn.close()
    return {"ok": True}


@app.post("/api/auth/login")
async def login(payload: dict):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, email, password_hash FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()
    if not row or not pwd_context.verify(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(row["id"], row["email"])
    return {"token": token}


@app.get("/api/me")
async def me(user=Depends(get_current_user)):
    return user


def project_root(project_id: int, user_id: int) -> str:
    root = os.path.join(PROJECTS_DIR, f"u{user_id}", f"p{project_id}")
    os.makedirs(root, exist_ok=True)
    return root


def secure_join(root: str, rel_path: str) -> str:
    rel_path = rel_path.lstrip("/\\")
    full = os.path.abspath(os.path.join(root, rel_path))
    if not full.startswith(root):
        raise HTTPException(status_code=400, detail="Invalid path")
    return full


def build_tree(root: str) -> List[dict]:
    tree = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        rel_base = os.path.relpath(base, root)
        for d in dirs:
            tree.append({"type": "dir", "path": os.path.normpath(os.path.join(rel_base, d))})
        for f in files:
            if f.startswith("."):
                continue
            tree.append({"type": "file", "path": os.path.normpath(os.path.join(rel_base, f))})
    tree = [t for t in tree if t["path"] not in (".", "..")]
    return sorted(tree, key=lambda x: (x["type"], x["path"]))


@app.get("/api/projects")
async def list_projects(user=Depends(get_current_user)):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, created_at FROM projects WHERE user_id = ? ORDER BY id DESC",
        (user["id"],),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.post("/api/projects")
async def create_project(payload: dict, user=Depends(get_current_user)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO projects (user_id, name, created_at) VALUES (?, ?, ?)",
        (user["id"], name, datetime.utcnow().isoformat()),
    )
    project_id = cur.lastrowid
    conn.commit()
    conn.close()
    project_root(project_id, user["id"])
    return {"id": project_id, "name": name}


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int, user=Depends(get_current_user)):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM projects WHERE id = ? AND user_id = ?", (project_id, user["id"]))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Project not found")
    cur.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()
    root = project_root(project_id, user["id"])
    if os.path.exists(root):
        shutil.rmtree(root)
    return {"ok": True}


@app.get("/api/projects/{project_id}/tree")
async def project_tree(project_id: int, user=Depends(get_current_user)):
    root = project_root(project_id, user["id"])
    return build_tree(root)


@app.get("/api/projects/{project_id}/file")
async def read_file(project_id: int, path: str, user=Depends(get_current_user)):
    root = project_root(project_id, user["id"])
    full = secure_join(root, path)
    if not os.path.exists(full) or not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="File not found")
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        return {"path": path, "content": f.read()}


@app.put("/api/projects/{project_id}/file")
async def write_file(project_id: int, payload: dict, user=Depends(get_current_user)):
    path = payload.get("path") or ""
    content = payload.get("content")
    if content is None:
        raise HTTPException(status_code=400, detail="Content required")
    root = project_root(project_id, user["id"])
    full = secure_join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return {"ok": True}


@app.post("/api/projects/{project_id}/upload")
async def upload_zip(project_id: int, file: UploadFile = File(...), user=Depends(get_current_user)):
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip supported")
    root = project_root(project_id, user["id"])
    tmp_path = os.path.join(DATA_DIR, "_upload.zip")
    with open(tmp_path, "wb") as f:
        f.write(await file.read())
    with zipfile.ZipFile(tmp_path, "r") as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            dest = secure_join(root, member.filename)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as out:
                out.write(src.read())
    os.remove(tmp_path)
    return {"ok": True}


async def call_groq(system: str, user_prompt: str) -> str:
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    body = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=headers, json=body)
    if resp.status_code >= 400:
        raise HTTPException(status_code=500, detail=f"Groq error: {resp.text}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


@app.post("/api/projects/{project_id}/ai/edit")
async def ai_edit(project_id: int, payload: dict, user=Depends(get_current_user)):
    path = payload.get("path") or ""
    instruction = (payload.get("instruction") or "").strip()
    apply_changes = bool(payload.get("apply", False))
    if not instruction:
        raise HTTPException(status_code=400, detail="Instruction required")

    root = project_root(project_id, user["id"])
    full = secure_join(root, path)
    if not os.path.exists(full) or not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="File not found")

    with open(full, "r", encoding="utf-8", errors="replace") as f:
        original = f.read()

    system = (
        "You are a senior software engineer. Return only the full updated file content, "
        "no markdown, no explanations. Preserve formatting where possible."
    )
    user_prompt = f"Instruction:\n{instruction}\n\nFile path: {path}\n\nCurrent file content:\n{original}"
    updated = await call_groq(system, user_prompt)

    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
        )
    )

    if apply_changes:
        with open(full, "w", encoding="utf-8") as f:
            f.write(updated)

    return {"diff": diff, "updated": updated}


@app.post("/api/projects/{project_id}/ai/patch")
async def ai_patch(project_id: int, payload: dict, user=Depends(get_current_user)):
    """Accept updated content from client and apply it with diff preview."""
    path = payload.get("path") or ""
    updated = payload.get("updated")
    if updated is None:
        raise HTTPException(status_code=400, detail="Updated content required")
    root = project_root(project_id, user["id"])
    full = secure_join(root, path)
    if not os.path.exists(full) or not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="File not found")
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        original = f.read()
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
        )
    )
    with open(full, "w", encoding="utf-8") as f:
        f.write(updated)
    return {"ok": True, "diff": diff}
