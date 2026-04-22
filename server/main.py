import os
import re
import json
import html
import sqlite3
import smtplib
import random
import string
import urllib.parse
import urllib.request
import urllib.error
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import jwt
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Response, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext

APP_SECRET = os.getenv("APP_SECRET", "change-me")
JWT_ALG = "HS256"
TOKEN_EXPIRE_HOURS = 24
LOGIN_CODE_MAX_ATTEMPTS = 5
LOGIN_CODE_LOCK_MINUTES = 15
DB_PATH = os.getenv("DB_PATH", "app.db")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "1") in ("1", "true", "yes", "on")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)
app = FastAPI()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


WORKSHOP_TYPE_VALUES = ("Групповой МК", "Индивидуальный МК", "МК-Свидание")


def normalize_workshop_type(value: str, description: str = "") -> str:
    text = (value or "").strip()
    if text in WORKSHOP_TYPE_VALUES:
        return text

    source = f"{text} {description or ''}".casefold()
    if "свидан" in source:
        return "МК-Свидание"
    if "индив" in source:
        return "Индивидуальный МК"
    if "груп" in source:
        return "Групповой МК"
    return "Групповой МК"


def normalize_workshop_capacity(workshop_type: str, capacity_value: int) -> int:
    normalized_type = normalize_workshop_type(workshop_type)
    if normalized_type == "Индивидуальный МК":
        return 1
    if normalized_type == "МК-Свидание":
        return 2
    return max(1, int(capacity_value or 6))


def workshop_types_from_csv(raw_value: str, fallback_type: str = "") -> list[str]:
    raw_parts = [str(part or "").strip() for part in str(raw_value or "").split(",")]
    parts = [part for part in raw_parts if part]
    if not parts and fallback_type:
        parts = [str(fallback_type).strip()]

    seen = set()
    for part in parts:
        seen.add(normalize_workshop_type(part))

    if not seen:
        seen.add(normalize_workshop_type(fallback_type or "Групповой МК"))

    ordered = [value for value in WORKSHOP_TYPE_VALUES if value in seen]
    return ordered


def workshop_types_label(workshop_types: list[str]) -> str:
    items = [str(item or "").strip() for item in workshop_types if str(item or "").strip()]
    return ", ".join(items) if items else "Групповой МК"


def db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 20000")
    return conn


def user_view(row: sqlite3.Row | dict) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "name": row["name"],
        "avatar_url": row["avatar_url"],
        "phone": row["phone"],
        "bio": row["bio"],
        "address": row["address"],
    }


def account_view(row: sqlite3.Row | dict) -> dict:
    data = user_view(row)
    email_verified = bool(int(row["email_verified"] or 0))
    data["email_verified"] = email_verified
    data["needs_email_verification"] = not email_verified
    return data


def create_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": utc_now() + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, APP_SECRET, algorithm=JWT_ALG)


def generate_verify_code(length: int = 6) -> str:
    return "".join(random.choice(string.digits) for _ in range(length))


def get_login_code_lock_until(cur: sqlite3.Cursor, email: str) -> Optional[datetime]:
    cur.execute(
        """
        SELECT locked_until
        FROM login_codes
        WHERE email = ?
          AND purpose = 'login'
          AND locked_until IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (email,),
    )
    row = cur.fetchone()
    if not row or not row["locked_until"]:
        return None
    try:
        locked_until = parse_dt(str(row["locked_until"]))
    except Exception:
        return None
    if locked_until <= utc_now():
        return None
    return locked_until


def log_action(user_id: int, action: str, payload: Optional[dict] = None):
    conn = None
    try:
        conn = db()
        conn.execute(
            "INSERT INTO user_actions (user_id, action, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (user_id, action, json.dumps(payload or {}, ensure_ascii=False), utc_now_iso()),
        )
        conn.commit()
    except sqlite3.OperationalError as error:
        print(f"[WARN] log_action skipped ({action}): {error}")
    finally:
        if conn:
            conn.close()


def random_state_token(length: int = 40) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def json_request(url: str, method: str = "GET", data: Optional[dict] = None, headers: Optional[dict] = None):
    raw = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=raw, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8") or "{}"
            return response.getcode(), json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") or "{}"
        payload = json.loads(body) if body.startswith("{") else {"detail": body}
        return exc.code, payload
    except Exception as exc:
        return 599, {"detail": str(exc)}


def run_safe_task(label: str, func, *args):
    try:
        func(*args)
    except Exception as exc:
        print(f"[BACKGROUND-FAIL] {label}: {exc}")


def enqueue_task(background_tasks: Optional[BackgroundTasks], label: str, func, *args):
    if background_tasks is None:
        run_safe_task(label, func, *args)
        return
    background_tasks.add_task(run_safe_task, label, func, *args)


def sync_user_google_bookings(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM bookings WHERE user_id = ? AND status = 'booked'",
        (user_id,),
    )
    booking_ids = [int(row["id"]) for row in cur.fetchall()]
    conn.close()
    for booking_id in booking_ids:
        sync_booking_with_google(user_id, booking_id)


def send_email_notification(
    email: str,
    notif_type: str,
    subject: str,
    body: str,
    payload: Optional[dict] = None,
    main_text: Optional[str] = None,
):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO notifications (user_id, channel, notif_type, payload_json, status, created_at)
        SELECT id, 'email', ?, ?, 'queued', ?
        FROM users
        WHERE email = ?
        """,
        (notif_type, json.dumps(payload or {}, ensure_ascii=False), utc_now_iso(), email),
    )
    conn.commit()
    notif_id = cur.lastrowid

    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and SMTP_FROM):
        print(f"[EMAIL-SKIP] SMTP not configured to={email} type={notif_type}")
        if notif_id:
            cur.execute("UPDATE notifications SET status = 'failed' WHERE id = ?", (notif_id,))
            conn.commit()
        conn.close()
        return

    try:
        payload_data = payload or {}
        effective_main_text = (main_text or "").strip()
        if not effective_main_text:
            if notif_type == "register_verify" and payload_data.get("verify_code"):
                effective_main_text = f"КОД ПОДТВЕРЖДЕНИЯ: {payload_data['verify_code']}"
            elif notif_type == "login_code" and payload_data.get("code"):
                effective_main_text = f"КОД ДЛЯ ВХОДА: {payload_data['code']}"
            else:
                lines = [line.strip() for line in body.splitlines() if line.strip()]
                effective_main_text = lines[0] if lines else "Важное уведомление МК-Маркет"

        actions = {
            "register_verify": "Открой страницу входа и регистрации, введи код подтверждения в блоке «Подтверждение почты», затем выполни вход.",
            "login_code": "Нажми «Забыли пароль? Вход по коду», введи код из письма и заверши вход в личный кабинет.",
            "booking": "Проверь раздел «Мои записи» в личном кабинете. При необходимости добавь событие в календарь с сайта.",
            "cancel": "Если хочешь, можешь выбрать другой слот и записаться снова на странице мастер-класса.",
            "queue_promoted": "Проверь «Мои записи»: заявка уже переведена из очереди в подтвержденную запись.",
        }
        action_text = actions.get(notif_type, "Проверь актуальный статус в личном кабинете МК-Маркет.")

        plain_body = (
            f"{body}\n\n"
            "Почему вы получили это письмо:\n"
            "Это автоматическое уведомление сервиса МК-Маркет о действии в вашем аккаунте.\n\n"
            "Что делать дальше:\n"
            f"{action_text}\n\n"
            "Если это действие выполняли не вы:\n"
            "Смените пароль в личном кабинете и свяжитесь с поддержкой.\n\n"
            "Поддержка: support@mkmarket.ru\n"
            "МК-Маркет"
        )

        html_body = f"""\
<!doctype html>
<html lang="ru">
  <body style="margin:0;padding:0;background:#fff6fb;font-family:Arial,sans-serif;color:#2f1a29;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#fff6fb;padding:24px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;background:#ffffff;border:1px solid #f4c8db;border-radius:16px;overflow:hidden;">
            <tr>
              <td style="padding:20px 22px;background:linear-gradient(135deg,#ea4b95,#ff79b5);color:#ffffff;">
                <div style="font-size:24px;font-weight:700;line-height:1.2;">МК-Маркет</div>
                <div style="font-size:14px;opacity:0.95;margin-top:6px;">Уведомление по вашему аккаунту</div>
              </td>
            </tr>
            <tr>
              <td style="padding:22px;">
                <h2 style="margin:0 0 14px 0;font-size:22px;line-height:1.25;color:#2f1a29;">{html.escape(subject)}</h2>
                <div style="margin:0 0 18px 0;padding:14px 16px;border-radius:12px;background:#ffe6f1;border-left:6px solid #ea4b95;font-size:20px;font-weight:700;color:#9b2256;">
                  {html.escape(effective_main_text)}
                </div>
                <div style="font-size:15px;line-height:1.7;color:#55364a;white-space:pre-line;">{html.escape(body)}</div>
                <div style="margin-top:18px;padding:14px 16px;border-radius:12px;background:#fff5fa;border:1px solid #f3d0df;">
                  <div style="font-size:14px;font-weight:700;margin-bottom:6px;color:#6d3e58;">Что делать дальше</div>
                  <div style="font-size:14px;line-height:1.6;color:#6d3e58;">{html.escape(action_text)}</div>
                </div>
                <div style="margin-top:18px;font-size:13px;line-height:1.6;color:#8a6176;">
                  Это автоматическое письмо МК-Маркет. Если действие выполняли не вы — смените пароль и напишите в поддержку: support@mkmarket.ru
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = email
        msg.set_content(plain_body)
        msg.add_alternative(html_body, subtype="html")

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            if SMTP_STARTTLS:
                server.starttls()
                server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

        if notif_id:
            cur.execute(
                "UPDATE notifications SET status = 'sent', sent_at = ? WHERE id = ?",
                (utc_now_iso(), notif_id),
            )
            conn.commit()
        print(f"[EMAIL-SENT] to={email} type={notif_type}")
    except Exception as exc:
        print(f"[EMAIL-FAIL] to={email} type={notif_type} error={exc}")
        if notif_id:
            cur.execute("UPDATE notifications SET status = 'failed' WHERE id = ?", (notif_id,))
            conn.commit()
    finally:
        conn.close()


def send_booking_notification(email: str, action: str, details: str):
    subjects = {
        "booking": "МК-Маркет: статус вашей записи",
        "cancel": "МК-Маркет: запись отменена",
        "queue_promoted": "МК-Маркет: вас перевели из очереди",
    }
    bodies = {
        "booking": "Ваша запись обновлена.",
        "cancel": "Ваша запись на мастер-класс отменена.",
        "queue_promoted": "Вы переведены из очереди в подтвержденную запись.",
    }
    subject = subjects.get(action, "МК-Маркет: уведомление")
    body = (
        f"{bodies.get(action, 'Обновление по вашей записи.')}\n\n"
        f"Детали: {details}\n\n"
        "МК-Маркет"
    )
    send_email_notification(
        email=email,
        notif_type=action,
        subject=subject,
        body=body,
        payload={"details": details},
        main_text=bodies.get(action, "Обновление по вашей записи."),
    )


def google_calendar_url(title: str, start_at: str, end_at: str, location: str = "", details: str = "") -> str:
    start = parse_dt(start_at).strftime("%Y%m%dT%H%M%SZ")
    end = parse_dt(end_at).strftime("%Y%m%dT%H%M%SZ")
    params = {
        "action": "TEMPLATE",
        "text": title or "МК-Маркет",
        "dates": f"{start}/{end}",
        "location": location or "",
        "details": details or "",
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(params)


def get_google_integration(user_id: int) -> Optional[dict]:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM calendar_integrations WHERE user_id = ? AND provider = 'google'",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def save_google_integration(user_id: int, access_token: str, refresh_token: Optional[str], expires_in: Optional[int]):
    expiry = utc_now() + timedelta(seconds=int(expires_in or 3600))
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO calendar_integrations (user_id, provider, access_token, refresh_token, token_expiry, created_at, updated_at)
        VALUES (?, 'google', ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, provider) DO UPDATE SET
            access_token = excluded.access_token,
            refresh_token = COALESCE(excluded.refresh_token, calendar_integrations.refresh_token),
            token_expiry = excluded.token_expiry,
            updated_at = excluded.updated_at
        """,
        (user_id, access_token, refresh_token, expiry.isoformat(), utc_now_iso(), utc_now_iso()),
    )
    conn.commit()
    conn.close()


