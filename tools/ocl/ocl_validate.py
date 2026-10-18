"""OpenClaims v0.1 event validation: structural checks mirroring the
reference validator semantics, plus optional JSON-Schema validation
against the vendored official schemas (jsonschema library, when present).
Digest verification is enforced for every event that carries one.
"""

import json
import os
import re

from jcs import event_digest

EVENT_TYPES = {"claim.emitted", "claim.verified", "claim.disputed", "claim.retracted"}
CLAIM_TYPES = {"factual", "calculation", "inference", "recommendation", "prediction"}
SUPPORT_TYPES = {
    "supports_directly",
    "supports_partially",
    "computed_from",
    "contradicts",
    "context_only",
    "provenance_only",
}
VERIFICATION_RESULTS = {"supported", "contradicted", "inconclusive"}
VERIFICATION_METHODS = {
    "human_review",
    "model_check",
    "source_attestation",
    "consensus",
    "formal_proof",
}
CLAIM_STATUSES = {"active", "disputed", "retracted"}
SELECTOR_TYPES = {
    "text_span",
    "page_span",
    "json_pointer",
    "table_cell",
    "uri_fragment",
    "byte_range",
}
AGENT_TYPES = {"human", "organization", "service", "model", "pipeline"}

_DATE_TIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)

_SCHEMA_DIR = os.environ.get(
    "OCL_SCHEMA_DIR",
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "vendor",
        "openclaims",
        "schemas",
        "openclaims",
        "0.1",
    ),
)


class Errors:
    def __init__(self):
        self.items = []

    def add(self, path, message):
        self.items.append({"path": path or "/", "message": message})

    def extend(self, other):
        self.items.extend(other)


def _required(obj, path, keys, errors):
    for key in keys:
        value = obj.get(key) if isinstance(obj, dict) else None
        if value is None or value == "":
            errors.add("%s/%s" % (path, key), "required field missing")


def _digest(obj, path, errors):
    if not isinstance(obj, dict):
        return
    for key, const in (("algorithm", "sha256"), ("encoding", "base64url")):
        if obj.get(key) != const:
            errors.add("%s/%s" % (path, key), "must equal %r" % const)
    if not obj.get("value"):
        errors.add("%s/value" % path, "required field missing")


def _agent(obj, path, errors):
    if not isinstance(obj, dict):
        errors.add(path, "agent object required")
        return
    _required(obj, path, ["agent_id", "agent_type"], errors)
    if obj.get("agent_type") not in AGENT_TYPES:
        errors.add("%s/agent_type" % path, "unknown agent_type")


def _facet(obj, path, errors):
    if not isinstance(obj, dict):
        errors.add(path, "facet object required")
        return
    _required(obj, path, ["_producer", "_schemaURL"], errors)


def _facets(obj, path, errors):
    for key, facet in (obj or {}).items():
        _facet(facet, "%s/%s" % (path, key), errors)


def _selector(obj, path, errors):
    if not isinstance(obj, dict):
        errors.add(path, "selector object required")
        return
    stype = obj.get("type")
    if stype not in SELECTOR_TYPES:
        errors.add("%s/type" % path, "unknown selector type")
        return
    if stype in ("text_span", "byte_range"):
        _required(obj, path, ["start", "end"], errors)
    elif stype == "page_span":
        _required(obj, path, ["page", "start", "end"], errors)
    elif stype == "json_pointer":
        _required(obj, path, ["path"], errors)
    elif stype == "table_cell":
        _required(obj, path, ["row", "column"], errors)
    elif stype == "uri_fragment":
        _required(obj, path, ["fragment"], errors)


def _claim(obj, path, errors):
    if not isinstance(obj, dict):
        errors.add(path, "claim object required")
        return
    _required(obj, path, ["claim_id", "text", "claim_type", "asserted_at"], errors)
    if obj.get("claim_type") not in CLAIM_TYPES:
        errors.add("%s/claim_type" % path, "unknown claim type")
    if obj.get("asserted_at") and not _DATE_TIME_RE.match(str(obj["asserted_at"])):
        errors.add("%s/asserted_at" % path, "not date-time")
    for rel in obj.get("relations", []) or []:
        _required(rel, "%s/relations" % path, ["relation_type", "claim_ref"], errors)
        if rel.get("relation_type") not in (
            "derived_from",
            "summarizes",
            "refines",
            "contradicts",
        ):
            errors.add(
                "%s/relations/relation_type" % path, "unknown relation_type"
            )
    _facets(obj.get("facets"), "%s/facets" % path, errors)


def _source(obj, path, errors):
    if not isinstance(obj, dict):
        errors.add(path, "source object required")
        return
    _required(obj, path, ["source_id"], errors)
    if obj.get("digest"):
        _digest(obj["digest"], "%s/digest" % path, errors)
    _facets(obj.get("facets"), "%s/facets" % path, errors)


def _evidence(obj, path, errors):
    if not isinstance(obj, dict):
        errors.add(path, "evidence object required")
        return
    _required(obj, path, ["evidence_id", "source_ref", "selector", "support_type"], errors)
    if obj.get("support_type") not in SUPPORT_TYPES:
        errors.add("%s/support_type" % path, "unknown support_type")
    _selector(obj.get("selector"), "%s/selector" % path, errors)
    if obj.get("content_digest"):
        _digest(obj["content_digest"], "%s/content_digest" % path, errors)
    _facets(obj.get("facets"), "%s/facets" % path, errors)


