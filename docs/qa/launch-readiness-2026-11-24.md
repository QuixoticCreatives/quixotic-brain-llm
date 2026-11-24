# Launch readiness check — 2026-11-24

Owner request: "Check this whole system ... more secure ... no bug or any flow mistakes ... easy for new users."
Method: read-only production checks, three independent code reviews (security, bugs, new-user experience), fixes with a
failing test first, then unit, real-PostgreSQL integration, build and browser runs on the local QA copy. No attack or load
traffic was sent to production, and nothing below is deployed yet.

## 1. Must be done by the owner before employees start (blockers)
| # | Item | Why |
|---|---|---|
| B1 | **Replace the expired OpenAI API key** (production and local `.env`). | Production answers and translations fail now: the provider returns "Your API key has expired". |
| B2 | **Upload and publish the company documents.** | Production has 0 published knowledge documents, so company questions cannot be answered from approved knowledge. |
| B3 | Deactivate or demote `qa_visual_admin` on production; give `admin` (email `portal-1@portal.invalid`) a real email and two-step sign-in, or deactivate it. | Test/placeholder admin accounts on a live system. |
| B4 | Deploy this release (it contains the Translate blank-page fix, live on production since 14 Nov). | Translate mode in chat shows a blank page on production today. |
| B5 | Decide self-approval: may a reviewer approve their own proposal? (PRD §7 "where policy requires separation"; open in `PRD_GAPS.md`). | Today one publisher can propose and approve alone. |

## 2. Fixed in this release (each with a test)
| Area | Problem found | Fix | Evidence |
|---|---|---|---|
| Chat | Translate mode crashed to a blank page (14 Nov change) | Fixed; plus an error screen with Reload for any future screen error | `flows.spec.ts` Translate: page now renders (answer itself blocked by B1) |
| Security F1 (P1) | A publishing Knowledge Admin could read, approve and copy changes to `restricted` documents | Level check on list, view, decide and propose | `tests/test_proposal_levels.py` (RED then GREEN) |
| Security F2 (P2) | 👍/👎 report showed answer text and titles from documents above the viewer's level | Filtered in SQL | integration `test_rating_report_leaves_out_...` on real PostgreSQL |
| Approvals | An upload could be approved before its text was read | Needs the indexed text | existing approval tests still pass |
| Missing info | Report stayed "in progress" for ever after its answer was withdrawn/rejected | Back to open | `test_withdrawing_the_answer_...` (RED then GREEN) |
| Missing info | Different Urdu questions were merged into one report | Urdu letters kept | `test_gap_key_keeps_urdu_words...` (RED reproduced) |
| Worker | One unreadable document stopped a full re-index | Continues, reports failures | `test_reindex_continues_past_a_bad_version...` |
| Worker | Two jobs from October show "running"/"queued" for ever on System Health | Jobs with no progress for 24 h are failed at worker start (this closes those two on deploy) | integration `test_abandoned_jobs_...` |
| Answers | An empty model reply was shown as an answer | PRD not-found text | `test_an_empty_model_reply...` (RED then GREEN) |
| Answers | A hanging model could hold a request 10 minutes | 90 s limit, 1 retry | `test_model_clients_have_a_time_limit` |
| Admin | System page returned 500 before the first publish | Handled | `test_vault_head_of_a_missing_folder...` (RED then GREEN) |
| New users | Reset link dead end; password rule hidden; department list failure silent; no "Signing in…"; 502/503 showed "Something went wrong (502)" | Fixed (see `PRD_GAPS.md` "Launch review") | browser check on a 375 px phone screen |
| Access | Grey text 3.2:1 contrast; chat menu hidden on touch; menu not closable with Esc; long links overflowed; composer overflowed on phones | Fixed | build + browser check |

## 3. Evidence (what actually ran, 2026-11-24)
- Unit: `pytest -m "not integration"`: **212 passed**, 59 skipped, 2 xfailed.
- Integration on real PostgreSQL + pgvector (signup, account, postgres, learning, translate, knowledge, chats): **37 passed**.
- Web: `tsc --noEmit` clean, `vite build` clean.
- Browser (Playwright `flows.spec.ts`, local QA copy): admin pages **passed**; employee chat and Translate **BLOCKED** by B1
  (server log: `expired_secret_key`). The reset-link pages were checked by hand at 375 px.
- NOT VERIFIED: answer quality after these changes (needs B1); integration suites `test_models`, `test_e2e`, `test_answers`,
  `test_contributors`, `test_client_*` were not run in this pass.

## 4. Known, not fixed (follow-ups, lower risk)
- F3 (P2): with Web Search on, company passages and web results go to the model in the same call (prompt-injection surface).
- F5 (P2): an API key can act as any `user_id` (no API keys exist on production today; restrict before creating one).
- F6 (P3): Obsidian zip import has no size limits. F7 (P3): unclassified documents readable by reviewers. F8 (P3): `/v1/search` has no per-user limit (no paid model call).
- Restoring an old version does not restore its title/departments/level; proposal list capped at 200, documents list at 500.
- Auth follow-ups from 14 Nov: token rotation after the two-step code, shared limits across processes, breached-password check.
- Answer speed: p95 12.5 s on production vs PRD §2 target 8 s (options in `latency-and-security-2026-11-14.md` §3).