def refresh_google_access_token(integration: dict) -> Optional[dict]:
    refresh_token = integration.get("refresh_token")
    if not refresh_token or not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return None
    code, token_data = json_request(
        "https://oauth2.googleapis.com/token",
        method="POST",
        data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        headers={"Content-Type": "application/json"},
    )
    if code != 200:
        return None
    save_google_integration(
        user_id=integration["user_id"],
        access_token=token_data.get(
            "access_token",
            integration.get("access_token"),
        ),
        refresh_token=refresh_token,
        expires_in=token_data.get("expires_in", 3600),
    )
    return get_google_integration(integration["user_id"])


def ensure_google_access_token(integration: dict) -> dict:
    expiry_raw = integration.get("token_expiry")
    if not expiry_raw:
        return integration
    expiry = parse_dt(expiry_raw)
    if expiry - utc_now() > timedelta(seconds=60):
        return integration
    refreshed = refresh_google_access_token(integration)
    if not refreshed:
        return integration
    return refreshed


def google_api_request(
    integration: dict,
    path: str,
    method: str = "GET",
    data: Optional[dict] = None,
    params: Optional[dict] = None,
):
    active = ensure_google_access_token(integration)
    token = active.get("access_token")
    if not token:
        return 401, {"detail": "google token missing"}, active
    url = f"https://www.googleapis.com/calendar/v3{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    code, payload = json_request(
        url,
        method=method,
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    if code == 401:
        refreshed = refresh_google_access_token(active)
        if refreshed:
            code, payload = json_request(
                url,
                method=method,
                data=data,
                headers={
                    "Authorization": f"Bearer {refreshed.get('access_token')}",
                    "Content-Type": "application/json",
                },
            )
            return code, payload, refreshed
    return code, payload, active


