"""
generate.py
-----------
Longer-form AI generation: cover letters and CV tailoring.

Unlike enrich.py (which silently degrades because it runs in the background),
these are triggered explicitly by the user, so on failure they RAISE — the
endpoint turns that into a clear error message.

Uses a stronger "writing" model than the enrichment tagger. Cover letters and
CV tailoring are longer outputs, so they cost more per run than enrichment —
they only run when the user clicks the button, never automatically.
"""

import enrich  # reuse the API-key resolution (env var or admin-set)
import database

# Default writing model for cover letters / CV tailoring. Admin-overridable.
DEFAULT_WRITING_MODEL = "claude-sonnet-4-6"


def get_model():
    return database.get_meta("writing_model") or DEFAULT_WRITING_MODEL


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=enrich.get_api_key())


def _text(message):
    return "".join(
        b.text for b in message.content if getattr(b, "type", "") == "text"
    ).strip()


def generate_cover_letter(job, cv, profile, name=""):
    """
    Write a tailored cover letter from the job + the candidate's real background.
    Honesty is enforced in the prompt: it must not invent experience.
    """
    job_block = (
        f"Job title: {job.get('title','')}\n"
        f"Company: {job.get('company','')}\n"
        f"Location: {job.get('location','')}\n"
        f"Summary: {job.get('summary','')}\n"
        f"Full description:\n{(job.get('description') or '')[:6000]}\n"
    )
    candidate = (cv or "").strip() or (profile or "").strip() or "(no CV provided)"

    prompt = (
        "Write a professional cover letter for the candidate below, tailored to this "
        "specific job. Requirements:\n"
        "- 250-350 words, confident but not generic or flowery.\n"
        "- Draw ONLY on facts present in the candidate's CV/background. Do NOT invent "
        "employers, titles, dates, metrics, or skills the candidate didn't list.\n"
        "- Open by connecting the candidate's real strengths to what the role needs.\n"
        "- Plain text only (no markdown). Include a greeting and a sign-off"
        + (f" signed '{name}'." if name else ".")
        + "\n\n=== JOB ===\n" + job_block
        + "\n=== CANDIDATE CV / BACKGROUND ===\n" + candidate[:8000]
        + "\n\nReturn only the letter."
    )

    msg = _client().messages.create(
        model=get_model(),
        max_tokens=1100,
        messages=[{"role": "user", "content": prompt}],
    )
    return _text(msg)


def tailor_cv(job, cv):
    """
    Rework the candidate's existing CV to fit a specific job — reorder, re-emphasize,
    and tighten wording. Never fabricates new experience.
    """
    if not (cv or "").strip():
        raise ValueError("No CV on file to tailor. Add your CV in Account first.")

    job_block = (
        f"Job title: {job.get('title','')}\n"
        f"Company: {job.get('company','')}\n"
        f"Summary: {job.get('summary','')}\n"
        f"Full description:\n{(job.get('description') or '')[:6000]}\n"
    )

    prompt = (
        "Tailor the candidate's CV below to the target job. Rules:\n"
        "- Keep it truthful: do NOT add experience, employers, dates, certifications, or "
        "skills that aren't already in the CV. You may rephrase, reorder, and re-emphasize.\n"
        "- Lead with and highlight the experience and skills most relevant to this role.\n"
        "- Tighten the summary/objective and bullet wording to mirror the job's language "
        "where it's genuinely accurate.\n"
        "- Preserve the candidate's real sections and facts. Keep it ATS-friendly plain text "
        "(no markdown tables or graphics).\n\n"
        "=== TARGET JOB ===\n" + job_block
        + "\n=== CURRENT CV ===\n" + cv[:12000]
        + "\n\nReturn only the tailored CV as plain text."
    )

    msg = _client().messages.create(
        model=get_model(),
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )
    return _text(msg)
