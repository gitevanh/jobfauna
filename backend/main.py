"""
main.py
-------
Run with:  python main.py   ->  http://localhost:8000

First visit with an empty database shows a one-time "create admin" setup.
After that: people can Request Access, and an admin approves them.
Every user has their own private board.
"""

import os
import re
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database
import enrich
import generate
import documents
import auth
import ratelimit

app = FastAPI(title="Job Application Tracker")

# Rate limiters (per client IP):
#   login   — blunt brute-force/credential-stuffing defense on the password check
#   signup  — keeps the access-request queue from being flooded
login_limiter = ratelimit.SlidingWindowLimiter(max_attempts=10, window_seconds=600)   # 10 / 10 min
signup_limiter = ratelimit.SlidingWindowLimiter(max_attempts=5, window_seconds=3600)   # 5 / hour

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

# Serve the decoupled CSS/JS (and any future assets) under /static.
app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")


@app.on_event("startup")
def startup():
    database.init_db()
    if database.count_users() == 0:
        print("\n  First run: open http://localhost:8000 to create your admin account.\n")


# ===========================================================================
# Auth dependencies
# ===========================================================================
def require_user(request: Request):
    user = auth.current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(request: Request):
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user


def _set_session_cookie(response: Response, user_id: int):
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=auth.make_session_token(user_id),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=auth.COOKIE_SECURE,
    )


def _public_user(u):
    return {"id": u["id"], "email": u["email"], "name": u["name"], "role": u["role"]}


DEFAULT_INSTANCE_NAME = "JobFauna"
DEFAULT_INSTANCE_LOGO = "🌿"
DEFAULT_TAGLINE = "Track every application in one place."


def _branding():
    return {
        "instance_name": database.get_meta("instance_name") or DEFAULT_INSTANCE_NAME,
        "instance_logo": database.get_meta("instance_logo") or DEFAULT_INSTANCE_LOGO,
        "instance_tagline": database.get_meta("login_tagline") or DEFAULT_TAGLINE,
        "logo_url": database.get_meta("logo_url") or "",
    }


def _valid_email(email):
    e = (email or "").strip()
    return "@" in e and "." in e.split("@")[-1] and len(e) <= 254


def _safe_filename(name):
    name = re.sub(r"[^A-Za-z0-9 _.-]", "", name or "").strip()
    return (name or "document")[:80]


# ===========================================================================
# Models
# ===========================================================================
class SetupIn(BaseModel):
    email: str
    name: Optional[str] = ""
    password: str


class RequestAccessIn(BaseModel):
    email: str
    name: Optional[str] = ""
    password: str
    note: Optional[str] = ""


class LoginIn(BaseModel):
    email: str
    password: str


class JobIn(BaseModel):
    company: Optional[str] = ""
    title: Optional[str] = ""
    url: Optional[str] = ""
    location: Optional[str] = ""
    salary: Optional[str] = ""
    description: Optional[str] = ""
    notes: Optional[str] = ""
    status: Optional[str] = "saved"
    source: Optional[str] = "manual"


