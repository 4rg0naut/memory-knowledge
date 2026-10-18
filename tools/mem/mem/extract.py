"""Structured extraction — thin facade over the provider seam (M3).

Kept for import compatibility (`from mem.extract import extract`);
provider selection is config via MEM_PROVIDER / --provider. See
providers.py for ollama / openai-compatible / manual.
"""

from . import providers


def extract(raw_text, *, url=None, model=None, predicates=None,
            retries=1, timeout=120, opener=None, kind="web",
            provider=None, ctx=None):
    """Returns (claims, warnings) from the configured provider; the
    quote gate lives in providers.filter_candidates."""
    p = providers.get_provider(provider)
    return p.extract(raw_text, kind=kind, url=url, model=model,
                     predicates=predicates, retries=retries,
                     timeout=timeout, opener=opener, ctx=ctx)
