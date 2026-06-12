"""
enrich.py
---------
OPTIONAL Claude-powered enrichment. When a job is saved, this can:
  - write a 1-2 sentence plain-English summary of the role
  - tag it with a category (e.g. sysadmin / cloud / it-support)
  - give it a 0-100 "fit score" against YOUR background

This is completely optional. If you don't set an ANTHROPIC_API_KEY environment
variable, the app still works perfectly — it just skips this step.

To turn it on:
  1. Get a key from https://console.anthropic.com/
  2. Set it as an environment variable named ANTHROPIC_API_KEY (see the README).
  3. (Optional) Edit profile.txt to describe yourself so the fit score is accurate.
"""

import os
import json

import database

# Default model for the quick tagging/scoring (cheap + fast). The admin can
# override this in the UI; get_model() reads the saved choice or this default.
DEFAULT_ENRICH_MODEL = "claude-haiku-4-5"


def get_model():
    return database.get_meta("enrich_model") or DEFAULT_ENRICH_MODEL

# Where to find the "about me" text used for fit scoring.
PROFILE_PATH = os.path.join(os.path.dirname(__file__), "profile.txt")

# Used if profile.txt is missing. Edit profile.txt instead of this.
DEFAULT_PROFILE = (
    "IT / systems administration professional. Skills: Windows & Linux admin, "
    "PowerShell/Bash/Python scripting, endpoint management, virtualization, "
    "Azure and cloud basics. Looking for sysadmin, IT support, and "
    "infrastructure roles."
)


def get_api_key():
    """
    The Anthropic key, from either:
      1. the ANTHROPIC_API_KEY environment variable (good for advanced setups), or
      2. a value an admin saved in the dashboard (good for simple self-hosting).
    Returns None if neither is set.
    """
    return os.environ.get("ANTHROPIC_API_KEY") or database.get_meta("anthropic_api_key")


def is_enabled():
    """True if an API key is configured (env or admin-set)."""
    return bool(get_api_key())


def _load_profile():
    if os.path.exists(PROFILE_PATH):
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            text = f.read().strip()
            if text:
                return text
    return DEFAULT_PROFILE


def enrich(job):
    """
    Given a job dict (with at least title/company/description), return a dict
    with keys: summary, category, fit_score.

    Never raises — if anything goes wrong (no key, network issue, bad response)
    it just returns empty/zero values so saving the job always succeeds.
    """
def enrich(job, profile=None):
    """
    Given a job dict (with at least title/company/description), return a dict
    with keys: summary, category, fit_score.

    `profile` is the candidate's background used for fit scoring. If not given,
    falls back to profile.txt / the default.

    Never raises — if anything goes wrong (no key, network issue, bad response)
    it just returns empty/zero values so saving the job always succeeds.
    """
    if not is_enabled():
        return {"summary": "", "category": "", "fit_score": 0}

    try:
        import anthropic  # imported here so the app loads even if not installed

        client = anthropic.Anthropic(api_key=get_api_key())
        profile = (profile or "").strip() or _load_profile()

        # Keep the description from blowing up the prompt.
        description = (job.get("description") or "")[:6000]

        prompt = (
            "You are helping someone track job applications. Here is a job:\n\n"
            f"Title: {job.get('title', '')}\n"
            f"Company: {job.get('company', '')}\n"
            f"Location: {job.get('location', '')}\n"
            f"Description:\n{description}\n\n"
            "Here is the person applying:\n"
            f"{profile}\n\n"
            "Respond with ONLY a JSON object (no markdown, no backticks, no extra text) "
            "with exactly these keys:\n"
            '  "summary": a single plain-English sentence describing the role,\n'
            '  "category": one short lowercase tag from this list that fits best '
            "[sysadmin, cloud, it-support, devops, security, helpdesk, networking, "
            "software, data, other],\n"
            '  "fit_score": an integer 0-100 for how well this person matches the role.\n'
        )

        message = client.messages.create(
            model=get_model(),
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )

        # Pull the text out of the response and parse the JSON.
        raw = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        ).strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)

        return {
            "summary": str(parsed.get("summary", ""))[:500],
            "category": str(parsed.get("category", ""))[:40],
            "fit_score": max(0, min(100, int(parsed.get("fit_score", 0)))),
        }
    except Exception as e:
        # Enrichment is a nice-to-have; never let it break saving a job.
        print(f"[enrich] skipped ({type(e).__name__}: {e})")
        return {"summary": "", "category": "", "fit_score": 0}
