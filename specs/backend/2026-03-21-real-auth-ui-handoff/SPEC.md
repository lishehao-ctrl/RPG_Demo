# Real Auth UI Handoff Spec

## Purpose

Replace the current fake account-switcher UX with a real auth/session UX that matches the product mental model:

- a person signs in as themselves
- their author jobs, library items, and play sessions belong to that identity
- they do not manually switch between `alice` / `bob` / `local-dev` from a shared dropdown

This pass is frontend-facing, but the architecture direction is backend-owned. The UI agent should implement the frontend against the contract below and remove the old demo-account affordance from shared chrome.

## Product Mental Model

The app is no longer a local studio demo with switchable fake actors.

The correct mental model is:

- unauthenticated users can browse the public library and inspect public story detail
- authenticated users can create stories, publish, manage their own library items, and create/play sessions
- “account” is identity, not workspace
- sign-in state persists via server session cookie, not local fake-user storage

Do not preserve the current fake account switcher in the main UI. This new auth UX should replace it.

## Fixed Backend Contract

The UI should target this contract. If the UI needs a temporary shim during implementation, keep it isolated and do not leak fake-account controls into shared UI.

### Session model

- Cookie-based auth session.
- Frontend must send `credentials: "include"` on HTTP requests.
- Frontend must stop sending `x-rpg-actor-id` / `x-rpg-actor-name`.
- Do not store bearer tokens in `localStorage`.
- Do not store raw password or session secrets in client storage.

### Auth endpoints

#### `GET /auth/session`

Always returns `200`.

Authenticated:

```json
{
  "authenticated": true,
  "user": {
    "user_id": "usr_123",
    "display_name": "Lishe Hao",
    "email": "me@example.com"
  }
}
```

Unauthenticated:

```json
{
  "authenticated": false,
  "user": null
}
```

#### `POST /auth/register`

Request:

```json
{
  "display_name": "Lishe Hao",
  "email": "me@example.com",
  "password": "correct horse battery staple"
}
```

Response:

- `200`
- same shape as `GET /auth/session`
- session cookie already set by server

#### `POST /auth/login`

Request:

```json
{
  "email": "me@example.com",
  "password": "correct horse battery staple"
}
```

Response:

- `200`
- same shape as `GET /auth/session`
- session cookie already set by server

#### `POST /auth/logout`

Response:

- `204`
- session cookie cleared by server

### Existing resource endpoints after auth rollout

- Public read routes may still succeed while logged out:
  - `GET /stories?view=public`
  - `GET /stories/:story_id` for public stories
- Protected create/write routes return `401` with a normal API error body when unauthenticated.
- UI should interpret `401` as “sign in required”, not as a generic crash state.

## Required UI End State

## 1. Remove fake account switching from shared chrome

Current shared header is built around a fake account switcher.

This must be replaced with:

- logged out state:
  - primary CTA: `Sign in`
  - secondary CTA: `Create account`
  - subtle status text is acceptable, but no fake user id
- authenticated state:
  - compact account summary in the header
  - display name primary, email secondary
  - dropdown/menu with at least:
    - `Library`
    - `Create story`
    - `Sign out`

Do not leave the old `<select>` account switcher anywhere in the production shell.

## 2. Add a dedicated auth route/page

Use a route-level auth page, not a tiny utility modal.

Reason:

- auth is now a first-class product boundary
- route redirects are cleaner for protected pages
- this avoids entangling every protected action with bespoke modal state

Required route:

- `#/auth`

Recommended query params:

- `mode=login | register`
- `next=<encoded-app-route>`

The page should:

- preserve the existing visual language of the app
- feel like part of the same studio, not a generic template
- support switching between sign-in and create-account modes without leaving the page
- show inline validation and backend error messages
- redirect to `next` after success, otherwise default to library

## 3. Add session bootstrap at app startup

Replace the current local demo-account bootstrap with a real session bootstrap.

On app boot:

- call `GET /auth/session`
- while loading, keep shell stable and avoid layout jump
- once resolved:
  - set authenticated or unauthenticated state globally
  - render header and route guards from that state

