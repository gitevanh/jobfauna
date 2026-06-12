"""
auth.py
-------
Login, sessions, API tokens, and user resolution.

Security choices:
  - Passwords hashed with Argon2id (OWASP-recommended). Plaintext never stored.
  - Sessions are signed, time-limited tokens in an HttpOnly cookie (XSS-resistant).
    The token carries the user id, so each request knows who is making it.
  - Extension API tokens are random; only their SHA-256 hash is stored, compared
    in constant time. Each token belongs to a specific user.
  - Only users with status 'approved' can authenticate. 'pending' (awaiting admin
    approval) and 'disabled' accounts are rejected.
"""

import os
import hmac
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

import database

ph = PasswordHasher()

COOKIE_NAME = "jobtracker_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"


# --------------------------------------------------------------------------
# Cookie signing key
# --------------------------------------------------------------------------
def _secret():
    env = os.environ.get("JOBTRACKER_SECRET")
    if env:
        return env
    stored = database.get_meta("secret_key")
    if not stored:
        stored = secrets.token_urlsafe(48)
        database.set_meta("secret_key", stored)
    return stored


def _serializer():
    return URLSafeTimedSerializer(_secret(), salt="jobtracker-session-v2")


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------
def hash_password(plaintext):
    return ph.hash(plaintext)


def verify_password(stored_hash, plaintext):
    try:
        ph.verify(stored_hash, plaintext)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


# --------------------------------------------------------------------------
# Session cookies (carry the user id)
# --------------------------------------------------------------------------
def make_session_token(user_id):
    return _serializer().dumps({"uid": user_id})


def session_user_id(token):
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
        return data.get("uid")
    except (BadSignature, SignatureExpired):
        return None


# --------------------------------------------------------------------------
# API tokens (extension) -> resolve to a user id
# --------------------------------------------------------------------------
def _hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def create_token(user_id, name="extension"):
    raw = secrets.token_urlsafe(32)
    database.add_token(user_id, name, _hash_token(raw))
    return raw


def token_user_id(raw):
    if not raw:
        return None
    incoming = _hash_token(raw)
    for uid, stored in database.all_token_hashes():
        if hmac.compare_digest(incoming, stored):
            return uid
    return None


# --------------------------------------------------------------------------
# Resolve the current user from a request (cookie OR bearer token)
# --------------------------------------------------------------------------
def current_user(request):
    """Return the authenticated, approved user dict, or None."""
    uid = None

    authz = request.headers.get("Authorization", "")
    if authz.startswith("Bearer "):
        uid = token_user_id(authz[7:].strip())

    if uid is None:
        uid = session_user_id(request.cookies.get(COOKIE_NAME))

    if uid is None:
        return None

    user = database.get_user(uid)
    if not user or user["status"] != "approved":
        return None
    return user
