# Product surfaces

## Decision

The FastAPI-served progressive web app at `/app/` is the official
**POSSESSION LAB** product. It owns the public navigation, responsive design,
phone installation experience, offline shell, accessibility standard, and
user-facing feature roadmap. The JSON API is its backend contract.

The Streamlit application is an internal analytics console. It remains useful
for rapid research, model diagnostics, data inspection, and validating new
analysis functions before they become supported product behavior. It is not a
second public client and does not define release completeness.

## Development policy

- New public features are designed and shipped in the PWA first.
- Basketball calculations belong in `src/nba_insights/analysis` or `ml`, not
  in either UI, so the API and internal tools can reuse them.
- The PWA consumes documented API responses; it must not duplicate model or
  analysis calculations in JavaScript.
- Streamlit may expose experimental controls that never become public product
  features. Public PWA features do not require a Streamlit equivalent.
- Correctness, data-access, and security fixes should be shared below the UI
  layer whenever possible. Streamlit-only presentation work is limited to
  keeping active internal workflows usable.

## Streamlit transition and retirement

Streamlit stays supported as an internal console while it provides a faster
workflow for model investigation or cached-data diagnosis. Its feature list is
an inventory, not a parity contract. A Streamlit surface can be retired when
its internal workflow is available through analysis scripts, notebooks, API
diagnostics, or the PWA and no active research task depends on it.

The transition is complete when:

1. deployment documentation and containers start FastAPI/PWA by default;
2. browser tests cover the public PWA workflows;
3. public API responses have stable, typed contracts; and
4. Streamlit is excluded from public release and feature-parity gates.

