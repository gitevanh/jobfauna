"""
database.py
-----------
All SQLite reading/writing. Uses Python's built-in sqlite3.

Tables:
  users   - accounts (admin + regular), with an approval status
  jobs    - job applications, each owned by a user (user_id)
  tokens  - API tokens for the extension, each owned by a user
  meta    - key/value for the cookie signing key
"""

import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "jobs.db")
STATUSES = ["saved", "applied", "interview", "offer", "rejected"]


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat()


def _column_exists(conn, table, column):
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c["name"] == column for c in cols)


def init_db():
    """Create tables if missing, and migrate older databases in place."""
    conn = _connect()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT    NOT NULL UNIQUE,
            name          TEXT    NOT NULL DEFAULT '',
            password_hash TEXT    NOT NULL,
            status        TEXT    NOT NULL DEFAULT 'pending',   -- pending | approved | disabled
            role          TEXT    NOT NULL DEFAULT 'user',      -- user | admin
            note          TEXT    NOT NULL DEFAULT '',
            profile       TEXT    NOT NULL DEFAULT '',
            cv            TEXT    NOT NULL DEFAULT '',
            created_at    TEXT    NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            company     TEXT    NOT NULL DEFAULT '',
            title       TEXT    NOT NULL DEFAULT '',
            url         TEXT    NOT NULL DEFAULT '',
            location    TEXT    NOT NULL DEFAULT '',
            salary      TEXT    NOT NULL DEFAULT '',
            description TEXT    NOT NULL DEFAULT '',
            summary     TEXT    NOT NULL DEFAULT '',
            category    TEXT    NOT NULL DEFAULT '',
            fit_score   INTEGER NOT NULL DEFAULT 0,
            status      TEXT    NOT NULL DEFAULT 'saved',
            notes       TEXT    NOT NULL DEFAULT '',
            source      TEXT    NOT NULL DEFAULT 'manual',
            cover_letter TEXT   NOT NULL DEFAULT '',
            tailored_cv  TEXT   NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tokens (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            name        TEXT NOT NULL DEFAULT '',
            token_hash  TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
        """
    )

    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )

    # --- migrations for databases created by an earlier version ---
    if not _column_exists(conn, "jobs", "user_id"):
        conn.execute("ALTER TABLE jobs ADD COLUMN user_id INTEGER")
    if not _column_exists(conn, "tokens", "user_id"):
        conn.execute("ALTER TABLE tokens ADD COLUMN user_id INTEGER")
    for col in ("cover_letter", "tailored_cv"):
        if not _column_exists(conn, "jobs", col):
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
    for col in ("profile", "cv"):
        if not _column_exists(conn, "users", col):
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")

    conn.commit()
    conn.close()


# ===========================================================================
# meta (cookie signing key)
# ===========================================================================
def get_meta(key):
    conn = _connect()
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_meta(key, value):
    conn = _connect()
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def delete_meta(key):
    conn = _connect()
    conn.execute("DELETE FROM meta WHERE key = ?", (key,))
    conn.commit()
    conn.close()


def set_user_password(user_id, password_hash):
    conn = _connect()
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
    conn.commit()
    conn.close()


def set_user_profile(user_id, cv, profile):
    conn = _connect()
    conn.execute("UPDATE users SET cv = ?, profile = ? WHERE id = ?", (cv, profile, user_id))
    conn.commit()
    conn.close()


# ===========================================================================
# users
# ===========================================================================
def count_users():
    conn = _connect()
    n = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    conn.close()
    return n


def create_user(email, name, password_hash, status="pending", role="user", note=""):
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO users (email, name, password_hash, status, role, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (email.lower().strip(), name, password_hash, status, role, note, _now()),
    )
    conn.commit()
    uid = cur.lastrowid
    conn.close()
    return get_user(uid)


def get_user(user_id):
    conn = _connect()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_email(email):
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_users():
    conn = _connect()
    rows = conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_user(user_id, fields):
    allowed = ["name", "status", "role"]
    f = {k: fields[k] for k in allowed if k in fields}
    if not f:
        return get_user(user_id)
    set_clause = ", ".join(f"{k} = ?" for k in f)
    conn = _connect()
    conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", list(f.values()) + [user_id])
    conn.commit()
    conn.close()
    return get_user(user_id)


def delete_user(user_id):
    conn = _connect()
    conn.execute("DELETE FROM jobs WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))
    cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def count_admins():
    conn = _connect()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND status = 'approved'"
    ).fetchone()["n"]
    conn.close()
    return n


# ===========================================================================
# jobs (always scoped to a user_id)
# ===========================================================================
def list_jobs(user_id):
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_job(job_id, user_id):
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM jobs WHERE id = ? AND user_id = ?", (job_id, user_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_job(data, user_id):
    now = _now()
    conn = _connect()
    cur = conn.execute(
        """
        INSERT INTO jobs
            (user_id, company, title, url, location, salary, description, summary,
             category, fit_score, status, notes, source, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            data.get("company", ""), data.get("title", ""), data.get("url", ""),
            data.get("location", ""), data.get("salary", ""), data.get("description", ""),
            data.get("summary", ""), data.get("category", ""),
            int(data.get("fit_score", 0) or 0), data.get("status", "saved"),
            data.get("notes", ""), data.get("source", "manual"), now, now,
        ),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return get_job(new_id, user_id)


def update_job(job_id, data, user_id):
    existing = get_job(job_id, user_id)
    if not existing:
        return None
    allowed = [
        "company", "title", "url", "location", "salary", "description",
        "summary", "category", "fit_score", "status", "notes", "source",
        "cover_letter", "tailored_cv",
    ]
    fields = {k: data[k] for k in allowed if k in data}
    if not fields:
        return existing
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [job_id, user_id]
    conn = _connect()
    conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ? AND user_id = ?", values)
    conn.commit()
    conn.close()
    return get_job(job_id, user_id)


def delete_job(job_id, user_id):
    conn = _connect()
    cur = conn.execute(
        "DELETE FROM jobs WHERE id = ? AND user_id = ?", (job_id, user_id)
    )
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def claim_orphan_jobs(user_id):
    """Assign any jobs left over from the single-user version to this user."""
    conn = _connect()
    conn.execute("UPDATE jobs SET user_id = ? WHERE user_id IS NULL", (user_id,))
    conn.commit()
    conn.close()


# ===========================================================================
# tokens (scoped to a user)
# ===========================================================================
def add_token(user_id, name, token_hash):
    conn = _connect()
    conn.execute(
        "INSERT INTO tokens (user_id, name, token_hash, created_at) VALUES (?, ?, ?, ?)",
        (user_id, name, token_hash, _now()),
    )
    conn.commit()
    conn.close()


def list_tokens(user_id):
    conn = _connect()
    rows = conn.execute(
        "SELECT id, name, created_at FROM tokens WHERE user_id = ? ORDER BY created_at",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def all_token_hashes():
    """Returns list of (user_id, token_hash) for auth resolution."""
    conn = _connect()
    rows = conn.execute("SELECT user_id, token_hash FROM tokens").fetchall()
    conn.close()
    return [(r["user_id"], r["token_hash"]) for r in rows]


def delete_token(token_id, user_id):
    conn = _connect()
    cur = conn.execute(
        "DELETE FROM tokens WHERE id = ? AND user_id = ?", (token_id, user_id)
    )
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted
