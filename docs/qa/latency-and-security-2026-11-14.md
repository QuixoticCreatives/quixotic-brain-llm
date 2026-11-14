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
| F2 | P3 | No `Content-Security-Policy` header. Answers render as plain text (no `dangerouslySetInnerHTML` except a static icon map), so this is defence in depth. | Open |
| — | ok | HSTS, nosniff, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy present; login throttled per account; parameterised SQL (dynamic column names come from fixed lists); internal services not exposed. | Checked |

Limit of this check: code review plus read-only production requests. No attack traffic was sent to production. Active
tests (authorization bypass, injection, upload abuse, prompt injection) run only against the local QA copy (`scripts/qa_up.py`).
