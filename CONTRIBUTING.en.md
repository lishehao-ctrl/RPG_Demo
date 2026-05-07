# Contributing

> Language: this doc is the English mirror of [CONTRIBUTING.md](./CONTRIBUTING.md).

Thanks for thinking about helping out. This is a small project run by
a small team — we read every issue and most PRs.

## What we want

The project is in **OSS preview / alpha**. The mechanism design (9
narrative engine layers + post-game highlights / branches) is mostly
settled, but everything around it — UX polish, deployment story,
provider support, internationalization — has plenty of room.

The highest-leverage areas to contribute, in roughly descending order:

1. **Real-player feedback.** Open an issue describing what happened in
   your session: what did you find confusing, what felt rewarding,
   where did you stop reading. We have ~0 real-human test data so far,
   so this is more useful than a code patch. Write in any language.

2. **Schedulers as deterministic unit tests.** The narrative engine's
   schedulers (`_pick_npc_agenda`, `_pick_twist_directive`,
   `compute_current_inventory`, `_summarize_recent_consequences`,
   `_parse_branches`, `_parse_player_role_options`) are pure functions
   with structured I/O. They have **zero deterministic test coverage**
   today. Adding `tests/test_narrative_schedulers.py` would let us
   refactor with confidence. Highest practical-engineering value.

3. **Provider abstraction.** The gateway layer assumes an OpenAI-
   compatible Responses API; in practice this works for DashScope,
   OpenAI, OpenRouter, and Ollama. But there's no clean fallback path
   for Anthropic-native, Gemini-native, or other shapes. A small
   adapter interface in `gateway.py` would broaden the user pool.

4. **More locales.** The frontend now has a zh/en string bundle layer
   (`frontend2/src/shared/lib/i18n.ts`) and the backend `engine.py`
   prompts accept a language hint. Adding a third locale (e.g. `ja`,
   `es`) requires extending the `STRINGS_*` bundles plus the
   prompt-language switch. The ending-label canonical IDs stay
   Chinese — only the display map needs translating.

5. **Streaming narration.** Right now `passage` arrives as one full
   blob after a 5-8s LLM call. Streaming would dramatically improve
   perceived responsiveness. `responses_transport.py` likely already
   has a streaming code path; the engine layer would need to expose
   token chunks.

6. **Persistent in-game HUD.** The role banner shows `current_inventory`
   but doesn't surface inter-NPC leverage state or NPC pulse history
   in one place. A sidebar / drawer would help hardcore players track
   the political map without scrolling.

If you want to do something different, please open an issue describing
your plan first. The prompt-driven design has subtle invariants that
aren't obvious from the code — review by the maintainers before a
multi-week effort saves both sides time.

## How to send a PR

1. Fork the repo.
2. Branch off `main`. Use a descriptive branch name (e.g.
   `feat/anthropic-gateway` not `patch-1`).
3. **Run the local checks before pushing:**
   ```bash
   # backend
   pytest -q

   # frontend
   cd frontend2
   npm run check
   npm run build
   ```
   The CI runs the same.
4. Open the PR. In the description, link the issue you're addressing
   (or describe the problem if there's no issue).
5. Keep PRs small and focused. One feature per PR; one bugfix per PR.
   We will not merge a 2000-line PR that touches 20 unrelated things.

## Style

- **Backend Python:** type hints required on new public functions.
  Pydantic contracts in `narrative/contracts.py` are the canonical
  schema; mirror new fields into `frontend2/src/api/contracts.ts` in
  the same PR.
- **Frontend TypeScript:** strict mode is on. No `any` in new code.
  Style follows existing files; no formatter is enforced.
- **Comments:** comment the *why*, not the *what*. The codebase has
  many examples of this — the existing prompt sections in
  `engine.py` are a model for how invariants are documented inline.
- **Commits:** prefer atomic commits. Conventional-commit style
  (`feat:`, `fix:`, `docs:`, `polish:`) is welcome but not required.

## Testing philosophy

The narrative engine has **two complementary test surfaces**:

- **Deterministic unit tests** for pure functions (schedulers, parsers,
  helpers). These should not call the LLM and should be fast.
- **LLM smoke tests** for end-to-end correctness. These call the real
  LLM and verify the contract holds (e.g. `npc_pulse[].reason` is
  populated when shift != steady). We run these manually, not in CI.

If you add a new mechanism, add at least one deterministic test for the
scheduler / parser layer. End-to-end LLM verification is encouraged
but not required for merge.

## Code of conduct

Be kind. Don't post private user data. Don't submit content that
glorifies violence, harassment, or targets real people without their
consent. We reserve the right to remove issues / PRs / comments at our
discretion if they cross those lines.

## Questions

Open an issue with the `question` label, or email
hello@tinystories.app (if listed in `frontend2/src/pages/about/`).
