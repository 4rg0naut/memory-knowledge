"""providers: the one seam text -> claim candidates (M3).

Seam contract: provider.extract(raw_text, kind=..., ctx=...) ->
(list_of_candidate_dicts, warnings). Every candidate carries subject,
predicate, value, confidence, source_quote; the quote gate is applied
once, here, so no provider — including manual — bypasses it.

Selection is config only: MEM_PROVIDER env (default "ollama"), or
--provider on the CLI. Providers:

  ollama            local qwen2.5:7b-instruct (OLLAMA_URL, MEM_MODEL)
  openai-compatible any /chat/completions endpoint
                    (MEM_OPENAI_BASE_URL, MEM_OPENAI_MODEL,
                     MEM_OPENAI_API_KEY)
  manual            no model; caller supplies candidates JSON
                    (--claims <file|->); still quote-gated

--dump-prompt prints the exact prompt instead of calling a model.
"""

import json
import os
import urllib.request

from . import schema, sources

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b-instruct"

SYSTEM_WEB = (
    "You are a structured extraction engine. Given the text and schema, "
    "return ONLY valid JSON. No explanation. No markdown. "
    "RULES: value must come from the text. source_quote must be a VERBATIM "
    "copy-paste of one or more consecutive sentences from the text, "
    "character for character, including punctuation. Never paraphrase "
    "the quote. If you cannot quote it verbatim, omit the claim."
)

SYSTEM_SESSION = (
    SYSTEM_WEB + " The text is an agent session transcript. Extract ONLY "
    "incident-type facts, each quoted from the turn that states it: "
    "(1) incident: a tool-call failure, with root cause and the fix that "
    "resolved it; (2) decision: a choice made, with its rationale; "
    "(3) gotcha: a trap or environment quirk worth remembering. "
    "Use predicates incident | decision | gotcha. Ignore greetings, "
    "status chatter, and restatements."
)

SCHEMA_HINT = """Schema:
{
  "claims": [
    {
      "subject": "string - entity this is about",
      "predicate": "one of: %s",
      "value": "string - the asserted fact, short",
      "confidence": 0.0,
      "source_quote": "exact sentence from text supporting this claim"
    }
  ]
}"""


def build_prompt(raw_text, kind="web", predicates=None):
    predicates = predicates or schema.PREDICATES
    return raw_text + "\n\n" + SCHEMA_HINT % ", ".join(predicates)


def system_for(kind):
    return SYSTEM_SESSION if kind == "session" else SYSTEM_WEB


def parse_json_first(content):
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        obj, _end = json.JSONDecoder().raw_decode(content.lstrip())
        return obj


def filter_candidates(candidates, raw_text):
    """Shared post-gate: verbatim-quote enforcement + normalization.
    Returns (claims, warnings)."""
    claims, warnings = [], []
    for c in candidates:
        try:
            quote = c["source_quote"]
            if quote not in raw_text:
                warnings.append("dropped (quote not in source): %r"
                                % c.get("value", "")[:60])
                continue
            pred = c.get("predicate", "other")
            if pred not in schema.PREDICATES:
                pred = "other"
            conf = float(c.get("confidence", 0.5))
            conf = min(1.0, max(0.0, conf))
            claims.append({
                "subject": str(c["subject"]).strip(),
                "pred": pred,
                "value": str(c["value"]).strip(),
                "confidence": conf,
                "source_quote": quote,
            })
        except Exception as e:  # noqa: BLE001
            warnings.append("dropped malformed candidate: %s" % e)
    return claims, warnings


class OllamaProvider:
    name = "ollama"

    def call(self, url, model, system, prompt, timeout=120):
        body = json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 8192},
        }).encode("utf-8")
        req = urllib.request.Request(url.rstrip("/") + "/api/chat",
                                     data=body,
                                     headers={"Content-Type":
                                              "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["message"]["content"]

    def extract(self, raw_text, kind="web", url=None, model=None,
                predicates=None, retries=1, timeout=120, opener=None,
                ctx=None):
        url = url or os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL)
        model = model or os.environ.get("MEM_MODEL", DEFAULT_MODEL)
        predicates = predicates or schema.PREDICATES
        prompt = build_prompt(raw_text, kind, predicates)
        call = opener or self.call
        candidates = None
        warnings = []
        for attempt in range(retries + 1):
            try:
                content = call(url, model, system_for(kind), prompt,
                               timeout)
                parsed = parse_json_first(content)
                candidates = parsed["claims"]
                if not isinstance(candidates, list):
                    raise ValueError("claims is not a list")
                break
            except Exception as e:  # noqa: BLE001
                if attempt == retries:
                    return [], warnings + ["extraction skipped: %s" % e]
                warnings.append("parse failure, retrying: %s" % e)
        return filter_candidates(candidates, raw_text)


class OpenAICompatProvider:
    name = "openai-compatible"

    def call(self, base_url, model, system, prompt, timeout=120):
        key = os.environ.get("MEM_OPENAI_API_KEY", "")
        body = json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = urllib.request.Request(
            base_url.rstrip("/") + "/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer %s" % key})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]

    def extract(self, raw_text, kind="web", url=None, model=None,
                predicates=None, retries=1, timeout=120, opener=None,
                ctx=None):
        base = url or os.environ.get("MEM_OPENAI_BASE_URL",
                                     "http://127.0.0.1:8000/v1")
        model = model or os.environ.get("MEM_OPENAI_MODEL", "gpt-4o-mini")
        predicates = predicates or schema.PREDICATES
        prompt = build_prompt(raw_text, kind, predicates)
        call = opener or self.call
        try:
            content = call(base, model, system_for(kind), prompt, timeout)
            candidates = parse_json_first(content)["claims"]
        except Exception as e:  # noqa: BLE001
            return [], ["extraction skipped: %s" % e]
        return filter_candidates(candidates, raw_text)


class ManualProvider:
    """No model. Candidates come from ctx['candidates'] (loaded by the
    caller from --claims); still quote-gated."""
    name = "manual"

    def extract(self, raw_text, kind="web", url=None, model=None,
                predicates=None, retries=1, timeout=120, opener=None,
                ctx=None):
        candidates = (ctx or {}).get("candidates")
        if candidates is None:
            return [], ["manual provider: no candidates supplied "
                        "(--claims <file|->)"]
        return filter_candidates(candidates, raw_text)


PROVIDERS = {"ollama": OllamaProvider,
             "openai-compatible": OpenAICompatProvider,
             "openai_compat": OpenAICompatProvider,
             "manual": ManualProvider}


def get_provider(name=None):
    name = name or os.environ.get("MEM_PROVIDER", "ollama")
    factory = PROVIDERS.get(name)
    if factory is None:
        raise ValueError("unknown provider %r (known: %s)"
                         % (name, ", ".join(sorted(set(PROVIDERS)))))
    return factory()


def load_claims_arg(path_or_dash, stdin=None):
    import sys
    text = (sys.stdin if stdin is None else stdin).read() \
        if path_or_dash == "-" else open(path_or_dash,
                                         encoding="utf-8").read()
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("claims", [])
    if not isinstance(data, list):
        raise ValueError("claims JSON must be a list or {claims: [...]}")
    return data
