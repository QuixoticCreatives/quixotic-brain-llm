# Latency and security check — 2026-11-14

## 1. Production health (read-only checks)
- `/v1/health`: 200, database ok, models ready; home page 0.2 s. Containers: api (healthy, up 8 days), worker, postgres,
  redis, caddy up. Only Caddy publishes ports (80/443); API, Postgres and Redis are internal.
- Answer latency from `query_log`, last 14 days: 7 general answers, **p50 19.5 s, p95 34.6 s** (PRD §2 target: p95 < 8 s).

## 2. Where the time goes (measured)
| Stage | Time | How measured |
|---|---|---|
| Retrieval (embed + vector + rerank) | well under 1 s | `/v1/search` on production |
| Task router (gpt-5-mini, effort low) | 4.3–6.7 s | local, same model and prompt |
| Answer (gpt-5-mini, effort **unset = default**) | median 16.5 s, max 35.8 s | local, 3 task types × 2 runs |
| Answer, effort `low` | median 4.9 s, max 13.4 s | same |
| Answer, effort `minimal` | median 3.7 s, max 4.8 s | same |

The answer model's reasoning effort is the main cost: production does not set `QB_GENERATION_REASONING_EFFORT`, so
gpt-5-mini thinks at its default level on every answer. The router adds a second sequential model call (~5 s).

## 3. Options to answer faster with the company information (ranked by gain / risk)
1. **Set `QB_GENERATION_REASONING_EFFORT=low`** (config only, no code). ~3x faster answers. Quality checked with the
   regression suite before rollout (results below).
2. **Run the router in parallel with retrieval** instead of before it, or skip it for obvious messages (a pasted client
   message, "translate ..."), saving ~5 s per question. Small code change.
3. **Stream the answer** to the browser (server-sent events): the first words appear in ~1–2 s even when the full answer
   takes longer. Medium change (API + chat UI); the format checks and guards then run on the finished text.
4. **Prompt caching**: keep the long fixed system prompt first and identical across calls so OpenAI's automatic prompt
   cache applies (lower time-to-first-token and cost on repeated prefixes). Check `usage.prompt_tokens_details.cached_tokens`.
5. **Cache repeated knowledge answers** (same normalized question + same permitted documents + same published version),
   invalidated on publish. Only for knowledge questions, never for client replies. Medium change; must keep permission
   filtering (PRD §8).
6. **Avoid the second generation**: the format rewrite and the no-invented-price retry each add a full answer call when
   they fire. Tighter first-pass instructions reduce how often they fire.

**Effort `low` checked with the regression suite** (local QA copy, 27 cases): 25/27 pass in every repeat (2 repeats)
versus 22/27 for the earlier default-effort local run (3 repeats); end-to-end median 14.7 s versus 19.0 s, p95 31.1 s versus
40.9 s on this machine (CPU-only local models; production is faster). The two misses passed 1 of 2 repeats (game jargon
in a "simple English" answer; a console-skin idea without vent clearance). No quality loss measured.

**Deployed to production 2026-11-14 12:12 UTC** (effort `low` + F1 only; Client Brain S1/S2 not deployed). Production
`query_log` afterwards, 25 answers from one quality-suite pass: **p50 7.6 s, p95 12.5 s, max 15.7 s** (before: p50 19.5 s,
p95 34.6 s, max 37.0 s, 7 answers over 14 days). Quality suite on production: 25/27 (misses: AI1 138 words vs 130 limit;
AI4 game jargon in a "simple English" answer). Still above the PRD §2 p95 < 8 s target: options 2–3 are next.

Not recommended now: a bigger or self-hosted model (cost, ops), fine-tuning (PRD §15), dropping the reranker (retrieval is
already fast).