If the session is invalidated during use:

- clear auth state
- return the UI to logged-out mode cleanly
- redirect protected routes to auth with preserved `next`

## 4. Protect the right actions, not the whole site

Logged-out users should still be able to explore the product.

### Logged-out allowed

- open library
- search/filter public library
- open public story detail

### Logged-out gated

- create story
- start author job
- publish a story
- change visibility
- delete owned story
- create play session
- submit play turn

When a logged-out user attempts a gated action:

- route them to `#/auth`
- preserve intended destination/action via `next`
- show concise copy such as `Sign in to create and manage your stories.`

Do not show raw 401 error text in the main page body when this can be handled as a sign-in requirement.

## 5. Library behavior must match auth state

### Logged out

- default library view is effectively public browsing
- do not show view controls that imply private ownership if they cannot work
- no “My stories” affordance in logged-out mode

### Logged in

- full library controls remain available
- “mine / accessible / public” behavior can stay, but the labels should make sense in a real account model

If the current wording feels too tied to the fake-account era, the UI agent may tighten copy, but should not redesign the library IA.

## 6. Create / detail / play pages must adopt real auth state

### Create

- if authenticated: unchanged author flow entry
- if logged out: do not render the fake-author flow as if it can succeed; show auth gate path

### Story detail

- public detail can render while logged out
- owner controls only render when authenticated and `viewer_can_manage` is true

### Play

- a logged-out user may inspect public story detail
- creating a session requires auth
- if a protected play session route is opened without session auth, redirect to `#/auth?next=...`

## 7. Copy and tone

Keep copy short and product-like.

Do not use enterprise/security jargon in user-facing copy.

Good:

- `Sign in to create and manage your stories.`
- `Create an account to save stories and continue play sessions.`

Bad:

- `Authentication required for this resource`
- `Unauthorized`

## Likely Frontend Files

The UI agent will probably need to touch these areas:

- `frontend/src/app/app.tsx`
- `frontend/src/app/routes.ts`
- `frontend/src/app/providers/account-provider.tsx` or its replacement
- `frontend/src/widgets/chrome/app-header.tsx`
- `frontend/src/api/http-client.ts`
- `frontend/src/api/contracts.ts`
- `frontend/src/api/route-map.ts`
- `frontend/src/pages/authoring/create-story-page.tsx`
- `frontend/src/pages/play/story-library-page.tsx`
- `frontend/src/pages/play/story-detail-page.tsx`
- `frontend/src/pages/play/play-session-page.tsx`
- `frontend/src/app/styles.css`

New files are expected for auth route/page/provider hooks if needed.

## In Scope

- replace demo account UX with real auth UX
- add auth route/page
- add authenticated session bootstrap
- add route/action gating for protected flows
- update API client plumbing for cookie sessions
- remove old shared-shell fake account switcher

## Out of Scope

- password reset
- email verification
- multi-factor auth
- social login
- account profile editing
- org/workspace support
- backend auth implementation details

## Non-Negotiable Invariants

- no fake account selector remains in production UI
- no auth token is stored in `localStorage`
- no `x-rpg-actor-*` header dependency remains in HTTP frontend mode
- public browsing works while logged out
- protected mutations route through explicit auth UX instead of failing opaquely
- shared header and shell remain stylistically consistent with the existing app

## Acceptance Criteria

- booting the app while logged out shows a stable logged-out header state
- booting while authenticated shows account summary from session data
- `Create` while logged out routes to auth
- public library browsing works while logged out
- opening a public story detail while logged out works without owner controls
- attempting to start play while logged out routes to auth
- successful sign-in/register returns to the intended route
- sign-out updates shell immediately and removes protected affordances
- TypeScript check passes
- no dead demo-account UX remains reachable from shared shell

## Review Notes For UI Agent

- preserve current art direction
- do not introduce a generic SaaS dashboard aesthetic
- keep the header compact
- avoid a heavy auth redesign that makes library/create/play feel like separate products
- prefer one clear route-level auth flow over scattered modal logic
