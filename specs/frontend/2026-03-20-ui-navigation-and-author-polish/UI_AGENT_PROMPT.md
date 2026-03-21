Read this spec first:

- `/Users/lishehao/Desktop/Project/RPG_Demo/specs/frontend/2026-03-20-ui-navigation-and-author-polish/SPEC.md`

You are the UI implementation owner for this pass.

Your job:

- implement the frontend-only polish defined in the spec
- stay strictly within the current public product contract
- do not change backend code
- do not upload anything to any server

Important constraints:

- do not use `/benchmark/*`
- do not invent frontend-only data
- if you believe the UI needs new backend fields, stop and report the exact missing field instead of faking it
- preserve the current editorial visual language

Implementation focus:

1. create page input clarity and above-the-fold CTA
2. animated preview generation state
3. stable author loading card area
4. real in-page sidebar navigation for play and story detail
5. collapsible right-rail organization on play

Preferred workflow:

1. inspect current local files named in the spec
2. implement the smallest coherent set of frontend changes
3. validate with:
   - `cd /Users/lishehao/Desktop/Project/RPG_Demo/frontend && npm run check`
4. summarize:
   - what changed
   - which files changed
   - any unresolved UX question

Do not treat fake tabs or dead links as acceptable. If a sidebar item exists, it must either:

- navigate to a real section
- or be clearly and intentionally absent

Favor clarity and consistency over feature inflation.