def sync_booking_with_google(user_id: int, booking_id: int):
    integration = get_google_integration(user_id)
    if not integration:
        return

    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.id, b.status, b.guests, s.start_at, s.end_at, w.title, w.location
        FROM bookings b
        JOIN workshop_slots s ON s.id = b.slot_id
        JOIN workshops w ON w.id = s.workshop_id
        WHERE b.id = ? AND b.user_id = ?
        """,
        (booking_id, user_id),
    )
    booking = cur.fetchone()
    cur.execute(
        "SELECT id, external_event_id FROM booking_external_events WHERE booking_id = ? AND provider = 'google'",
        (booking_id,),
    )
    link = cur.fetchone()
    conn.close()

    if not booking:
        return

    event_payload = {
        "summary": booking["title"],
        "location": booking["location"] or "",
        "description": f"МК-Маркет\nbooking_id={booking_id}\nguests={booking['guests']}",
        "start": {"dateTime": parse_dt(booking["start_at"]).isoformat()},
        "end": {"dateTime": parse_dt(booking["end_at"]).isoformat()},
        "extendedProperties": {"private": {"mk_booking_id": str(booking_id)}},
    }
    calendar_id = integration.get("calendar_id", "primary")

    if booking["status"] != "booked":
        if link:
            code, _, integration = google_api_request(
                integration,
                f"/calendars/{urllib.parse.quote(calendar_id, safe='')}/events/{urllib.parse.quote(link['external_event_id'], safe='')}",
                method="DELETE",
            )
            if code in (200, 204, 404):
                conn = db()
                conn.execute(
                    "DELETE FROM booking_external_events WHERE booking_id = ? AND provider = 'google'",
                    (booking_id,),
                )
                conn.commit()
                conn.close()
        return

    event_id = link["external_event_id"] if link else f"mkb{user_id}_{booking_id}"
    method = "PUT" if link else "POST"
    path = f"/calendars/{urllib.parse.quote(calendar_id, safe='')}/events"
    if link:
        path += f"/{urllib.parse.quote(event_id, safe='')}"
    else:
        event_payload["id"] = event_id
    code, payload, integration = google_api_request(integration, path, method=method, data=event_payload)
    if code not in (200, 201):
        return

    external_event_id = payload.get("id", event_id)
    conn = db()
    conn.execute(
        """
        INSERT INTO booking_external_events (booking_id, user_id, provider, external_event_id, status, created_at, updated_at)
        VALUES (?, ?, 'google', ?, 'active', ?, ?)
        ON CONFLICT(booking_id, provider) DO UPDATE SET
            external_event_id = excluded.external_event_id,
            status = 'active',
            updated_at = excluded.updated_at
        """,
        (booking_id, user_id, external_event_id, utc_now_iso(), utc_now_iso()),
    )
    conn.commit()
    conn.close()


def sync_google_to_app(user_id: int):
    integration = get_google_integration(user_id)
    if not integration:
        return {"ok": True, "checked": 0, "updated": 0}

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT booking_id, external_event_id FROM booking_external_events WHERE user_id = ? AND provider = 'google'",
        (user_id,),
    )
    linked = [dict(r) for r in cur.fetchall()]
    conn.close()

    checked = 0
    updated = 0
    calendar_id = integration.get("calendar_id", "primary")
    for row in linked:
        checked += 1
        code, payload, integration = google_api_request(
            integration,
            f"/calendars/{urllib.parse.quote(calendar_id, safe='')}/events/{urllib.parse.quote(row['external_event_id'], safe='')}",
            method="GET",
        )
        cancelled = code == 404 or payload.get("status") == "cancelled"
        if not cancelled:
            continue

        conn = db()
        cur = conn.cursor()
        cur.execute(
            "SELECT b.id, b.status, b.guests, b.slot_id, u.email FROM bookings b JOIN users u ON u.id = b.user_id WHERE b.id = ? AND b.user_id = ?",
            (row["booking_id"], user_id),
        )
        booking = cur.fetchone()
        if booking and booking["status"] == "booked":
            cur.execute("UPDATE bookings SET status = 'cancelled', cancelled_at = ?, updated_at = ? WHERE id = ?", (utc_now_iso(), utc_now_iso(), booking["id"]))
            cur.execute(
                "UPDATE workshop_slots SET booked_seats = booked_seats - ? WHERE id = ? AND booked_seats >= ?",
                (booking["guests"], booking["slot_id"], booking["guests"]),
            )
            promoted = promote_queue_for_slot(conn, booking["slot_id"])
            conn.commit()
            for promoted_booking in promoted:
                run_safe_task(
                    f"google_cancel_queue_promote_notify_{promoted_booking['booking_id']}",
                    send_booking_notification,
                    promoted_booking["email"],
                    "queue_promoted",
                    f"booking_id={promoted_booking['booking_id']}",
                )
                sync_booking_with_google(promoted_booking["user_id"], promoted_booking["booking_id"])
            send_booking_notification(booking["email"], "cancel", f"booking_id={booking['id']} source=google")
            log_action(user_id, "cancel_booking_from_google", {"booking_id": booking["id"]})
            updated += 1
        conn.close()

    return {"ok": True, "checked": checked, "updated": updated}


def require_master(user: dict):
    if user["role"] != "master":
        raise HTTPException(status_code=403, detail="Only master/studio can do this")


def get_user_from_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, APP_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = int(payload.get("sub", 0))
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="User not found")
    return dict(row)


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    return get_user_from_token(creds.credentials)


def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email_verified INTEGER NOT NULL DEFAULT 1,
            email_verify_code TEXT,
            role TEXT NOT NULL CHECK(role IN ('user', 'master')),
            name TEXT NOT NULL,
            avatar_url TEXT,
            phone TEXT,
            bio TEXT,
            address TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS master_profiles (
            user_id INTEGER PRIMARY KEY,
            studio_name TEXT,
            about TEXT,
            map_lat REAL,
            map_lng REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS workshops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            workshop_type TEXT,
            description TEXT,
            location TEXT,
            price INTEGER NOT NULL,
            duration_min INTEGER NOT NULL,
            capacity INTEGER NOT NULL,
            image_url TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY(master_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS workshop_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workshop_id INTEGER NOT NULL,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            workshop_type TEXT,
            price INTEGER,
            total_seats INTEGER NOT NULL,
            booked_seats INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed', 'cancelled')),
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY(workshop_id) REFERENCES workshops(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            slot_id INTEGER NOT NULL,
            guests INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('booked', 'queue', 'cancelled', 'completed', 'no_show')),
            cancel_reason TEXT,
            cancelled_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            UNIQUE(user_id, slot_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(slot_id) REFERENCES workshop_slots(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            booking_id INTEGER,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            text TEXT NOT NULL,
            review_media_json TEXT,
            master_reply TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY(master_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(booking_id) REFERENCES bookings(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS review_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id INTEGER NOT NULL,
            master_id INTEGER NOT NULL,
            reply_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY(review_id) REFERENCES reviews(id) ON DELETE CASCADE,
            FOREIGN KEY(master_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel TEXT NOT NULL CHECK(channel IN ('email')),
            notif_type TEXT NOT NULL,
            payload_json TEXT,
            status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued', 'sent', 'failed')),
            sent_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            payload_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS oauth_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            state TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS login_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT 'login',
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS calendar_integrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            token_expiry TEXT,
            calendar_id TEXT NOT NULL DEFAULT 'primary',
            created_at TEXT NOT NULL,
            updated_at TEXT,
            UNIQUE(user_id, provider),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS booking_external_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            external_event_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT,
            UNIQUE(booking_id, provider),
            FOREIGN KEY(booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER UNIQUE NOT NULL,
            ics_uid TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(booking_id) REFERENCES bookings(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_workshops_master_id ON workshops(master_id);
        CREATE INDEX IF NOT EXISTS idx_slots_workshop_id ON workshop_slots(workshop_id);
        CREATE INDEX IF NOT EXISTS idx_slots_start_at ON workshop_slots(start_at);
        CREATE INDEX IF NOT EXISTS idx_bookings_user_id ON bookings(user_id);
        CREATE INDEX IF NOT EXISTS idx_bookings_slot_id ON bookings(slot_id);
        CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
        CREATE INDEX IF NOT EXISTS idx_reviews_master_id ON reviews(master_id);
        CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);
        CREATE INDEX IF NOT EXISTS idx_user_actions_user_id ON user_actions(user_id);
        CREATE INDEX IF NOT EXISTS idx_oauth_states_provider ON oauth_states(provider);
        CREATE INDEX IF NOT EXISTS idx_calendar_integrations_user_id ON calendar_integrations(user_id);
        CREATE INDEX IF NOT EXISTS idx_booking_external_events_booking_id ON booking_external_events(booking_id);
        CREATE INDEX IF NOT EXISTS idx_login_codes_email ON login_codes(email);
        """
    )

    def has_column(table: str, column: str) -> bool:
        cur.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cur.fetchall())

    def add_column_if_missing(table: str, column: str, definition: str):
        if not has_column(table, column):
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    add_column_if_missing("users", "updated_at", "TEXT")
    add_column_if_missing("users", "email_verified", "INTEGER NOT NULL DEFAULT 1")
    add_column_if_missing("users", "email_verify_code", "TEXT")

    add_column_if_missing("workshops", "workshop_type", "TEXT")
    add_column_if_missing("workshops", "is_active", "INTEGER NOT NULL DEFAULT 1")
    add_column_if_missing("workshops", "updated_at", "TEXT")

    add_column_if_missing("workshop_slots", "status", "TEXT NOT NULL DEFAULT 'open'")
    add_column_if_missing("workshop_slots", "created_at", "TEXT")
    add_column_if_missing("workshop_slots", "updated_at", "TEXT")
    add_column_if_missing("workshop_slots", "workshop_type", "TEXT")
    add_column_if_missing("workshop_slots", "price", "INTEGER")

    add_column_if_missing("bookings", "cancel_reason", "TEXT")
    add_column_if_missing("bookings", "cancelled_at", "TEXT")
    add_column_if_missing("bookings", "updated_at", "TEXT")

    add_column_if_missing("reviews", "booking_id", "INTEGER")
    add_column_if_missing("reviews", "updated_at", "TEXT")
    add_column_if_missing("reviews", "review_media_json", "TEXT")
    add_column_if_missing("login_codes", "failed_attempts", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing("login_codes", "locked_until", "TEXT")

    cur.execute(
        """
        UPDATE workshop_slots
        SET price = COALESCE(
            price,
            (SELECT w.price FROM workshops w WHERE w.id = workshop_slots.workshop_id)
        )
        WHERE price IS NULL OR price <= 0
        """
    )
    cur.execute(
        """
        UPDATE workshop_slots
        SET workshop_type = COALESCE(
            NULLIF(workshop_type, ''),
            (SELECT w.workshop_type FROM workshops w WHERE w.id = workshop_slots.workshop_id)
        )
        WHERE workshop_type IS NULL OR workshop_type = ''
        """
    )

    conn.commit()
    conn.close()

init_db()


def promote_queue_for_slot(conn: sqlite3.Connection, slot_id: int):
    cur = conn.cursor()
    promoted = []
    cur.execute("SELECT total_seats, booked_seats FROM workshop_slots WHERE id = ?", (slot_id,))
    slot = cur.fetchone()
    if not slot:
        return promoted

    free = slot["total_seats"] - slot["booked_seats"]
    if free <= 0:
        return promoted

    cur.execute(
        """
        SELECT b.id, b.user_id, b.guests, u.email
        FROM bookings b
        JOIN users u ON u.id = b.user_id
        WHERE b.slot_id = ? AND b.status = 'queue'
        ORDER BY b.id ASC
        """,
        (slot_id,),
    )
    queue_rows = cur.fetchall()

    for row in queue_rows:
        if row["guests"] <= free:
            cur.execute(
                "UPDATE bookings SET status = 'booked', updated_at = ? WHERE id = ?",
                (utc_now_iso(), row["id"]),
            )
            cur.execute(
                "UPDATE workshop_slots SET booked_seats = booked_seats + ?, updated_at = ? WHERE id = ?",
                (row["guests"], utc_now_iso(), slot_id),
            )
            free -= row["guests"]
            promoted.append(
                {
                    "user_id": int(row["user_id"]),
                    "booking_id": int(row["id"]),
                    "email": row["email"],
                }
            )
        if free <= 0:
            break
    return promoted


def refresh_workshop_price_from_slots(conn: sqlite3.Connection, workshop_id: int):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT MIN(price) AS min_price
        FROM workshop_slots
        WHERE workshop_id = ? AND status = 'open' AND price > 0
        """,
        (workshop_id,),
    )
    row = cur.fetchone()
    min_price = int(row["min_price"] or 0) if row else 0
    if min_price > 0:
        cur.execute(
            "UPDATE workshops SET price = ?, updated_at = ? WHERE id = ?",
            (min_price, utc_now_iso(), workshop_id),
        )


@app.get("/api/search/resolve")
def search_resolve(q: str = ""):
    cleaned = q.strip()
    if not cleaned:
        return {"target": "/catalog.html"}
    looks_like_full_name = len(cleaned.split()) >= 2

    conn = db()
    cur = conn.cursor()
    query_norm = cleaned.casefold()

    cur.execute(
        """
        SELECT id, name
        FROM users
        WHERE role = 'master'
        ORDER BY id DESC
        """,
    )
    masters = [dict(r) for r in cur.fetchall()]

    exact_masters = [m for m in masters if str(m.get("name") or "").casefold() == query_norm]
    if looks_like_full_name and len(exact_masters) == 1:
        conn.close()
        return {"target": "/master.html", "master_id": exact_masters[0]["id"]}

    matched_masters = [m for m in masters if query_norm in str(m.get("name") or "").casefold()]

    cur.execute(
        """
        SELECT id, title
        FROM workshops
        WHERE is_active = 1
        """,
    )
    workshop_rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    matched_workshops = [w for w in workshop_rows if query_norm in str(w.get("title") or "").casefold()]

    if looks_like_full_name and len(matched_masters) == 1 and len(matched_workshops) == 0:
        return {"target": "/master.html", "master_id": matched_masters[0]["id"]}
    return {"target": "/catalog.html"}


@app.post("/api/auth/register")
def register(payload: dict, background_tasks: BackgroundTasks):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    password_repeat = (
        payload.get("password_repeat")
        or payload.get("passwordRepeat")
        or payload.get("confirm_password")
        or ""
    )
    role_raw = (payload.get("role") or "").strip().lower()
    name = (payload.get("name") or "").strip()

    role_aliases = {
        "master": "master",
        "studio": "master",
        "мастер": "master",
        "мастер / студия": "master",
        "master / studio": "master",
        "user": "user",
        "client": "user",
        "клиент": "user",
        "пользователь": "user",
    }
    role = role_aliases.get(role_raw)
    verify_code = generate_verify_code()

    if not email or not password or not password_repeat or not name or not role:
        raise HTTPException(
            status_code=400,
            detail="email, password, password_repeat, role, name required",
        )
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="password must be >= 6 chars")
    if password != password_repeat:
        raise HTTPException(status_code=400, detail="passwords do not match")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="invalid email")

    conn = db()
    created_user = None
    try:
        conn.execute(
            """
            INSERT INTO users (email, password_hash, email_verified, email_verify_code, role, name, created_at)
            VALUES (?, ?, 0, ?, ?, ?, ?)
            """,
            (email, pwd_context.hash(password), verify_code, role, name, utc_now_iso()),
        )
        conn.commit()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = ?", (email,))
        created_user = cur.fetchone()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="email already registered")
    finally:
        conn.close()

    enqueue_task(
        background_tasks,
        "register_verify_email",
        send_email_notification,
        email,
        "register_verify",
        "МК-Маркет: подтверждение почты",
        (
            f"Здравствуйте, {name}!\n\n"
            "Ваш код подтверждения почты:\n"
            f"{verify_code}\n\n"
            "Введите этот код на странице входа/регистрации в МК-Маркет.\n\n"
            "МК-Маркет"
        ),
        {"name": name, "role": role, "verify_code": verify_code},
        f"КОД ПОДТВЕРЖДЕНИЯ: {verify_code}",
    )
    if created_user:
        log_action(created_user["id"], "register", {"role": role})

    return {"ok": True, "needs_email_verification": True, "email": email}


@app.post("/api/auth/verify-email")
def verify_email(payload: dict):
    email = (payload.get("email") or "").strip().lower()
    code = (payload.get("code") or "").strip()
    if not email or not code:
        raise HTTPException(status_code=400, detail="email and code required")

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="user not found")
    if int(row["email_verified"] or 0) == 1:
        conn.close()
        return {"ok": True, "already_verified": True}
    if (row["email_verify_code"] or "") != code:
        conn.close()
        raise HTTPException(status_code=400, detail="invalid verification code")

    cur.execute(
        "UPDATE users SET email_verified = 1, email_verify_code = NULL, updated_at = ? WHERE id = ?",
        (utc_now_iso(), row["id"]),
    )
    conn.commit()
    conn.close()
    log_action(row["id"], "verify_email")
    return {"ok": True}


@app.post("/api/auth/login")
def login(payload: dict):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()

    if not row or not pwd_context.verify(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid credentials")
    if int(row["email_verified"] or 0) != 1:
        raise HTTPException(status_code=403, detail="email not verified")

    log_action(row["id"], "login")
    return {"token": create_token(row["id"], row["email"]), "user": account_view(row)}


@app.post("/api/auth/request-login-code")
def request_login_code(payload: dict, background_tasks: BackgroundTasks):
    email = (payload.get("email") or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="invalid email")

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cur.fetchone()
    if not user or int(user["email_verified"] or 0) != 1:
        conn.close()
        return {"ok": True}

    locked_until = get_login_code_lock_until(cur, email)
    if locked_until:
        conn.close()
        return {
            "ok": True,
            "cooldown_seconds": max(1, int((locked_until - utc_now()).total_seconds())),
        }

    cur.execute(
        """
        SELECT created_at
        FROM login_codes
        WHERE email = ? AND purpose = 'login'
        ORDER BY id DESC
        LIMIT 1
        """,
        (email,),
    )
    last_code = cur.fetchone()
    if last_code:
        last_created = parse_dt(last_code["created_at"])
        if utc_now() - last_created < timedelta(seconds=45):
            conn.close()
            return {"ok": True, "cooldown_seconds": 45}

    cur.execute(
        """
        UPDATE login_codes
        SET used_at = COALESCE(used_at, ?)
        WHERE email = ? AND purpose = 'login' AND used_at IS NULL
        """,
        (utc_now_iso(), email),
    )

    code = generate_verify_code()
    expires_at = (utc_now() + timedelta(minutes=15)).isoformat()
    cur.execute(
        """
        INSERT INTO login_codes (email, code, purpose, failed_attempts, locked_until, expires_at, used_at, created_at)
        VALUES (?, ?, 'login', 0, NULL, ?, NULL, ?)
        """,
        (email, code, expires_at, utc_now_iso()),
    )
    conn.commit()
    conn.close()

    enqueue_task(
        background_tasks,
        "login_code_email",
        send_email_notification,
        email,
        "login_code",
        "МК-Маркет: код для входа",
        (
            f"Код для входа: {code}\n\n"
            "Код действует 15 минут.\n\n"
            "Если это были не вы, просто проигнорируйте письмо."
        ),
        {"email": email, "code": code, "purpose": "login"},
        f"КОД ДЛЯ ВХОДА: {code}",
    )
    return {"ok": True}


@app.post("/api/auth/login-by-code")
def login_by_code(payload: dict):
    email = (payload.get("email") or "").strip().lower()
    code = (payload.get("code") or "").strip()
    if not email or not code:
        raise HTTPException(status_code=400, detail="email and code required")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="invalid email")

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cur.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=401, detail="invalid code")
    if int(user["email_verified"] or 0) != 1:
        conn.close()
        raise HTTPException(status_code=403, detail="email not verified")

    locked_until = get_login_code_lock_until(cur, email)
    if locked_until:
        conn.close()
        raise HTTPException(status_code=429, detail="too many code attempts")

    cur.execute(
        """
        SELECT *
        FROM login_codes
        WHERE email = ? AND purpose = 'login' AND used_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (email,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="invalid code")
    if parse_dt(row["expires_at"]) < utc_now():
        conn.close()
        raise HTTPException(status_code=401, detail="code expired")
    if row["code"] != code:
        failed_attempts = int(row["failed_attempts"] or 0) + 1
        if failed_attempts >= LOGIN_CODE_MAX_ATTEMPTS:
            now_iso = utc_now_iso()
            cur.execute(
                """
                UPDATE login_codes
                SET failed_attempts = ?, locked_until = ?, used_at = ?
                WHERE id = ?
                """,
                (
                    failed_attempts,
                    (utc_now() + timedelta(minutes=LOGIN_CODE_LOCK_MINUTES)).isoformat(),
                    now_iso,
                    row["id"],
                ),
            )
            conn.commit()
            conn.close()
            raise HTTPException(status_code=429, detail="too many code attempts")

        cur.execute(
            "UPDATE login_codes SET failed_attempts = ?, locked_until = NULL WHERE id = ?",
            (failed_attempts, row["id"]),
        )
        conn.commit()
        conn.close()
        raise HTTPException(status_code=401, detail="invalid code")

    cur.execute("UPDATE login_codes SET used_at = ? WHERE id = ?", (utc_now_iso(), row["id"]))
    conn.commit()
    conn.close()

    log_action(user["id"], "login_by_code")
    return {"token": create_token(user["id"], user["email"]), "user": account_view(user)}


@app.get("/api/integrations/google/status")
def google_status(user=Depends(get_current_user)):
    integration = get_google_integration(user["id"])
    if not integration:
        return {"connected": False}
    return {
        "connected": True,
        "provider": "google",
        "calendar_id": integration.get("calendar_id", "primary"),
        "token_expiry": integration.get("token_expiry"),
    }


@app.get("/api/integrations/google/start")
def google_start(request: Request, user=Depends(get_current_user)):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="google oauth is not configured")
    redirect_uri = GOOGLE_REDIRECT_URI or str(request.base_url).rstrip("/") + "/api/integrations/google/callback"
    state = random_state_token()
    conn = db()
    conn.execute(
        "INSERT INTO oauth_states (user_id, provider, state, created_at) VALUES (?, 'google', ?, ?)",
        (user["id"], state, utc_now_iso()),
    )
    conn.commit()
    conn.close()

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return {"auth_url": auth_url}