class JobUpdate(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    location: Optional[str] = None
    salary: Optional[str] = None
    description: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    fit_score: Optional[int] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    cover_letter: Optional[str] = None
    tailored_cv: Optional[str] = None


class ProfileIn(BaseModel):
    cv: Optional[str] = ""
    profile: Optional[str] = ""


class RenderIn(BaseModel):
    body: str
    title: Optional[str] = None
    filename: Optional[str] = "document"


class TokenIn(BaseModel):
    name: Optional[str] = "extension"


class AdminUserIn(BaseModel):
    email: str
    name: Optional[str] = ""
    password: str
    role: Optional[str] = "user"


class AdminUserUpdate(BaseModel):
    status: Optional[str] = None   # approved | disabled | pending
    role: Optional[str] = None     # admin | user
    name: Optional[str] = None


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class AdminSettingsIn(BaseModel):
    instance_name: Optional[str] = None
    instance_logo: Optional[str] = None
    login_tagline: Optional[str] = None
    logo_url: Optional[str] = None
    anthropic_api_key: Optional[str] = None   # "" clears it
    enrich_model: Optional[str] = None        # "" reverts to default
    writing_model: Optional[str] = None       # "" reverts to default


# ===========================================================================
# Public auth endpoints
# ===========================================================================
@app.get("/api/me")
def me(request: Request):
    user = auth.current_user(request)
    return {
        "needs_setup": database.count_users() == 0,
        "authenticated": user is not None,
        "user": _public_user(user) if user else None,
        "enrichment_enabled": enrich.is_enabled(),
        **_branding(),
    }


@app.post("/api/setup")
def setup(body: SetupIn, response: Response):
    """Create the first admin. Only works while there are zero users."""
    if database.count_users() != 0:
        raise HTTPException(status_code=403, detail="Setup already completed")
    if not _valid_email(body.email):
        raise HTTPException(status_code=400, detail="Enter a valid email")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Use at least 8 characters")
    user = database.create_user(
        email=body.email, name=body.name or "",
        password_hash=auth.hash_password(body.password),
        status="approved", role="admin",
    )
    database.claim_orphan_jobs(user["id"])  # adopt any jobs from the single-user version
    _set_session_cookie(response, user["id"])
    return {"ok": True, "user": _public_user(user)}


@app.post("/api/request-access")
def request_access(body: RequestAccessIn, request: Request):
    """Anyone can submit this. It creates a PENDING account for an admin to approve."""
    ip = ratelimit.client_ip(request)
    key = f"signup:{ip}"
    if not signup_limiter.allowed(key):
        wait = signup_limiter.retry_after(key)
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests from your network. Try again in about {wait // 60 + 1} minutes.",
            headers={"Retry-After": str(wait)},
        )
    signup_limiter.record(key)

    if not _valid_email(body.email):
        raise HTTPException(status_code=400, detail="Enter a valid email")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Use at least 8 characters")
    if database.get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    database.create_user(
        email=body.email, name=body.name or "",
        password_hash=auth.hash_password(body.password),
        status="pending", role="user", note=(body.note or "")[:500],
    )
    return {"ok": True}


@app.post("/api/login")
def login(body: LoginIn, request: Request, response: Response):
    ip = ratelimit.client_ip(request)
    key = f"login:{ip}"
    if not login_limiter.allowed(key):
        wait = login_limiter.retry_after(key)
        raise HTTPException(
            status_code=429,
            detail=f"Too many sign-in attempts. Try again in about {wait} seconds.",
            headers={"Retry-After": str(wait)},
        )

    user = database.get_user_by_email(body.email)
    # Always run a verify to keep timing roughly constant whether or not the user exists.
    stored = user["password_hash"] if user else auth.hash_password("dummy-placeholder")
    ok = auth.verify_password(stored, body.password)
    if not user or not ok:
        login_limiter.record(key)  # only wrong email/password counts toward the limit
        raise HTTPException(status_code=401, detail="Wrong email or password")

    # Correct credentials -> clearly not a brute-force attempt; clear the counter.
    login_limiter.reset(key)
    if user["status"] == "pending":
        raise HTTPException(status_code=403, detail="Your access request is awaiting approval")
    if user["status"] != "approved":
        raise HTTPException(status_code=403, detail="This account is disabled")
    _set_session_cookie(response, user["id"])
    return {"ok": True, "user": _public_user(user)}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


# ===========================================================================
# Jobs (per-user)
# ===========================================================================
@app.get("/api/jobs")
def get_jobs(user=Depends(require_user)):
    return database.list_jobs(user["id"])


@app.post("/api/jobs")
def add_job(job: JobIn, user=Depends(require_user)):
    data = job.model_dump()
    data.update(enrich.enrich(data, profile=user.get("profile", "")))
    return database.create_job(data, user["id"])


@app.patch("/api/jobs/{job_id}")
def edit_job(job_id: int, job: JobUpdate, user=Depends(require_user)):
    data = {k: v for k, v in job.model_dump().items() if v is not None}
    updated = database.update_job(job_id, data, user["id"])
    if not updated:
        raise HTTPException(status_code=404, detail="Job not found")
    return updated


@app.post("/api/jobs/{job_id}/enrich")
def reenrich_job(job_id: int, user=Depends(require_user)):
    job = database.get_job(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not enrich.is_enabled():
        raise HTTPException(status_code=400, detail="Enrichment is not configured")
    return database.update_job(job_id, enrich.enrich(job, profile=user.get("profile", "")), user["id"])


@app.post("/api/jobs/{job_id}/cover-letter")
def make_cover_letter(job_id: int, user=Depends(require_user)):
    job = database.get_job(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not enrich.is_enabled():
        raise HTTPException(status_code=400, detail="Add an AI key (Admin → Instance settings) to use this")
    try:
        letter = generate.generate_cover_letter(
            job, user.get("cv", ""), user.get("profile", ""), name=user.get("name", "")
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Generation failed: {type(e).__name__}")
    database.update_job(job_id, {"cover_letter": letter}, user["id"])
    return {"cover_letter": letter}


@app.post("/api/jobs/{job_id}/tailor-cv")
def make_tailored_cv(job_id: int, user=Depends(require_user)):
    job = database.get_job(job_id, user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not enrich.is_enabled():
        raise HTTPException(status_code=400, detail="Add an AI key (Admin → Instance settings) to use this")
    try:
        tailored = generate.tailor_cv(job, user.get("cv", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Generation failed: {type(e).__name__}")
    database.update_job(job_id, {"tailored_cv": tailored}, user["id"])
    return {"tailored_cv": tailored}


@app.delete("/api/jobs/{job_id}")
def remove_job(job_id: int, user=Depends(require_user)):
    if not database.delete_job(job_id, user["id"]):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"deleted": True}


# ===========================================================================
# API tokens (per-user, for the extension)
# ===========================================================================
@app.get("/api/tokens")
def get_tokens(user=Depends(require_user)):
    return database.list_tokens(user["id"])


@app.post("/api/tokens")
def make_token(body: TokenIn, user=Depends(require_user)):
    raw = auth.create_token(user["id"], (body.name or "extension")[:40])
    return {"token": raw}  # shown once


@app.delete("/api/tokens/{token_id}")
def remove_token(token_id: int, user=Depends(require_user)):
    if not database.delete_token(token_id, user["id"]):
        raise HTTPException(status_code=404, detail="Token not found")
    return {"deleted": True}


@app.post("/api/account/password")
def change_password(body: PasswordChangeIn, user=Depends(require_user)):
    if not auth.verify_password(user["password_hash"], body.current_password):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    database.set_user_password(user["id"], auth.hash_password(body.new_password))
    return {"ok": True}


@app.get("/api/account/profile")
def get_profile(user=Depends(require_user)):
    return {"cv": user.get("cv", ""), "profile": user.get("profile", "")}


@app.put("/api/account/profile")
def put_profile(body: ProfileIn, user=Depends(require_user)):
    database.set_user_profile(user["id"], (body.cv or "")[:30000], (body.profile or "")[:4000])
    return {"ok": True}


@app.post("/api/account/cv-upload")
async def upload_cv(file: UploadFile = File(...), user=Depends(require_user)):
    """Extract text from an uploaded CV (PDF/DOCX/TXT) and return it for review."""
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 8 MB)")
    try:
        text = documents.extract_text(file.filename or "", data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=400, detail="Couldn't read that file. Try a PDF, DOCX, or TXT.")
    if not text.strip():
        raise HTTPException(status_code=400, detail="No text found in that file (is it a scanned image?)")
    return {"text": text[:30000]}


@app.post("/api/render/{fmt}")
def render_document(fmt: str, body: RenderIn, user=Depends(require_user)):
    """Render arbitrary text (a cover letter or CV) to a downloadable .docx or .pdf."""
    if fmt not in ("docx", "pdf"):
        raise HTTPException(status_code=400, detail="Unknown format")
    text = (body.body or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Nothing to render")

    fname = f"{_safe_filename(body.filename)}.{fmt}"
    if fmt == "docx":
        data = documents.build_docx(text, body.title)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        data = documents.build_pdf(text, body.title)
        media = "application/pdf"

    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ===========================================================================
# Admin: user management
# ===========================================================================
@app.get("/api/admin/users")
def admin_list_users(admin=Depends(require_admin)):
    users = database.list_users()
    return [
        {k: u[k] for k in ("id", "email", "name", "status", "role", "note", "created_at")}
        for u in users
    ]


@app.post("/api/admin/users")
def admin_create_user(body: AdminUserIn, admin=Depends(require_admin)):
    if not _valid_email(body.email):
        raise HTTPException(status_code=400, detail="Enter a valid email")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Use at least 8 characters")
    if database.get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="Email already exists")
    role = "admin" if body.role == "admin" else "user"
    user = database.create_user(
        email=body.email, name=body.name or "",
        password_hash=auth.hash_password(body.password),
        status="approved", role=role,
    )
    return {k: user[k] for k in ("id", "email", "name", "status", "role")}


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, body: AdminUserUpdate, admin=Depends(require_admin)):
    target = database.get_user(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}

    # Don't let the last admin lock everyone out.
    demoting = (fields.get("role") == "user" and target["role"] == "admin")
    disabling = (fields.get("status") in ("disabled", "pending") and target["status"] == "approved" and target["role"] == "admin")
    if (demoting or disabling) and database.count_admins() <= 1:
        raise HTTPException(status_code=400, detail="Can't remove the last admin")

    updated = database.update_user(user_id, fields)
    return {k: updated[k] for k in ("id", "email", "name", "status", "role")}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, admin=Depends(require_admin)):
    target = database.get_user(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["role"] == "admin" and target["status"] == "approved" and database.count_admins() <= 1:
        raise HTTPException(status_code=400, detail="Can't delete the last admin")
    database.delete_user(user_id)
    return {"deleted": True}


@app.get("/api/admin/settings")
def admin_get_settings(admin=Depends(require_admin)):
    """Branding + whether an AI key is set. The key itself is never returned."""
    return {
        **_branding(),
        "ai_key_set": bool(database.get_meta("anthropic_api_key")),
        "ai_key_from_env": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "enrich_model": enrich.get_model(),
        "writing_model": generate.get_model(),
        "default_enrich_model": enrich.DEFAULT_ENRICH_MODEL,
        "default_writing_model": generate.DEFAULT_WRITING_MODEL,
    }


@app.get("/api/admin/models")
def admin_list_models(admin=Depends(require_admin)):
    """List models available on the configured API key, for the settings dropdowns."""
    if not enrich.is_enabled():
        return {"models": []}
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=enrich.get_api_key())
        ids = [m.id for m in client.models.list(limit=100)]
        return {"models": ids}
    except Exception:
        return {"models": []}


@app.patch("/api/admin/settings")
def admin_update_settings(body: AdminSettingsIn, admin=Depends(require_admin)):
    if body.instance_name is not None:
        name = body.instance_name.strip()[:40] or DEFAULT_INSTANCE_NAME
        database.set_meta("instance_name", name)
    if body.instance_logo is not None:
        database.set_meta("instance_logo", body.instance_logo.strip()[:8] or DEFAULT_INSTANCE_LOGO)
    if body.login_tagline is not None:
        database.set_meta("login_tagline", body.login_tagline.strip()[:120] or DEFAULT_TAGLINE)
    if body.logo_url is not None:
        url = body.logo_url.strip()
        if url:
            database.set_meta("logo_url", url[:500])
        else:
            database.delete_meta("logo_url")
    if body.anthropic_api_key is not None:
        key = body.anthropic_api_key.strip()
        if key:
            database.set_meta("anthropic_api_key", key)
        else:
            database.delete_meta("anthropic_api_key")  # empty string clears it
    if body.enrich_model is not None:
        m = body.enrich_model.strip()
        database.set_meta("enrich_model", m) if m else database.delete_meta("enrich_model")
    if body.writing_model is not None:
        m = body.writing_model.strip()
        database.set_meta("writing_model", m) if m else database.delete_meta("writing_model")
    return admin_get_settings(admin)


# ===========================================================================
# Pages (must be last)
# ===========================================================================
@app.get("/login")
def login_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))


@app.get("/")
def dashboard():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    print("\n  Job Tracker starting on http://localhost:8000\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)
