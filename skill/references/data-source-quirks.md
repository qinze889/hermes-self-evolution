# Data Source Quirks — Hermes Learner v3.1

Collected API behaviors, failure modes, and remediation for the three learner data sources.

See also the learner script: `~/.hermes/scripts/learn_eval_propose.sh`

## AI HOT (aihot.virxact.com)

### API
```python
GET /api/public/items?mode=selected&since={ISO8601_UTC}&take=50
```

### Known behaviors
- **Returns JSON** directly. No auth needed.
- **Requires browser User-Agent**. Without one, returns 403 Forbidden.
- **Category field**: `ai-products`, `industry`, `tip`, etc.
- **Items are Chinese-heavy**. Scoring needed Chinese keywords (模型/降价/供应链/攻击/安全/gpt/claude/deepseek/开源/发布等) otherwise all items score 0-2 and get filtered.
- **AI HOT now generates proposals** (V3.1+). `AIHOT_PROPOSAL_SCORE` removed entirely. Items scoring ≥7 call `generate_actions()`. Most items still score 2-6 (general news) so few proposals emerge naturally.
- **`since` in UTC**. Use CST→UTC conversion.

### Failure modes
| Symptom | Cause | Fix |
|---------|-------|-----|
| 403 Forbidden | Missing/wrong User-Agent | Use browser UA string |
| Items fetched but 0 saved | Chinese content filtered by EN-only keyword list | Add Chinese KW_SCORES entries |

## GitHub Search API

### API
```python
GET https://api.github.com/search/repositories?q={query}&sort=updated&order=desc&per_page=5
```

### Known behaviors
- **Returns JSON** with `items[].{full_name, description, html_url, updated_at, language, stargazers_count, topics}`.
- **Requires `GITHUB_TOKEN`**. Without it, unauthenticated requests get 403 rate-limited quickly (60 req/hr vs 5000 req/hr with token). Script auto-loads from `.env` if not in environment.
- **Topics search**: `topic:ai-agent`, `topic:mcp-server`, `topic:agent-framework`.
- **Full-text search**: `AI agent framework tool`, `MCP server tools LLM`.
- **OR between qualifiers is NOT supported**. `topic:ai-agent+OR+topic:mcp-server` returns 422. Always use separate queries.
- **Star bonus** applied: +1 for >1000 stars. Agent/MCP keyword bonus: +1.
- **5 queries** in V3.1 (was 9 in V3). The merged topic query approach didn't work due to OR restriction. Reduced by keeping only the 3 most distinct topic queries + 2 text fallbacks.
- **Seen-items dedup** uses `seen_items.json` with SHA256 hash of `source|url|title`. Also uses `seen_titles` set in-memory for same-run dedup across queries.

### Failure modes
| Symptom | Cause | Fix |
|---------|-------|-----|
| 403 rate limit | No GITHUB_TOKEN | Add to .env (fine-grained, zero scopes) |
| Connection refused (Errno 111) | Proxy (mihomo) port not ready | Check mihomo startup: old process may hold port. Add ExecStartPre kill. |
| 422 Validation Failed | OR between qualifiers | Don't use OR for topic: queries. Use separate calls. |

## Arxiv API

### API
```python
GET https://export.arxiv.org/api/query?search_query={query}&max_results=5&sortBy=submittedDate&sortOrder=descending
```

### Known behaviors (CRITICAL — changed in 2026)
- **Returns XML**, not JSON. **Never use `http_get_json()`**. Always parse XML with `xml.etree.ElementTree`.
- **Redirects**: HTTP→HTTPS (301). Use `https://` directly.
- **Namespace**: `http://www.w3.org/2005/Atom` (prefix `atom:`).
- **Rate limit**: ~1 request per 3 seconds. Bursts return 429 with HTML error page.
- **Upstream instability**: Between 2026-05-23 and 2026-05-25, the API started returning empty responses / non-parsable data for some queries.
- **Atom entry fields**:
  - `atom:id` — URL like `http://arxiv.org/abs/XXXX.XXXXX`
  - `atom:title` — Paper title
  - `atom:summary` — Abstract
  - `atom:published` — Date YYYY-MM-DD
  - `atom:link[href]` — Link to paper

### Failure modes
| Symptom | Cause | Fix |
|---------|-------|-----|
| `Expecting value: line 1 column 1` | JSON parse on HTML (429 page) | Use direct XML parsing, never http_get_json |
| HTTP 429 | Burst rate exceeded | Add retry with backoff (5s, 10s) |
| Empty response | Upstream API flakiness | Retry once, skip if still empty |
| Empty result for valid queries | API may have changed query syntax | Test manually with curl before debugging code |

### Retry pattern (proven)
```python
for attempt in range(3):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Hermes-Learner/3.0"})
        ctx = ssl.create_default_context()
        resp = urllib.request.urlopen(req, timeout=30, context=ctx)
        xml_text = resp.read()
        root = ET.fromstring(xml_text)
        break
    except urllib.error.HTTPError as e:
        if e.code == 429 and attempt < 2:
            wait = 5 * (attempt + 1)
            time.sleep(wait)
            continue
        raise  # re-raise non-429 or exhausted retries
```
