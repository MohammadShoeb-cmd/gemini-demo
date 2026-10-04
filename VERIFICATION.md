# Verification record — 4 October 2026

Environment: Windows PowerShell, Python 3.14.7, google-genai 2.28.0.

## Offline checks

`python -m unittest discover -s tests -v`: all 12 tests passed.
Tests use a fake Gemini client and temporary databases. They include typed CLI
confirmation, successful approval, duplicate protection across two connections,
denial, expiry at approval, validation, bounded execution, continuation, and
interruption after preparation. `git diff --check` passed.

## Live Gemini checks

Model: `gemini-3.8-flash`, via `client.interactions.create()`.
Local verification database: `data/live-check.db` (ignored by Git).

1. Lookup and eligibility for ORD-1001: Gemini selected `lookup_order` and
   `check_refund_eligibility`; final answer correctly reported INR 2,499 and
   eligibility. No request was prepared by this lookup.
2. Same-session follow-up asking to refund "that order": Gemini selected
   `prepare_refund_request`; SQLite recorded one pending request for ORD-1001.
   Final answer stated that separate CLI approval was required.
3. Expired ORD-1002: Gemini looked up the order and checked eligibility. It then
   attempted preparation, which Python rejected with "Outside the 30-day window".
   A later Gemini request failed; this was a partial live check, without a final
   answer. No request or refund for ORD-1002 was written.

The initial lookup reached both tools but failed when Windows encoded a rupee
symbol in the final answer. After setting CLI stdout to UTF-8, the repeated
lookup completed with exit code 0. SDK retries were reduced for subsequent checks.
Inspection of the pinned SDK showed its Interactions adapter maps `attempts=1`
to one transport retry, despite the general option's inclusive-attempt wording.

At inspection after preparation, the live database contained one pending request
and zero refunds. No live approval was performed. Approval behavior was verified
offline. These checks do not establish production readiness or guarantee future
model behavior. User verification remains required before GitHub publication.