@app.get("/api/integrations/google/callback")
def google_callback(code: str, state: str, request: Request, background_tasks: BackgroundTasks):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id FROM oauth_states WHERE state = ? AND provider = 'google'",
        (state,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=400, detail="invalid oauth state")
    user_id = row["user_id"]
    cur.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
    conn.commit()
    conn.close()

    redirect_uri = GOOGLE_REDIRECT_URI or str(request.base_url).rstrip("/") + "/api/integrations/google/callback"
    code_status, token_data = json_request(
        "https://oauth2.googleapis.com/token",
        method="POST",
        data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/json"},
    )
    if code_status != 200:
        raise HTTPException(status_code=400, detail=f"google oauth failed: {token_data}")

    save_google_integration(
        user_id=user_id,
        access_token=token_data.get("access_token", ""),
        refresh_token=token_data.get("refresh_token"),
        expires_in=token_data.get("expires_in", 3600),
    )
    log_action(user_id, "google_connected")
    html = """
    <html><body>
    <h3>Google Calendar подключен</h3>
    <script>window.location.href='/cabinet.html?google_connected=1';</script>
    </body></html>
    """
    return Response(content=html, media_type="text/html")


@app.post("/api/integrations/google/disconnect")
def google_disconnect(user=Depends(get_current_user)):
    conn = db()
    conn.execute("DELETE FROM calendar_integrations WHERE user_id = ? AND provider = 'google'", (user["id"],))
    conn.execute("DELETE FROM booking_external_events WHERE user_id = ? AND provider = 'google'", (user["id"],))
    conn.commit()
    conn.close()
    log_action(user["id"], "google_disconnected")
    return {"ok": True}


@app.post("/api/integrations/google/sync-now")
def google_sync_now(user=Depends(get_current_user)):
    result = sync_google_to_app(user["id"])

    conn = db()
    cur = conn.cursor()
    conn.close()
    enqueue_task(background_tasks, "sync_all_google_bookings", sync_user_google_bookings, user["id"])
    log_action(user["id"], "google_sync_now", result)
    return result


@app.get("/api/me")
def me(user=Depends(get_current_user)):
    return account_view(user)


@app.put("/api/me")
def update_me(payload: dict, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    name = (payload.get("name") or user["name"]).strip()
    email = (payload.get("email") or user["email"]).strip().lower()
    avatar_url = payload.get("avatar_url")
    phone = payload.get("phone")
    bio = payload.get("bio")
    address = payload.get("address")
    current_password = payload.get("current_password") or ""
    new_password = payload.get("new_password") or ""
    new_password_repeat = payload.get("new_password_repeat") or ""

    if not name:
        raise HTTPException(status_code=400, detail="name required")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="invalid email")
    email_changed = email != str(user["email"] or "").strip().lower()
    verify_code = generate_verify_code() if email_changed else None

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = ? AND id != ?", (email, user["id"]))
    if cur.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="email already registered")

    if new_password or new_password_repeat:
        if not current_password:
            conn.close()
            raise HTTPException(status_code=400, detail="current_password required")
        if not pwd_context.verify(current_password, user["password_hash"]):
            conn.close()
            raise HTTPException(status_code=400, detail="current password invalid")
        if len(new_password) < 6:
            conn.close()
            raise HTTPException(status_code=400, detail="new password must be >= 6 chars")
        if new_password != new_password_repeat:
            conn.close()
            raise HTTPException(status_code=400, detail="new passwords do not match")
        cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pwd_context.hash(new_password), user["id"]))

    conn.execute(
        """
        UPDATE users
        SET name = ?, email = ?, avatar_url = ?, phone = ?, bio = ?, address = ?,
            email_verified = ?, email_verify_code = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            name,
            email,
            avatar_url,
            phone,
            bio,
            address,
            0 if email_changed else int(user["email_verified"] or 0),
            verify_code if email_changed else user["email_verify_code"],
            utc_now_iso(),
            user["id"],
        ),
    )
    conn.commit()

    cur.execute("SELECT * FROM users WHERE id = ?", (user["id"],))
    row = cur.fetchone()
    conn.close()
    log_action(user["id"], "update_profile", {"email": row["email"]})
    if email_changed and verify_code:
        enqueue_task(
            background_tasks,
            "profile_verify_email",
            send_email_notification,
            email,
            "profile_verify",
            "МК-Маркет: подтверждение новой почты",
            (
                f"Здравствуйте, {name}!\n\n"
                "Вы изменили почту в профиле МК-Маркет.\n"
                "Ваш код подтверждения новой почты:\n"
                f"{verify_code}\n\n"
                "Введите этот код на странице входа/регистрации, чтобы подтвердить новый адрес.\n\n"
                "МК-Маркет"
            ),
            {"name": name, "verify_code": verify_code, "email": email},
            f"КОД ПОДТВЕРЖДЕНИЯ: {verify_code}",
        )
    return account_view(row)


@app.post("/api/me/password")
def change_my_password(payload: dict, user=Depends(get_current_user)):
    current_password = payload.get("current_password") or ""
    new_password = payload.get("new_password") or ""
    new_password_repeat = payload.get("new_password_repeat") or ""

    if not current_password or not new_password or not new_password_repeat:
        raise HTTPException(status_code=400, detail="current_password, new_password, new_password_repeat required")
    if not pwd_context.verify(current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="current password invalid")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="new password must be >= 6 chars")
    if new_password != new_password_repeat:
        raise HTTPException(status_code=400, detail="new passwords do not match")

    conn = db()
    conn.execute(
        "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
        (pwd_context.hash(new_password), utc_now_iso(), user["id"]),
    )
    conn.commit()
    conn.close()
    log_action(user["id"], "change_password")
    return {"ok": True}


@app.get("/api/catalog")
def catalog(
    q: str = "",
    date: Optional[str] = None,
    sort: str = "price_asc",
    location: str = "",
    workshop_type: str = "",
    min_rating: Optional[float] = None,
):
    conn = db()
    cur = conn.cursor()
    query_norm = q.strip().casefold()
    location_norm = location.strip().casefold()
    workshop_type_norm = workshop_type.strip().casefold()

    sql = """
    SELECT
        w.id, w.title, w.location, w.price, w.capacity, w.duration_min,
        w.image_url, w.workshop_type,
        COALESCE(
            (
                SELECT MIN(s.price)
                FROM workshop_slots s
                WHERE s.workshop_id = w.id
                  AND s.status = 'open'
                  AND s.price > 0
            ),
            w.price
        ) AS min_price,
        COALESCE(
            (
                SELECT MIN(s.total_seats)
                FROM workshop_slots s
                WHERE s.workshop_id = w.id
                  AND s.status = 'open'
                  AND s.total_seats > 0
            ),
            w.capacity
        ) AS min_capacity,
        COALESCE(
            (
                SELECT GROUP_CONCAT(DISTINCT COALESCE(NULLIF(s.workshop_type, ''), w.workshop_type))
                FROM workshop_slots s
                WHERE s.workshop_id = w.id
                  AND s.status = 'open'
            ),
            w.workshop_type
        ) AS workshop_types_csv,
        u.id AS master_id, u.name AS master_name,
        COALESCE((SELECT AVG(r.rating) FROM reviews r WHERE r.master_id = u.id), 0) AS master_rating
    FROM workshops w
    JOIN users u ON u.id = w.master_id
    WHERE w.is_active = 1
    """
    args = []

    if date:
        sql += """
        AND EXISTS (
            SELECT 1 FROM workshop_slots s
            WHERE s.workshop_id = w.id
              AND date(s.start_at) = date(?)
        )
        """
        args.append(date)

    if min_rating is not None:
        sql += " AND COALESCE((SELECT AVG(r.rating) FROM reviews r WHERE r.master_id = u.id), 0) >= ?"
        args.append(float(min_rating))

    allowed_sort = {"price_asc", "price_desc", "rating_desc", "date"}
    if sort not in allowed_sort:
        sort = "price_asc"

    if sort == "price_desc":
        sql += " ORDER BY w.price DESC"
    elif sort == "rating_desc":
        sql += " ORDER BY master_rating DESC, w.price ASC"
    elif sort == "date":
        sql += " ORDER BY (SELECT MIN(s.start_at) FROM workshop_slots s WHERE s.workshop_id = w.id) ASC, w.price ASC"
    else:
        sql += " ORDER BY w.price ASC"

    cur.execute(sql, args)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    for row in rows:
        types = workshop_types_from_csv(str(row.get("workshop_types_csv") or ""), str(row.get("workshop_type") or ""))
        row["workshop_types"] = types
        row["workshop_types_label"] = workshop_types_label(types)

    if query_norm:
        rows = [
            row
            for row in rows
            if query_norm in str(row.get("title") or "").casefold()
            or query_norm in str(row.get("master_name") or "").casefold()
            or query_norm in str(row.get("location") or "").casefold()
            or query_norm in str(row.get("workshop_types_label") or "").casefold()
        ]

    if location_norm:
        rows = [row for row in rows if location_norm in str(row.get("location") or "").casefold()]

    if workshop_type_norm:
        rows = [
            row
            for row in rows
            if any(workshop_type_norm in str(workshop_type or "").casefold() for workshop_type in row.get("workshop_types", []))
        ]

    return rows


@app.get("/api/masters/{master_id}")
def master_page(
    master_id: int,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
):
    viewer = get_user_from_token(creds.credentials) if creds else None

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE id = ? AND role = 'master'", (master_id,))
    master = cur.fetchone()
    if not master:
        conn.close()
        raise HTTPException(status_code=404, detail="master not found")

    cur.execute(
        """
        SELECT
            w.id,
            w.title,
            w.workshop_type,
            COALESCE(
                (
                    SELECT GROUP_CONCAT(DISTINCT COALESCE(NULLIF(s.workshop_type, ''), w.workshop_type))
                    FROM workshop_slots s
                    WHERE s.workshop_id = w.id
                      AND s.status = 'open'
                ),
                w.workshop_type
            ) AS workshop_types_csv,
            w.description,
            w.location,
            w.price,
            w.duration_min,
            w.capacity,
            w.image_url,
            COALESCE(
                (
                    SELECT MIN(s.price)
                    FROM workshop_slots s
                    WHERE s.workshop_id = w.id
                      AND s.status = 'open'
                      AND s.price > 0
                ),
                w.price
            ) AS min_price
        FROM workshops w
        WHERE w.master_id = ?
        ORDER BY w.id DESC
        """,
        (master_id,),
    )
    workshops = []
    for row in cur.fetchall():
        item = dict(row)
        types = workshop_types_from_csv(str(item.get("workshop_types_csv") or ""), str(item.get("workshop_type") or ""))
        item["workshop_types"] = types
        item["workshop_types_label"] = workshop_types_label(types)
        workshops.append(item)

    cur.execute(
        """
        SELECT r.id, r.user_id, r.rating, r.text, r.review_media_json, r.master_reply, r.created_at,
               u.name AS user_name, u.avatar_url AS user_avatar
        FROM reviews r
        JOIN users u ON u.id = r.user_id
        WHERE r.master_id = ?
        ORDER BY r.id DESC
        """,
        (master_id,),
    )
    reviews = []
    for row in cur.fetchall():
        item = dict(row)
        raw_media = item.pop("review_media_json", "") or ""
        try:
            parsed_media = json.loads(raw_media) if raw_media else []
            item["media"] = parsed_media if isinstance(parsed_media, list) else []
        except Exception:
            item["media"] = []
        reviews.append(item)

    cur.execute("SELECT AVG(rating) AS avg_rating, COUNT(*) AS cnt FROM reviews WHERE master_id = ?", (master_id,))
    agg = cur.fetchone()
    review_policy = build_review_policy(conn, viewer, master_id)

    conn.close()
    return {
        "master": user_view(master),
        "stats": {
            "rating": round(float(agg["avg_rating"] or 0), 1),
            "reviews_count": agg["cnt"],
        },
        "workshops": workshops,
        "reviews": reviews,
        "review_policy": {
            "can_add": bool(review_policy["can_add"]),
            "reason": str(review_policy["reason"] or ""),
            "code": str(review_policy["error_code"] or ""),
        },
    }


@app.get("/api/workshops/{workshop_id}")
def workshop_card(
    workshop_id: int,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
):
    user_id = None
    if creds:
        user = get_user_from_token(creds.credentials)
        user_id = int(user["id"])

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT w.*, u.name AS master_name, u.id AS master_id
        FROM workshops w
        JOIN users u ON u.id = w.master_id
        WHERE w.id = ?
        """,
        (workshop_id,),
    )
    workshop = cur.fetchone()
    if not workshop:
        conn.close()
        raise HTTPException(status_code=404, detail="workshop not found")

    cur.execute(
        """
        SELECT id, start_at, end_at, workshop_type, price, total_seats, booked_seats,
               (total_seats - booked_seats) AS free_seats
        FROM workshop_slots
        WHERE workshop_id = ?
          AND status = 'open'
        ORDER BY start_at ASC
        """,
        (workshop_id,),
    )
    slots = [dict(r) for r in cur.fetchall()]
    for slot in slots:
        slot["my_booking_status"] = ""

    if user_id and slots:
        slot_ids = [int(slot["id"]) for slot in slots]
        placeholders = ",".join(["?"] * len(slot_ids))
        cur.execute(
            f"""
            SELECT slot_id, status
            FROM bookings
            WHERE user_id = ?
              AND slot_id IN ({placeholders})
              AND status IN ('booked', 'queue')
            """,
            (user_id, *slot_ids),
        )
        my_rows = {int(row["slot_id"]): str(row["status"] or "") for row in cur.fetchall()}
        for slot in slots:
            slot["my_booking_status"] = my_rows.get(int(slot["id"]), "")

    conn.close()
    return {"workshop": dict(workshop), "slots": slots}