def _tool_run(obj, path, errors):
    if not isinstance(obj, dict):
        errors.add(path, "tool_run object required")
        return
    _required(obj, path, ["tool_run_id", "tool_type", "tool"], errors)
    if isinstance(obj.get("tool"), dict) and not obj["tool"].get("name"):
        errors.add("%s/tool/name" % path, "required field missing")
    _facets(obj.get("facets"), "%s/facets" % path, errors)


def _verification(obj, path, errors):
    if not isinstance(obj, dict):
        errors.add(path, "verification object required")
        return
    _required(
        obj,
        path,
        [
            "verification_id",
            "verification_result",
            "verification_method",
            "claim_status",
            "validator",
            "verified_at",
        ],
        errors,
    )
    if obj.get("verification_result") not in VERIFICATION_RESULTS:
        errors.add("%s/verification_result" % path, "unknown verification_result")
    if obj.get("verification_method") not in VERIFICATION_METHODS:
        errors.add("%s/verification_method" % path, "unknown verification_method")
    if obj.get("claim_status") not in CLAIM_STATUSES:
        errors.add("%s/claim_status" % path, "unknown claim_status")
    _agent(obj.get("validator"), "%s/validator" % path, errors)
    if obj.get("verified_at") and not _DATE_TIME_RE.match(str(obj["verified_at"])):
        errors.add("%s/verified_at" % path, "not date-time")
    _facets(obj.get("facets"), "%s/facets" % path, errors)


def validate_event(event, verify_digest=True):
    errors = Errors()
    if not isinstance(event, dict):
        errors.add("/", "event must be an object")
        return {"valid": False, "errors": errors.items}
    _required(
        event,
        "",
        [
            "event_id",
            "event_type",
            "event_time",
            "spec_version",
            "schema_url",
            "producer",
            "digest",
        ],
        errors,
    )
    if event.get("event_type") not in EVENT_TYPES:
        errors.add("/event_type", "unknown event type")
    if not event.get("claim") and not event.get("claim_ref"):
        errors.add("/", "event requires claim or claim_ref")
    if event.get("claim"):
        _claim(event["claim"], "/claim", errors)
    _agent(event.get("producer"), "/producer", errors)
    for i, source in enumerate(event.get("sources") or []):
        _source(source, "/sources/%d" % i, errors)
    for i, evidence in enumerate(event.get("evidence") or []):
        _evidence(evidence, "/evidence/%d" % i, errors)
    for i, evidence in enumerate(event.get("contradicting_evidence") or []):
        _evidence(evidence, "/contradicting_evidence/%d" % i, errors)
    for i, run in enumerate(event.get("tool_runs") or []):
        _tool_run(run, "/tool_runs/%d" % i, errors)
    if event.get("verification"):
        _verification(event["verification"], "/verification", errors)
    etype = event.get("event_type")
    if etype == "claim.emitted" and not event.get("claim"):
        errors.add("/claim", "claim.emitted requires claim")
    if etype == "claim.verified":
        _required(event, "", ["claim_ref", "verification"], errors)
    if etype == "claim.disputed":
        _required(event, "", ["claim_ref"], errors)
        if not event.get("dispute_rationale") and not event.get(
            "contradicting_evidence"
        ):
            errors.add(
                "/",
                "claim.disputed requires dispute_rationale or contradicting_evidence",
            )
    if etype == "claim.retracted":
        _required(event, "", ["claim_ref", "retracted_at"], errors)
    if event.get("digest"):
        _digest(event["digest"], "/digest", errors)
        if verify_digest and event_digest(event) != event["digest"]:
            errors.add("/digest", "event digest mismatch")
    schema_errors = _schema_validate(event)
    if schema_errors:
        errors.extend(schema_errors)
    return {"valid": not errors.items, "errors": errors.items}


def _schema_validate(event):
    try:
        import jsonschema
    except ImportError:
        return None
    try:
        registry = _schema_registry()
        validator = registry["validator"]
        validator.iter_errors  # ensure built
        errs = [
            {"path": "/schema", "message": "JSON Schema: %s" % e.message}
            for e in validator.iter_errors(event)
        ]
        return errs
    except Exception as exc:  # noqa: BLE001 - report as validation error
        return [
            {
                "path": "/schema",
                "message": "JSON Schema: %s" % str(exc).splitlines()[0],
            }
        ]


_REGISTRY_CACHE = {}


def _schema_registry():
    if _REGISTRY_CACHE:
        return _REGISTRY_CACHE
    import jsonschema
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    resources = []
    root = None
    for name in os.listdir(_SCHEMA_DIR):
        if not name.endswith(".schema.json"):
            continue
        with open(os.path.join(_SCHEMA_DIR, name), encoding="utf-8") as handle:
            schema = json.load(handle)
        uri = schema.get("$id")
        resources.append((uri, Resource.from_contents(schema)))
        if name == "ClaimEvent.schema.json":
            root = schema
    if root is None:
        raise RuntimeError("ClaimEvent.schema.json not found in %s" % _SCHEMA_DIR)
    registry = Registry().with_resources(resources)
    Draft202012Validator.check_schema(root)
    validator = Draft202012Validator(root, registry=registry, format_checker=jsonschema.FormatChecker())
    _REGISTRY_CACHE.update({"registry": registry, "manifest_schema": root, "validator": validator})
    return _REGISTRY_CACHE
