"""Gemini synthesis client (§C, §E.1). Synthesis only — never originates
numbers. Retries with exponential backoff + jitter on 429/503/timeout."""

from app.models.reports import AINarrative

MAX_RETRIES = 3
TIMEOUT_S = 30


async def synthesize(prompt: str) -> AINarrative:
    """Send the assembled prompt, parse the JSON response against AINarrative.
    On malformed output, retry with a stricter instruction. TODO: implement the
    google-genai call + backoff."""
    raise NotImplementedError
