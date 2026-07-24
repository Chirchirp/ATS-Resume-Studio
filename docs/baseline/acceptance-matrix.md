# Cloudflare Parity Acceptance Matrix

Every required item must pass before the custom domain is cut over.

| ID | Area | Required check | Pass condition |
|---|---|---|---|
| B-001 | Source | Baseline unit/integration suite | All tests pass |
| B-002 | Visual | Analyze desktop | Matches reference layout, theme and sidebar |
| B-003 | Visual | All Streamlit tabs | Navigation and empty states match references |
| B-004 | Visual | Streamlit mobile | Sidebar opens/closes and tab strip remains usable |
| B-005 | Visual | Platform desktop/mobile | Sign-in and workspace match references |
| B-006 | Input | Resume paste | Structured profile updates after commit/blur |
| B-007 | Input | PDF upload | Text extracts and profile is populated |
| B-008 | ATS | Baseline fixture | Score 52, High confidence, 10 matched terms |
| B-009 | Quality | Baseline fixture | Score 95, grade Excellent, one medium issue |
| B-010 | ATS | Explanation | Dimensions, provenance and gaps are visible |
| B-011 | Evidence | Ledger and matrix | Resume evidence remains the source of truth |
| B-012 | Truth | Unsupported claims | Unsupported claims are flagged and gated |
| B-013 | AI | Groq | Configured model produces valid grounded output |
| B-014 | AI | Gemini | Configured model produces valid grounded output |
| B-015 | AI | OpenRouter | Configured model produces valid grounded output |
| B-016 | AI | Custom model | Custom model ID and reasoning settings are honored |
| B-017 | AI | Fallback | Retryable primary failure reaches configured fallback |
| B-018 | Tokens | Usage controls | Token counters, cache savings and budget limits update |
| B-019 | Export | DOCX | Download opens and round-trip parseability passes |
| B-020 | Export | Markdown | Resume/cover-letter download content is complete |
| B-021 | Sessions | Isolation | Two browsers do not share resume, keys or results |
| B-022 | WebSocket | Continuity | Long session and reconnect retain expected state |
| B-023 | Auth | Registration/login | Account creation, login, expiry and sign-out work |
| B-024 | Storage | Restart survival | Users, applications, versions and jobs survive replacement |
| B-025 | Ownership | Isolation | One account cannot read another account's records |
| B-026 | Jobs | Recovery | Queued/running work reaches a valid terminal state after restart |
| B-027 | Privacy | Export | Export returns only the authenticated account's data |
| B-028 | Privacy | Retention | Configured completed-job retention is enforced |
| B-029 | Privacy | Deletion | Password-confirmed deletion removes owned records |
| B-030 | Routing | Streamlit | `/` and `/_stcore/*` route without caching |
| B-031 | Routing | Platform | `/studio`, `/assets/*`, `/v1/*`, `/health` route correctly |
| B-032 | Security | Secrets | No provider, auth or encryption key is in image/source/logs |
| B-033 | Operations | Health | Health checks reflect actual process readiness |
| B-034 | Operations | Rollback | Previous deployment can be restored without data loss |
| B-035 | Domain | TLS/DNS | `resume.pharaohchirchir.com` resolves with valid HTTPS |

## Visual comparison tolerance

- No missing controls, labels, tabs, sections or navigation items.
- No white-on-white menu fields or unreadable contrast.
- No clipped primary actions at the desktop reference viewport.
- Mobile horizontal tab scrolling may remain as currently captured.
- Font rasterization and browser-native control rendering may differ slightly.
- Layout shifts, hidden fields, changed colors, or altered component ordering fail
  the parity gate.

## AI comparison rules

Exact prose is not a stable assertion for remotely hosted models. An AI test
passes only when:

1. the request uses the selected provider, model and reasoning setting;
2. resume evidence and job requirements are present in the request;
3. output satisfies the task's required sections;
4. the self-review/validation stage completes;
5. unsupported metrics, credentials, employers and dates are not introduced;
6. token and provider telemetry is recorded;
7. provider errors are clear and do not erase the user's inputs.