@app.post("/api/workshops/{workshop_id}/book")
def book_workshop(workshop_id: int, payload: dict, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    slot_id = int(payload.get("slot_id") or 0)
    guests = int(payload.get("guests") or 1)
    if guests < 1:
        raise HTTPException(status_code=400, detail="guests must be >= 1")

    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT s.*, w.title
        FROM workshop_slots s
        JOIN workshops w ON w.id = s.workshop_id
        WHERE s.id = ? AND s.workshop_id = ?
        """,
        (slot_id, workshop_id),
    )
    slot = cur.fetchone()
    if not slot:
        conn.close()
        raise HTTPException(status_code=404, detail="slot not found")
    if slot["status"] != "open":
        conn.close()
        raise HTTPException(status_code=400, detail="slot is not available")

    start_at = parse_dt(slot["start_at"])
    if start_at - utc_now() < timedelta(hours=24):
        conn.close()
        raise HTTPException(status_code=400, detail="booking allowed at least 24 hours before start")

    slot_type = normalize_workshop_type(str(slot["workshop_type"] or ""))
    if slot_type == "Индивидуальный МК":
        guests = 1
    elif slot_type == "МК-Свидание":
        guests = 2

    free_seats = slot["total_seats"] - slot["booked_seats"]
    status = "booked" if free_seats >= guests else "queue"
    if slot_type == "МК-Свидание":
        cur.execute(
            "SELECT id FROM bookings WHERE slot_id = ? AND status = 'booked' LIMIT 1",
            (slot_id,),
        )
        if cur.fetchone():
            status = "queue"
    cur.execute(
        """
        SELECT id, status
        FROM bookings
        WHERE user_id = ? AND slot_id = ?
        LIMIT 1
        """,
        (user["id"], slot_id),
    )
    existing_booking = cur.fetchone()

    if existing_booking and existing_booking["status"] in ("booked", "queue"):
        conn.close()
        raise HTTPException(status_code=400, detail="Вы уже записаны или стоите в очереди на этот слот")

    if existing_booking and existing_booking["status"] in ("cancelled", "completed", "no_show"):
        booking_id = existing_booking["id"]
        cur.execute(
            """
            UPDATE bookings
            SET guests = ?, status = ?, cancel_reason = NULL, cancelled_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (guests, status, utc_now_iso(), booking_id),
        )
    else:
        try:
            cur.execute(
                """
                INSERT INTO bookings (user_id, slot_id, guests, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user["id"], slot_id, guests, status, utc_now_iso()),
            )
        except sqlite3.IntegrityError:
            conn.close()
            raise HTTPException(status_code=400, detail="Вы уже записаны или стоите в очереди на этот слот")
        booking_id = cur.lastrowid

    if status == "booked":
        cur.execute(
            "UPDATE workshop_slots SET booked_seats = booked_seats + ?, updated_at = ? WHERE id = ?",
            (guests, utc_now_iso(), slot_id),
        )

    conn.commit()
    conn.close()

    enqueue_task(
        background_tasks,
        "booking_notification",
        send_booking_notification,
        user["email"],
        "booking",
        f"booking_id={booking_id} status={status}",
    )
    enqueue_task(background_tasks, "booking_google_sync", sync_booking_with_google, user["id"], booking_id)
    log_action(user["id"], "book_workshop", {"workshop_id": workshop_id, "slot_id": slot_id, "booking_id": booking_id, "status": status, "guests": guests})
    return {"booking_id": booking_id, "status": status, "message": "Booked" if status == "booked" else "Added to queue"}


@app.get("/api/me/bookings")
def my_bookings(user=Depends(get_current_user)):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            b.id, b.guests, b.status, b.created_at,
            s.id AS slot_id, s.start_at, s.end_at,
            w.id AS workshop_id, w.title, w.location,
            m.name AS master_name
        FROM bookings b
        JOIN workshop_slots s ON s.id = b.slot_id
        JOIN workshops w ON w.id = s.workshop_id
        JOIN users m ON m.id = w.master_id
        WHERE b.user_id = ?
        ORDER BY s.start_at ASC
        """,
        (user["id"],),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.get("/api/me/master-upcoming-slots")
def my_master_upcoming_slots(user=Depends(get_current_user)):
    require_master(user)
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            s.id,
            s.workshop_id,
            s.start_at,
            s.end_at,
            s.workshop_type,
            s.price,
            s.total_seats,
            s.booked_seats,
            s.status,
            (s.total_seats - s.booked_seats) AS free_seats,
            w.title AS workshop_title,
            w.location AS workshop_location,
            (
              SELECT COUNT(*)
              FROM bookings b
              WHERE b.slot_id = s.id AND b.status = 'booked'
            ) AS booked_records
        FROM workshop_slots s
        JOIN workshops w ON w.id = s.workshop_id
        WHERE w.master_id = ?
          AND s.status = 'open'
        ORDER BY s.start_at ASC, s.id ASC
        """,
        (user["id"],),
    )
    now_utc = utc_now()
    min_start = now_utc - timedelta(minutes=5)
    max_start = now_utc + timedelta(hours=24)
    rows = []
    for row in cur.fetchall():
        item = dict(row)
        start_at = parse_dt(str(item["start_at"]))
        if start_at < min_start or start_at > max_start:
            continue
        rows.append(item)
    conn.close()
    return rows


@app.get("/api/me/reviews")
def my_reviews(user=Depends(get_current_user)):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.id,
            r.rating,
            r.text,
            r.review_media_json,
            r.master_reply,
            r.created_at,
            r.updated_at,
            m.id AS master_id,
            m.name AS master_name
        FROM reviews r
        JOIN users m ON m.id = r.master_id
        WHERE r.user_id = ?
        ORDER BY r.id DESC
        """,
        (user["id"],),
    )
    rows = []
    for raw in cur.fetchall():
        item = dict(raw)
        media_raw = item.pop("review_media_json", "") or ""
        try:
            parsed_media = json.loads(media_raw) if media_raw else []
            item["media"] = parsed_media if isinstance(parsed_media, list) else []
        except Exception:
            item["media"] = []
        rows.append(item)
    conn.close()
    return rows


