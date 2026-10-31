# Code standards

1. Keep it simple, do not overcomplicate.
2. Comments only when necessary.
3. Be concise: a short README and no emojis.
4. IMPORTANT: avoid overly defensive code. Handle exceptions only when necessary.
5. Use uv: ALWAYS `uv run`, NEVER `python3`.
6. TypeScript: strict mode, never `any`.
7. Keep dependencies one-way. Shared modules must not import entry points; no circular imports. Cross-module imports are fine when they follow responsibility boundaries.
8. Separate agent configuration, HTTP transport, tools and orchestration. Agents access business data only through HTTP; backend operations enforce workflow and payment rules.
9. Separate backend execution from stored run state. Share transaction helpers in `backend/records.py`; keep locks and writes in the same transaction. Separate dashboard HTTP transport from React resource/polling hooks.
10. Configure service origins once per runtime. Agents and CLI share `agent/config.py`; the dashboard uses relative `/api` paths and Vite's configurable proxy. Keep stable endpoint paths beside their operations; avoid a second route registry.
