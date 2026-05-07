---
name: Bug report
about: Something doesn't work as expected
title: '[bug] '
labels: bug
assignees: ''
---

## What happened

<!-- Describe what went wrong. If LLM output looks weird, paste the
output verbatim — say which mechanism / function generated it. -->

## What you expected

<!-- One or two sentences. -->

## How to reproduce

<!-- Minimum steps. If it's a play-time issue, the seed + role index +
turn number is usually enough. If it's a server error, paste the
relevant lines from the uvicorn log. -->

```
seed: ...
role index: ...
turn: ...
```

## Environment

- Python: <!-- 3.11 / 3.12 / etc -->
- LLM provider: <!-- DashScope qwen3.6-flash / OpenAI gpt-4o-mini / Ollama qwen2.5 / etc -->
- Browser: <!-- if frontend issue -->
- Commit: <!-- git rev-parse HEAD -->

## Anything else

<!-- Stack traces, screenshots, related issues — drop them here. -->
