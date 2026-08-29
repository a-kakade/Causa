# Security Architecture (API layer)

## Threat model / prototype limitation, stated plainly

This is a prototype with **no real login/authentication system**. The browser can claim to be any role (`ANALYST`/`EXECUTIVE`/`INTERNAL`) via `?requester_role=` or the `X-Causa-Role` header — there is no password, token, or session proving that claim. **What the server does guarantee**: whatever role the client claims, the server — never the client — decides what clearance that role gets and what data it can see, using the exact same `src/tools/policy.py` tables the Step 5 multi-agent engine itself is bound by. A client cannot self-grant a clearance level above what its claimed role maps to; it can only lie about *which* role it is, exactly as today's demo-mode `AppStateContext` role toggle already does client-side with zero backing enforcement. Real authentication (OAuth/SSO, sessions) is explicitly out of scope for this round and is the natural next step before any real deployment.

## User → Auth → RBAC → Clearance → Tool Gateway → Input Validation → Tool → Output Validation → Audit

```
Browser
  │  ?requester_role=ANALYST  (a role NAME, never a clearance)
  ▼
api/dependencies.py::get_requester_role       -- validates against RequesterRole enum, 400s on unknown
  ▼
api/dependencies.py::get_requester_clearance  -- tools.policy.clearance_for_role(role)  [SERVER-SIDE ONLY]
  ▼
route handler                                  -- passes requester_clearance into the engine call
  ▼
src/evidence/access_control.py                -- filter_evidence_objects / filter_graph / clearance_sufficient
src/drivers/engine.py                          -- its own requester_clearance check (Unauthorized/UnsupportedSegmentError)
src/tools/gateway.py (INSIDE an investigation run)  -- the actual Tool Gateway chokepoint, per-tool RBAC + audit
  ▼
api/errors.py                                  -- redacts error messages below INTERNAL clearance
  ▼
Response (evidence/segments/graph already filtered)
```

**Never a second policy.** `causa/api/routes/security.py`'s `/api/security/policy` endpoint *reads* `src/tools/policy.RBAC_CLEARANCE_FOR_ROLE` / `ALLOWED_TOOLS_PER_AGENT` and returns them verbatim — it does not redefine, cache-and-drift, or approximate them. Every evidence/graph/segment-returning route calls the exact same `src/evidence/access_control.py` functions the Step 4/5 engines already use internally.

## Verified live (not just claimed)

`GET /api/evidence` as `EXECUTIVE` returns 383 evidence items; the identical call as `ANALYST` returns 12,216 — the seller/customer-level `INTERNAL` evidence is genuinely absent from the `EXECUTIVE` response, not just hidden in the UI. `GET /api/kpis/revenue/segments?dimension=seller` as `EXECUTIVE` returns HTTP 403 (`UnauthorizedSegmentError`) — the engine itself refuses, the API layer does not "helpfully" downgrade the request.

## Untrusted evidence boundary

`POST /api/security/prompt-injection-demo` calls the real `src/agents/security.py::wrap_untrusted_evidence` — the exact function every review-derived evidence string passes through before it can reach an LLM prompt inside a live investigation. The API layer does not implement its own injection detection; it exercises the real one.

## Numeric guardrail / causal-language guard

Not separately re-implemented at the API layer — these are structural properties of the underlying dataclasses (`agents.models.Hypothesis.__post_init__`, `causal.models.CausalResult.causal_claim_allowed` hardcoded `False` on every non-experimental path, `drivers.models.DriverContribution.causal_claim: bool = False`) that the API only serializes, never edits.

## Redaction / audit / no secrets

- `causa/api/serializers.py::audit_entry_dict` / `telemetry_record_dict` are strict field allowlists over `AuditTraceEntry`/`TelemetryRecord` — never a blind `dataclasses.asdict()` that could forward a future field containing raw LLM I/O.
- `causa/api/errors.py` routes every exception message through `evidence.access_control.redact_error_message`, scrubbing identifier-shaped tokens for any caller below `INTERNAL` clearance.
- `GROQ_API_KEYS` (in `causa/.env`, gitignored) are read only by `src/agents/llm_client.py`; no API route ever echoes them, and `mode=live` investigation creation only reports whether credentials exist (`has_groq_credentials()` boolean), never the key values.

## Defense-in-depth, not "solved"

This is a layered, best-effort posture (server-side clearance derivation + real access-control functions + the pre-existing Tool Gateway/guardrails inside an investigation run + redacted errors) — not a claim that prompt injection or authorization bypass is impossible. Language used throughout this repo's docs and this API is deliberately "defense-in-depth controls," never "prompt injection solved."