## 4. Security findings
| ID | Priority | Finding | Status |
|---|---|---|---|
| F1 | P1 | Signed-in users had no limit on paid model calls (`/v1/ask`, `/v1/translate`, `/v1/images`): one account or a stolen session could run up cost and slow the service for everyone. API keys already had a per-key limit. | Fixed locally: shared per-user budget, default 20 / minute (`QB_USER_AI_REQUESTS_PER_MINUTE`), 429 + Retry-After. Test `test_signed_in_users_have_a_per_user_ai_request_limit`. Deployed 2026-11-14 (limit 20 confirmed in the running api). |
| F2 | P3 | No `Content-Security-Policy` header. Answers render as plain text (no `dangerouslySetInnerHTML` except a static icon map), so this is defence in depth. | Fixed locally: CSP on every response (`backend/main.py`); no violations in the browser. Not deployed. |
| — | ok | HSTS, nosniff, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy present; login throttled per account; parameterised SQL (dynamic column names come from fixed lists); internal services not exposed. | Checked |

Limit of this check: code review plus read-only production requests. No attack traffic was sent to production. Active
tests (authorization bypass, injection, upload abuse, prompt injection) run only against the local QA copy (`scripts/qa_up.py`).

## 5. Auth checklist (20 points) and image-creation removal — 2026-11-14, local only (not deployed)
Code review of the 20-point auth checklist (OTP, tokens, reset, admin). Already OK before this change: tokens are hashed and
never returned; reset links are single-use, 256-bit and expire; login gives the same 401 and does the same hashing work for unknown
users; the session lives in an HttpOnly, SameSite cookie with CSRF double-submit (no token in localStorage); logout, suspension and
password reset revoke sessions; roles come from the database only; every admin route is checked on the server; no default admin
account; MFA is required for admin roles. Not applicable: email change (no endpoint), OAuth (none).

| # | Gap found | Fix (test) |
|---|---|---|
| 5 | Failures counted per account only, so one address could spray many accounts | Also 50 per 15 min per address (`test_login_failures_are_limited_per_client_address_across_accounts`) |
| 1 | A two-step code could be reused within its ~90 s window | Accepted once (`test_mfa_verify_refuses_a_replayed_code`, integration `test_admin_mfa_setup_and_verify`) |
| 16 | Turning two-step sign-in on left other sessions open | Others signed out (`test_enabling_mfa_revokes_the_users_other_sessions`) |
| — | `GET /mfa/setup` changed state without the CSRF check | POST only (`test_mfa_setup_is_post_only`) |
| 4 | Reset email sent inside the request: timing showed which accounts exist | Sent after the response (`test_password_reset_mail_is_sent_in_the_background`) |
| 7, 2, 20 | `change-me` placeholder keys passed validation; console mail or admin MFA off possible on https | Refused at start-up (`test_placeholder_secrets_are_refused`, `test_https_deployment_requires_real_mail_and_admin_mfa`); production checked first: no placeholders, smtp, MFA on |
| — | Throttle memory grew with every name tried | Bounded (`test_checking_unknown_identifiers_does_not_grow_the_throttle`) |
| F2 | No CSP | `test_every_response_has_a_content_security_policy` |

Open (follow-ups): token rotation after the two-step code, shared limits across processes (Redis), breached-password check,
sign-up still reports a taken name (30 tries per address per hour).

Image creation removed (owner request): `/v1/images`, Create image mode, art director and the Attach image button are gone; a
picture request gets a fixed "not available" reply with no model call (`test_image_requests_get_a_fixed_reply_and_no_model_call`,
`test_a_create_image_line_from_the_model_is_never_passed_on`, `test_image_creation_endpoint_is_removed`). Pasted screenshots are
still read and validated (`test_pasted_images_are_still_validated_after_image_creation_was_removed`). Browser check on the local QA
copy: no image icon, modes Answer / Search only / Translate, "generate an image of ..." returns the fixed reply, no CSP errors.

Evidence: `pytest -m "not integration"` 201 passed, 57 skipped, 2 xfailed; integration (real PostgreSQL) signup, account, postgres,
client API, client memory, learning, translate: 47 passed; `tsc --noEmit` and `vite build` clean. Model-loading integration suites
(models, e2e, answers, chats, contributors, knowledge) NOT VERIFIED locally (memory pressure on this machine).