@app.get("/api/me/reviews/received")
def my_received_reviews(user=Depends(get_current_user)):
    require_master(user)
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.id,
            r.user_id,
            r.rating,
            r.text,
            r.review_media_json,
            r.master_reply,
            r.created_at,
            r.updated_at,
            u.name AS user_name,
            u.avatar_url AS user_avatar,
            r.master_id
        FROM reviews r
        JOIN users u ON u.id = r.user_id
        WHERE r.master_id = ?
        ORDER BY r.id DESC
        """,
        (user["id"],),
    )
    rows = []
    for raw in cur.fetchall():
        item = dict(raw)
        media_raw = item.pop("review_media_json", "") or ""
        try:
            parsed_media = json.loads(media_raw) if media_raw else []
            item["media"] = parsed_media if isinstance(parsed_media, list) else []
        except Exception:
            item["media"] = []
        rows.append(item)
    conn.close()
    return rows


@app.post("/api/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: int, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.*, s.start_at
        FROM bookings b
        JOIN workshop_slots s ON s.id = b.slot_id
        WHERE b.id = ? AND b.user_id = ?
        """,
        (booking_id, user["id"]),
    )
    booking = cur.fetchone()
    if not booking:
        conn.close()
        raise HTTPException(status_code=404, detail="booking not found")

    if booking["status"] == "cancelled":
        conn.close()
        return {"ok": True, "status": "cancelled"}

    start_at = parse_dt(booking["start_at"])
    if start_at - utc_now() < timedelta(hours=24):
        conn.close()
        raise HTTPException(status_code=400, detail="cancellation allowed at least 24 hours before start")

    cur.execute(
        "UPDATE bookings SET status = 'cancelled', cancelled_at = ?, updated_at = ? WHERE id = ?",
        (utc_now_iso(), utc_now_iso(), booking_id),
    )

    promoted = []
    if booking["status"] == "booked":
        cur.execute(
            "UPDATE workshop_slots SET booked_seats = booked_seats - ?, updated_at = ? WHERE id = ? AND booked_seats >= ?",
            (booking["guests"], utc_now_iso(), booking["slot_id"], booking["guests"]),
        )
        promoted = promote_queue_for_slot(conn, booking["slot_id"])

    conn.commit()
    conn.close()

    for promoted_booking in promoted:
        enqueue_task(
            background_tasks,
            f"promote_notification_{promoted_booking['booking_id']}",
            send_booking_notification,
            promoted_booking["email"],
            "queue_promoted",
            f"booking_id={promoted_booking['booking_id']}",
        )
        enqueue_task(
            background_tasks,
            f"promote_google_sync_{promoted_booking['booking_id']}",
            sync_booking_with_google,
            promoted_booking["user_id"],
            promoted_booking["booking_id"],
        )
    enqueue_task(background_tasks, "cancel_notification", send_booking_notification, user["email"], "cancel", f"booking_id={booking_id}")
    enqueue_task(background_tasks, "cancel_google_sync", sync_booking_with_google, user["id"], booking_id)
    log_action(user["id"], "cancel_booking", {"booking_id": booking_id})
    return {"ok": True, "status": "cancelled"}


@app.get("/api/bookings/{booking_id}/reschedule-options")
def booking_reschedule_options(booking_id: int, user=Depends(get_current_user)):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.id, b.guests, b.status, b.slot_id, s.start_at, s.workshop_id
        FROM bookings b
        JOIN workshop_slots s ON s.id = b.slot_id
        WHERE b.id = ? AND b.user_id = ?
        """,
        (booking_id, user["id"]),
    )
    booking = cur.fetchone()
    if not booking:
        conn.close()
        raise HTTPException(status_code=404, detail="booking not found")

    if booking["status"] not in ("booked", "queue"):
        conn.close()
        raise HTTPException(status_code=400, detail="booking is not active")

    start_at = parse_dt(booking["start_at"])
    if start_at - utc_now() < timedelta(hours=24):
        conn.close()
        raise HTTPException(status_code=400, detail="reschedule allowed at least 24 hours before start")

    min_target_start = utc_now() + timedelta(hours=24)
    cur.execute(
        """
        SELECT
            s.id,
            s.start_at,
            s.end_at,
            COALESCE(NULLIF(s.workshop_type, ''), w.workshop_type) AS workshop_type,
            COALESCE(s.price, w.price) AS price,
            s.total_seats,
            s.booked_seats
        FROM workshop_slots s
        JOIN workshops w ON w.id = s.workshop_id
        WHERE s.workshop_id = ?
          AND s.status = 'open'
          AND s.id != ?
          AND s.start_at >= ?
          AND (s.total_seats - s.booked_seats) >= ?
          AND NOT EXISTS (
            SELECT 1
            FROM bookings b2
            WHERE b2.user_id = ?
              AND b2.slot_id = s.id
              AND b2.id != ?
          )
        ORDER BY s.start_at ASC
        """,
        (
            booking["workshop_id"],
            booking["slot_id"],
            min_target_start.isoformat(),
            int(booking["guests"] or 1),
            user["id"],
            booking_id,
        ),
    )
    options = []
    for row in cur.fetchall():
        slot = dict(row)
        total = int(slot.get("total_seats") or 0)
        booked = int(slot.get("booked_seats") or 0)
        slot["free_seats"] = max(0, total - booked)
        options.append(slot)
    conn.close()

    return {
        "booking_id": int(booking["id"]),
        "slot_id": int(booking["slot_id"]),
        "workshop_id": int(booking["workshop_id"]),
        "guests": int(booking["guests"] or 1),
        "options": options,
    }


@app.post("/api/bookings/{booking_id}/reschedule")
def reschedule_booking(booking_id: int, payload: dict, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    target_slot_id = int(payload.get("target_slot_id") or 0)
    if target_slot_id <= 0:
        raise HTTPException(status_code=400, detail="target_slot_id required")

    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.id, b.user_id, b.guests, b.status, b.slot_id, s.start_at, s.workshop_id
        FROM bookings b
        JOIN workshop_slots s ON s.id = b.slot_id
        WHERE b.id = ? AND b.user_id = ?
        """,
        (booking_id, user["id"]),
    )
    booking = cur.fetchone()
    if not booking:
        conn.close()
        raise HTTPException(status_code=404, detail="booking not found")

    if booking["status"] not in ("booked", "queue"):
        conn.close()
        raise HTTPException(status_code=400, detail="booking is not active")

    if int(booking["slot_id"]) == target_slot_id:
        conn.close()
        raise HTTPException(status_code=400, detail="target slot must be different")

    start_at = parse_dt(booking["start_at"])
    if start_at - utc_now() < timedelta(hours=24):
        conn.close()
        raise HTTPException(status_code=400, detail="reschedule allowed at least 24 hours before start")

    cur.execute(
        """
        SELECT s.*, w.id AS workshop_id, w.workshop_type AS workshop_default_type, w.price AS workshop_default_price
        FROM workshop_slots s
        JOIN workshops w ON w.id = s.workshop_id
        WHERE s.id = ?
        """,
        (target_slot_id,),
    )
    target = cur.fetchone()
    if not target:
        conn.close()
        raise HTTPException(status_code=404, detail="target slot not found")

    if int(target["workshop_id"]) != int(booking["workshop_id"]):
        conn.close()
        raise HTTPException(status_code=400, detail="target slot must belong to same workshop")

    if target["status"] != "open":
        conn.close()
        raise HTTPException(status_code=400, detail="target slot is not available")

    target_start = parse_dt(target["start_at"])
    if target_start - utc_now() < timedelta(hours=24):
        conn.close()
        raise HTTPException(status_code=400, detail="booking allowed at least 24 hours before start")

    free_seats = int(target["total_seats"] or 0) - int(target["booked_seats"] or 0)
    if free_seats < int(booking["guests"] or 1):
        conn.close()
        raise HTTPException(status_code=400, detail="not enough free seats in target slot")

    cur.execute(
        """
        SELECT id
        FROM bookings
        WHERE user_id = ? AND slot_id = ? AND id != ?
        LIMIT 1
        """,
        (user["id"], target_slot_id, booking_id),
    )
    duplicate_for_target = cur.fetchone()
    if duplicate_for_target:
        conn.close()
        raise HTTPException(status_code=400, detail="you already have booking history for target slot")

    now_iso = utc_now_iso()
    if booking["status"] == "booked":
        cur.execute(
            "UPDATE workshop_slots SET booked_seats = booked_seats - ?, updated_at = ? WHERE id = ? AND booked_seats >= ?",
            (booking["guests"], now_iso, booking["slot_id"], booking["guests"]),
        )

    cur.execute(
        "UPDATE workshop_slots SET booked_seats = booked_seats + ?, updated_at = ? WHERE id = ?",
        (booking["guests"], now_iso, target_slot_id),
    )
    cur.execute(
        """
        UPDATE bookings
        SET slot_id = ?, status = 'booked', cancel_reason = NULL, cancelled_at = NULL, updated_at = ?
        WHERE id = ?
        """,
        (target_slot_id, now_iso, booking_id),
    )

    promoted = []
    if booking["status"] == "booked":
        promoted = promote_queue_for_slot(conn, booking["slot_id"])

    conn.commit()
    conn.close()

    for promoted_booking in promoted:
        enqueue_task(
            background_tasks,
            f"reschedule_promote_notification_{promoted_booking['booking_id']}",
            send_booking_notification,
            promoted_booking["email"],
            "queue_promoted",
            f"booking_id={promoted_booking['booking_id']}",
        )
        enqueue_task(
            background_tasks,
            f"reschedule_promote_google_sync_{promoted_booking['booking_id']}",
            sync_booking_with_google,
            promoted_booking["user_id"],
            promoted_booking["booking_id"],
        )
    enqueue_task(background_tasks, "reschedule_google_sync", sync_booking_with_google, user["id"], booking_id)
    log_action(
        user["id"],
        "reschedule_booking",
        {"booking_id": booking_id, "from_slot_id": int(booking["slot_id"]), "to_slot_id": target_slot_id},
    )
    return {"ok": True, "status": "booked", "booking_id": booking_id, "slot_id": target_slot_id}


