# Web Search / Scan Tool Contract

## Purpose

Source of truth: `backend/tool_registry/tools/*.yml`. This SOP is the operational
summary for routing and recovery.

This SOP separates three different capabilities that must not be conflated:

1. `web_search`: deterministic HTTP search. It does not open or depend on a browser tab.
2. `web_scan`: inspect the currently rendered browser page/tab. It does not search the web.
3. `web_execute_js`: run JavaScript in the current browser tab. It is for navigation or DOM actions, not general search.
4. `browser_agent`: high-cost autonomous browser workflow for multi-step rendered tasks only.

## Default search policy

Use `web_search` first for information retrieval.

Default engine order:

```text
bing -> google -> duckduckgo
```

The order can be overridden with:

```text
GENERIC_AGENT_WEB_SEARCH_ORDER=bing,google,duckduckgo
```

On Windows, HTTP fetch transport prefers:

```text
PowerShell Invoke-WebRequest -> Python requests
```

The transport order can be overridden with:

```text
GENERIC_AGENT_WEB_SEARCH_TRANSPORT=powershell,python
```

Rules:

- Do not use Baidu as a search backend.
- Do not use the current browser tab as a search source unless the user explicitly asks for rendered-page behavior.
- Do not use `web_scan` as a fallback for ordinary search failure.
- Do not use `browser_agent` as a fallback for ordinary search failure.
- If `web_search(engine='github')` times out, retry with general `web_search(engine='bing')` using a GitHub-targeted query such as `site:github.com owner repo topic`, rather than jumping to browser automation.

## Tool selection

### Use `web_search` when

- You need search results, source discovery, official docs, GitHub repositories, papers, or public pages.
- You do not need to interact with a rendered page.
- You only need URLs, titles, snippets, or source candidates.

### Use `web_scan` when

- A browser tab is already open and you need visible page state.
- You need to inspect a page after navigation.
- You need the simplified DOM/text of the current page.

### Use `web_execute_js` when

- You need to navigate the current tab.
- You need to click/fill/read DOM state with precise JavaScript.
- You need to operate inside the current page after `web_scan` has confirmed the state.

### Use `browser_agent` when

- The task requires multi-page interaction, login, uploads/downloads, repeated screenshot-analyze-act loops, or long rendered workflows.
- It is not a simple search or a single page inspection.

## Failure policy

On `web_search` failure:

1. Do not immediately switch to `web_scan`, `web_execute_js`, or `browser_agent`.
2. Try another HTTP search engine in the configured order.
3. If GitHub API fails, try a Bing query constrained to GitHub.
4. If all HTTP search paths fail, report the network/proxy blocker and continue with local/offline evidence only after user approval.

On `web_scan` / `web_execute_js` failure:

1. Treat it as a browser bridge/session problem, not a search problem.
2. Reconnect the browser extension/profile if rendered interaction is required.
3. For search-like tasks, fall back to `web_search(engine='bing')`.

## Implementation contract

A compliant `web_search` implementation must:

- Not open a browser window by default.
- Not depend on the current active browser tab.
- Return `status`, `query`, `engine`, `search_url`, `result_count`, and `results` on success.
- Return structured `status='error'`, `engine`, `msg`, and optional `attempts` on failure.
- Never silently return Baidu homepage links as if they were search results.
- Reject unsupported or browser-backed engine values instead of opening a browser tab.

A compliant `web_scan` implementation must:

- Never perform a search query.
- Only inspect current rendered tab state.
- Return tab metadata when `tabs_only=True`.

A compliant failure handler must:

- Not recommend `web_scan` as the next step after ordinary `web_search` network failure.
- Not recommend `browser_agent` as the next step after ordinary `web_search` network failure.
- Recommend a different HTTP search engine or local/offline evidence first.
