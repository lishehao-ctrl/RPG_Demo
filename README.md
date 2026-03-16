# RPG Demo Rebuild

This repository has been reset for a clean rebuild.

Current scope:

- keep `.env` as the source of LLM API configuration
- rebuild the backend around official LangGraph state management
- define a `DesignBundle`-first author pipeline before any play runtime

The new minimal backend currently includes:

- `FocusedBrief`
- `StoryBible`
- `StateSchema`
- `BeatSpine`
- `RulePack`
- `DesignBundle`
- an official LangGraph author workflow with checkpoint support
- a minimal FastAPI endpoint to generate a design bundle

Next intended layers:

1. real LLM-backed overview and rule generation
2. beat compiler subgraph
3. play runtime driven by `DesignBundle`