@app.get("/api/bookings/{booking_id}/calendar.ics")
def booking_ics(booking_id: int, user=Depends(get_current_user)):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.id, b.status, s.start_at, s.end_at, w.title, w.location
        FROM bookings b
        JOIN workshop_slots s ON s.id = b.slot_id
        JOIN workshops w ON w.id = s.workshop_id
        WHERE b.id = ? AND b.user_id = ?
        """,
        (booking_id, user["id"]),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="booking not found")
    if row["status"] != "booked":
        raise HTTPException(status_code=400, detail="calendar available only for booked status")

    start = parse_dt(row["start_at"]).strftime("%Y%m%dT%H%M%SZ")
    end = parse_dt(row["end_at"]).strftime("%Y%m%dT%H%M%SZ")
    uid = f"booking-{row['id']}@mkmarket"
    dtstamp = utc_now().strftime("%Y%m%dT%H%M%SZ")

    content = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//MK-Market//Booking//RU\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{dtstamp}\r\n"
        f"DTSTART:{start}\r\n"
        f"DTEND:{end}\r\n"
        f"SUMMARY:{row['title']}\r\n"
        f"LOCATION:{row['location'] or ''}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    headers = {"Content-Disposition": f"attachment; filename=booking-{row['id']}.ics"}
    return Response(content=content, media_type="text/calendar", headers=headers)


@app.get("/api/bookings/{booking_id}/calendar-links")
def booking_calendar_links(booking_id: int, user=Depends(get_current_user)):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.id, b.status, b.guests, s.start_at, s.end_at, w.title, w.location
        FROM bookings b
        JOIN workshop_slots s ON s.id = b.slot_id
        JOIN workshops w ON w.id = s.workshop_id
        WHERE b.id = ? AND b.user_id = ?
        """,
        (booking_id, user["id"]),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="booking not found")
    if row["status"] != "booked":
        raise HTTPException(status_code=400, detail="calendar available only for booked status")

    details = f"Бронь МК-Маркет. Количество участников: {row['guests']}"
    return {
        "apple_ics_url": f"/api/bookings/{booking_id}/calendar.ics",
        "google_url": google_calendar_url(
            title=row["title"],
            start_at=row["start_at"],
            end_at=row["end_at"],
            location=row["location"] or "",
            details=details,
        ),
    }


@app.get("/api/admin/slots/{slot_id}/calendar.ics")
def admin_slot_ics(slot_id: int, user=Depends(get_current_user)):
    require_master(user)

    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            s.id,
            s.status,
            s.start_at,
            s.end_at,
            s.total_seats,
            s.booked_seats,
            w.title,
            w.location
        FROM workshop_slots s
        JOIN workshops w ON w.id = s.workshop_id
        WHERE s.id = ? AND w.master_id = ?
        LIMIT 1
        """,
        (slot_id, user["id"]),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="slot not found")

    start = parse_dt(row["start_at"]).strftime("%Y%m%dT%H%M%SZ")
    end = parse_dt(row["end_at"]).strftime("%Y%m%dT%H%M%SZ")
    uid = f"master-slot-{row['id']}@mkmarket"
    dtstamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    details = (
        f"Слот мастер-класса MK-Маркет\\n"
        f"slot_id={row['id']}\\n"
        f"booked_seats={row['booked_seats']}\\n"
        f"total_seats={row['total_seats']}"
    )

    content = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//MK-Market//MasterSlot//RU\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{dtstamp}\r\n"
        f"DTSTART:{start}\r\n"
        f"DTEND:{end}\r\n"
        f"SUMMARY:{row['title']}\r\n"
        f"LOCATION:{row['location'] or ''}\r\n"
        f"DESCRIPTION:{details}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    headers = {"Content-Disposition": f"attachment; filename=master-slot-{row['id']}.ics"}
    return Response(content=content, media_type="text/calendar", headers=headers)


def normalize_review_media(raw_media) -> list[str]:
    media = raw_media or []
    if not isinstance(media, list):
        raise HTTPException(status_code=400, detail="media must be list")
    if len(media) > 3:
        raise HTTPException(status_code=400, detail="too many media items")

    normalized_media = []
    for item in media:
        media_item = str(item or "").strip()
        if not media_item:
            continue
        if not (media_item.startswith("data:image/") or media_item.startswith("data:video/")):
            raise HTTPException(status_code=400, detail="only image/video data urls are allowed")
        if len(media_item) > 16_000_000:
            raise HTTPException(status_code=400, detail="media item is too large")
        normalized_media.append(media_item)
    return normalized_media


def build_review_policy(conn: sqlite3.Connection, viewer: Optional[dict], master_id: int) -> dict:
    if not viewer:
        return {
            "can_add": False,
            "reason": "Войдите, чтобы оставить отзыв.",
            "error_code": "review login required",
            "booking_id": None,
        }

    viewer_id = int(viewer["id"] or 0)
    if viewer_id == int(master_id):
        return {
            "can_add": False,
            "reason": "Нельзя оставить отзыв самому себе.",
            "error_code": "self review forbidden",
            "booking_id": None,
        }

    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.id, s.start_at
        FROM bookings b
        JOIN workshop_slots s ON s.id = b.slot_id
        JOIN workshops w ON w.id = s.workshop_id
        WHERE b.user_id = ? AND w.master_id = ? AND b.status = 'booked'
        ORDER BY s.start_at DESC, b.id DESC
        """,
        (viewer_id, master_id),
    )
    booking_rows = [dict(row) for row in cur.fetchall()]
    if not booking_rows:
        return {
            "can_add": False,
            "reason": "Отзыв может оставить только человек, который был именно у этого мастера.",
            "error_code": "review allowed only for customer of this master",
            "booking_id": None,
        }

    now = utc_now()
    past_booking_ids: list[int] = []
    for row in booking_rows:
        start_at_raw = str(row.get("start_at") or "").strip()
        if not start_at_raw:
            continue
        try:
            start_at = parse_dt(start_at_raw)
        except Exception:
            continue
        if start_at <= now:
            past_booking_ids.append(int(row["id"]))

    if not past_booking_ids:
        return {
            "can_add": False,
            "reason": "Оставить отзыв можно только после посещения мастер-класса.",
            "error_code": "review allowed only after completed booking",
            "booking_id": None,
        }

    cur.execute(
        "SELECT COUNT(*) AS cnt FROM reviews WHERE master_id = ? AND user_id = ?",
        (master_id, viewer_id),
    )
    existing_reviews_count = int((cur.fetchone() or {"cnt": 0})["cnt"] or 0)
    if existing_reviews_count >= len(past_booking_ids):
        return {
            "can_add": False,
            "reason": "Вы уже оставили все доступные отзывы этому мастеру.",
            "error_code": "review already exists for completed booking",
            "booking_id": None,
        }

    cur.execute(
        "SELECT booking_id FROM reviews WHERE master_id = ? AND user_id = ? AND booking_id IS NOT NULL",
        (master_id, viewer_id),
    )
    used_booking_ids = {int(row["booking_id"]) for row in cur.fetchall() if row["booking_id"]}
    booking_id = next((bid for bid in past_booking_ids if bid not in used_booking_ids), past_booking_ids[0])
    return {
        "can_add": True,
        "reason": "Оставить отзыв можно только после посещения мастер-класса.",
        "error_code": "",
        "booking_id": int(booking_id),
    }


@app.post("/api/reviews")
def add_review(payload: dict, user=Depends(get_current_user)):
    master_id = int(payload.get("master_id") or 0)
    rating = int(payload.get("rating") or 0)
    text = (payload.get("text") or "").strip()
    media = payload.get("media") or []

    if rating < 1 or rating > 5:
        raise HTTPException(status_code=400, detail="rating must be from 1 to 5")
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    normalized_media = normalize_review_media(media)

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE id = ? AND role = 'master'", (master_id,))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="master not found")

    review_policy = build_review_policy(conn, user, master_id)
    if not review_policy["can_add"]:
        conn.close()
        raise HTTPException(status_code=403, detail=review_policy["error_code"])

    cur.execute(
        """
        INSERT INTO reviews (master_id, user_id, booking_id, rating, text, review_media_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            master_id,
            user["id"],
            int(review_policy["booking_id"] or 0),
            rating,
            text,
            json.dumps(normalized_media, ensure_ascii=False),
            utc_now_iso(),
        ),
    )
    conn.commit()
    review_id = cur.lastrowid
    conn.close()
    log_action(user["id"], "add_review", {"review_id": review_id, "master_id": master_id, "rating": rating})
    return {"id": review_id, "ok": True}


@app.put("/api/reviews/{review_id}")
def update_review(review_id: int, payload: dict, user=Depends(get_current_user)):
    rating = int(payload.get("rating") or 0)
    text = (payload.get("text") or "").strip()
    media_provided = "media" in payload
    media = payload.get("media") or []

    if rating < 1 or rating > 5:
        raise HTTPException(status_code=400, detail="rating must be from 1 to 5")
    if not text:
        raise HTTPException(status_code=400, detail="text required")

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, review_media_json, master_id FROM reviews WHERE id = ? AND user_id = ?", (review_id, user["id"]))
    review = cur.fetchone()
    if not review:
        conn.close()
        raise HTTPException(status_code=404, detail="review not found")

    if media_provided:
        normalized_media = normalize_review_media(media)
    else:
        try:
            parsed = json.loads(review["review_media_json"] or "[]")
            normalized_media = parsed if isinstance(parsed, list) else []
        except Exception:
            normalized_media = []

    cur.execute(
        """
        UPDATE reviews
        SET rating = ?, text = ?, review_media_json = ?, updated_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (rating, text, json.dumps(normalized_media, ensure_ascii=False), utc_now_iso(), review_id, user["id"]),
    )
    conn.commit()
    conn.close()
    log_action(user["id"], "update_review", {"review_id": review_id, "master_id": int(review["master_id"])})
    return {"ok": True}


@app.post("/api/reviews/{review_id}/reply")
def reply_review(review_id: int, payload: dict, user=Depends(get_current_user)):
    require_master(user)
    reply = (payload.get("reply") or "").strip()
    if not reply:
        raise HTTPException(status_code=400, detail="reply required")

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, master_id FROM reviews WHERE id = ?", (review_id,))
    review = cur.fetchone()
    if not review:
        conn.close()
        raise HTTPException(status_code=404, detail="review not found")
    if int(review["master_id"] or 0) != int(user["id"]):
        conn.close()
        raise HTTPException(status_code=403, detail="forbidden to reply")

    cur.execute("UPDATE reviews SET master_reply = ? WHERE id = ?", (reply, review_id))
    conn.commit()
    conn.close()
    log_action(user["id"], "reply_review", {"review_id": review_id})
    return {"ok": True}


