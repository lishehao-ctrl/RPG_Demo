Read `/Users/lishehao/Desktop/Project/RPG_Demo/specs/backend/2026-03-21-real-auth-ui-handoff/SPEC.md` first and treat it as authoritative.

Implement the frontend pass for real auth/session UX.

Requirements:
- replace the fake account switcher with real logged-in / logged-out header states
- add a dedicated `#/auth` route/page with login/register modes
- wire app bootstrap to `GET /auth/session`
- update HTTP client plumbing for cookie-based auth and stop depending on `x-rpg-actor-*`
- gate protected create/publish/play actions through auth UX
- keep public library/public story browsing available while logged out
- preserve the current visual language

Do not touch backend files.

When done:
- run `cd frontend && npm run check`
- write changed files, validation, and any backend assumptions into `/Users/lishehao/Desktop/Project/RPG_Demo/specs/backend/2026-03-21-real-auth-ui-handoff/OUTPUT.md`
- then reply to the user with a concise Chinese summary