@app.get("/api/admin/workshops")
def admin_workshops(user=Depends(get_current_user)):
    require_master(user)
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            w.id,
            w.title,
            w.workshop_type,
            w.description,
            w.location,
            w.price,
            w.duration_min,
            w.capacity,
            w.image_url,
            w.created_at,
            (
              SELECT COUNT(*)
              FROM bookings b
              JOIN workshop_slots s ON s.id = b.slot_id
              WHERE s.workshop_id = w.id AND b.status = 'queue'
            ) AS queue_count
        FROM workshops w
        WHERE w.master_id = ?
        ORDER BY w.id DESC
        """,
        (user["id"],),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.post("/api/admin/workshops")
def create_workshop(payload: dict, user=Depends(get_current_user)):
    require_master(user)
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    location = (payload.get("location") or "").strip()
    duration_min = int(payload.get("duration_min") or 0)
    image_url = (payload.get("image_url") or "").strip() or None

    raw_workshop_type = str(payload.get("workshop_type") or "").strip()
    workshop_type = normalize_workshop_type(raw_workshop_type, description)
    if not raw_workshop_type:
        workshop_type = "Групповой МК"

    raw_price = payload.get("price")
    try:
        price = int(raw_price) if raw_price not in (None, "") else 1
    except (TypeError, ValueError):
        price = 0

    raw_capacity = payload.get("capacity")
    try:
        capacity_seed = int(raw_capacity) if raw_capacity not in (None, "") else 0
    except (TypeError, ValueError):
        capacity_seed = 0
    if capacity_seed <= 0 and workshop_type == "Групповой МК":
        capacity_seed = 6
    capacity = normalize_workshop_capacity(workshop_type, capacity_seed)

    if not title:
        raise HTTPException(status_code=400, detail="title required")
    if price <= 0 or duration_min <= 0 or capacity <= 0:
        raise HTTPException(status_code=400, detail="price, duration_min, capacity must be > 0")

    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO workshops (master_id, title, workshop_type, description, location, price, duration_min, capacity, image_url, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user["id"], title, workshop_type, description, location, price, duration_min, capacity, image_url, utc_now_iso()),
    )
    conn.commit()
    workshop_id = cur.lastrowid
    conn.close()
    log_action(user["id"], "create_workshop", {"workshop_id": workshop_id, "title": title})
    return {"id": workshop_id, "ok": True}


@app.put("/api/admin/workshops/{workshop_id}")
def update_workshop(workshop_id: int, payload: dict, user=Depends(get_current_user)):
    require_master(user)
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    location = (payload.get("location") or "").strip()
    duration_min = int(payload.get("duration_min") or 0)
    image_url = (payload.get("image_url") or "").strip() or None

    if not title:
        raise HTTPException(status_code=400, detail="title required")
    if duration_min <= 0:
        raise HTTPException(status_code=400, detail="duration_min must be > 0")

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM workshops WHERE id = ? AND master_id = ?", (workshop_id, user["id"]))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="workshop not found")

    cur.execute(
        """
        UPDATE workshops
        SET title = ?, description = ?, location = ?, duration_min = ?, image_url = ?, updated_at = ?
        WHERE id = ? AND master_id = ?
        """,
        (title, description, location, duration_min, image_url, utc_now_iso(), workshop_id, user["id"]),
    )
    conn.commit()
    conn.close()
    log_action(user["id"], "update_workshop", {"workshop_id": workshop_id})
    return {"ok": True}


@app.delete("/api/admin/workshops/{workshop_id}")
def delete_workshop(workshop_id: int, user=Depends(get_current_user)):
    require_master(user)
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM workshops WHERE id = ? AND master_id = ?", (workshop_id, user["id"]))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="workshop not found")

    cur.execute("DELETE FROM workshops WHERE id = ? AND master_id = ?", (workshop_id, user["id"]))
    conn.commit()
    conn.close()
    log_action(user["id"], "delete_workshop", {"workshop_id": workshop_id})
    return {"ok": True}


@app.get("/api/admin/workshops/{workshop_id}/slots")
def admin_slots(workshop_id: int, user=Depends(get_current_user)):
    require_master(user)
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM workshops WHERE id = ? AND master_id = ?", (workshop_id, user["id"]))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="workshop not found")

    cur.execute(
        """
        SELECT id, start_at, end_at, workshop_type, price, total_seats, booked_seats,
               (total_seats - booked_seats) AS free_seats
        FROM workshop_slots
        WHERE workshop_id = ?
        ORDER BY start_at ASC
        """,
        (workshop_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.get("/api/admin/slots")
def admin_all_slots(user=Depends(get_current_user)):
    require_master(user)
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            s.id,
            s.workshop_id,
            s.start_at,
            s.end_at,
            s.workshop_type,
            s.price,
            s.total_seats,
            s.booked_seats,
            s.status,
            (s.total_seats - s.booked_seats) AS free_seats,
            w.title AS workshop_title
        FROM workshop_slots s
        JOIN workshops w ON w.id = s.workshop_id
        WHERE w.master_id = ?
        ORDER BY s.start_at ASC, s.id ASC
        """,
        (user["id"],),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


@app.post("/api/admin/workshops/{workshop_id}/slots")
def create_slot(workshop_id: int, payload: dict, user=Depends(get_current_user)):
    require_master(user)

    start_at = payload.get("start_at")
    end_at = payload.get("end_at")
    total_seats = int(payload.get("total_seats") or 0)
    if not start_at:
        raise HTTPException(status_code=400, detail="start_at required")

    start = parse_dt(start_at)

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, duration_min, workshop_type, price FROM workshops WHERE id = ? AND master_id = ?", (workshop_id, user["id"]))
    workshop = cur.fetchone()
    if not workshop:
        conn.close()
        raise HTTPException(status_code=404, detail="workshop not found")

    requested_type = str(payload.get("workshop_type") or "").strip()
    effective_type = normalize_workshop_type(requested_type or str(workshop["workshop_type"] or ""))

    requested_price = payload.get("price")
    try:
        effective_price = int(requested_price) if requested_price not in (None, "") else int(workshop["price"] or 0)
    except (TypeError, ValueError):
        effective_price = 0
    if effective_price <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="price must be > 0")

    total_seats = normalize_workshop_capacity(effective_type, total_seats)
    if total_seats <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="total_seats must be > 0")

    duration_min = int(workshop["duration_min"] or 0)
    if duration_min <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="workshop duration must be > 0")

    if end_at:
        end = parse_dt(end_at)
        if end <= start:
            conn.close()
            raise HTTPException(status_code=400, detail="end_at must be greater than start_at")
    else:
        end = start + timedelta(minutes=duration_min)

    cur.execute(
        """
        INSERT INTO workshop_slots (workshop_id, start_at, end_at, workshop_type, price, total_seats, booked_seats, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, 'open', ?)
        """,
        (workshop_id, start.isoformat(), end.isoformat(), effective_type, effective_price, total_seats, utc_now_iso()),
    )
    refresh_workshop_price_from_slots(conn, workshop_id)
    conn.commit()
    slot_id = cur.lastrowid
    conn.close()
    log_action(
        user["id"],
        "create_slot",
        {"workshop_id": workshop_id, "slot_id": slot_id, "workshop_type": effective_type, "price": effective_price, "total_seats": total_seats},
    )
    return {"id": slot_id, "ok": True}


@app.put("/api/admin/slots/{slot_id}")
def update_slot(slot_id: int, payload: dict, user=Depends(get_current_user)):
    require_master(user)
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            s.id,
            s.workshop_id,
            s.start_at,
            s.total_seats,
            s.booked_seats,
            s.workshop_type AS slot_workshop_type,
            s.price,
            w.duration_min,
            w.workshop_type AS workshop_default_type
        FROM workshop_slots s
        JOIN workshops w ON w.id = s.workshop_id
        WHERE s.id = ? AND w.master_id = ?
        """,
        (slot_id, user["id"]),
    )
    slot = cur.fetchone()
    if not slot:
        conn.close()
        raise HTTPException(status_code=404, detail="slot not found")

    requested_type = str(payload.get("workshop_type") or "").strip()
    effective_type = normalize_workshop_type(requested_type or str(slot["slot_workshop_type"] or "") or str(slot["workshop_default_type"] or ""))

    raw_seats = payload.get("total_seats")
    try:
        seats_seed = int(raw_seats) if raw_seats not in (None, "") else int(slot["total_seats"] or 0)
    except (TypeError, ValueError):
        seats_seed = 0
    total_seats = normalize_workshop_capacity(effective_type, seats_seed)
    if total_seats <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="total_seats must be > 0")
    if total_seats < int(slot["booked_seats"] or 0):
        conn.close()
        raise HTTPException(status_code=400, detail="total_seats cannot be less than booked_seats")

    raw_price = payload.get("price")
    try:
        effective_price = int(raw_price) if raw_price not in (None, "") else int(slot["price"] or 0)
    except (TypeError, ValueError):
        effective_price = 0
    if effective_price <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="price must be > 0")

    start_at_raw = payload.get("start_at")
    start = parse_dt(start_at_raw) if start_at_raw else parse_dt(str(slot["start_at"]))
    duration_min = int(slot["duration_min"] or 0)
    if duration_min <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="workshop duration must be > 0")
    end = start + timedelta(minutes=duration_min)

    cur.execute(
        """
        UPDATE workshop_slots
        SET start_at = ?, end_at = ?, workshop_type = ?, price = ?, total_seats = ?, updated_at = ?
        WHERE id = ?
        """,
        (start.isoformat(), end.isoformat(), effective_type, effective_price, total_seats, utc_now_iso(), slot_id),
    )
    refresh_workshop_price_from_slots(conn, int(slot["workshop_id"]))
    conn.commit()
    conn.close()
    log_action(
        user["id"],
        "update_slot",
        {"slot_id": slot_id, "workshop_id": int(slot["workshop_id"]), "price": effective_price, "total_seats": total_seats},
    )
    return {"ok": True}


@app.delete("/api/admin/slots/{slot_id}")
def delete_slot(slot_id: int, user=Depends(get_current_user)):
    require_master(user)
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT s.id, s.workshop_id
        FROM workshop_slots s
        JOIN workshops w ON w.id = s.workshop_id
        WHERE s.id = ? AND w.master_id = ?
        """,
        (slot_id, user["id"]),
    )
    slot = cur.fetchone()
    if not slot:
        conn.close()
        raise HTTPException(status_code=404, detail="slot not found")

    cur.execute(
        "SELECT COUNT(*) AS cnt FROM bookings WHERE slot_id = ? AND status IN ('booked', 'queue')",
        (slot_id,),
    )
    active_bookings = int((cur.fetchone() or {"cnt": 0})["cnt"] or 0)
    if active_bookings > 0:
        conn.close()
        raise HTTPException(status_code=400, detail="slot has active bookings")

    cur.execute("DELETE FROM workshop_slots WHERE id = ?", (slot_id,))
    refresh_workshop_price_from_slots(conn, int(slot["workshop_id"]))
    conn.commit()
    conn.close()
    log_action(user["id"], "delete_slot", {"slot_id": slot_id, "workshop_id": int(slot["workshop_id"])})
    return {"ok": True}


@app.get("/api/admin/slots/{slot_id}/people")
def admin_slot_people(slot_id: int, user=Depends(get_current_user)):
    require_master(user)
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT s.id, s.start_at, w.id AS workshop_id, w.title AS workshop_title
        FROM workshop_slots s
        JOIN workshops w ON w.id = s.workshop_id
        WHERE s.id = ? AND w.master_id = ?
        LIMIT 1
        """,
        (slot_id, user["id"]),
    )
    slot = cur.fetchone()
    if not slot:
        conn.close()
        raise HTTPException(status_code=404, detail="slot not found")

    cur.execute(
        """
        SELECT
            b.id,
            b.user_id,
            b.guests,
            b.status,
            b.created_at,
            b.updated_at,
            u.name AS user_name,
            u.email AS user_email
        FROM bookings b
        JOIN users u ON u.id = b.user_id
        WHERE b.slot_id = ? AND b.status = 'booked'
        ORDER BY b.created_at ASC, b.id ASC
        """,
        (slot_id,),
    )
    people = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"slot": dict(slot), "people": people}


@app.get("/api/admin/queue")
def admin_queue(user=Depends(get_current_user)):
    require_master(user)
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.id, b.guests, b.status, b.created_at,
               s.id AS slot_id, s.start_at,
               w.id AS workshop_id, w.title,
               u.name AS user_name, u.email AS user_email
        FROM bookings b
        JOIN workshop_slots s ON s.id = b.slot_id
        JOIN workshops w ON w.id = s.workshop_id
        JOIN users u ON u.id = b.user_id
        WHERE w.master_id = ? AND b.status = 'queue'
        ORDER BY s.start_at ASC, b.id ASC
        """,
        (user["id"],),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


app.mount("/", StaticFiles(directory="static", html=True), name="static")
