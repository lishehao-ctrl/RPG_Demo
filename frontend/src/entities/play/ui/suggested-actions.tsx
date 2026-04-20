import type { PlayControlAction, PlaySuggestedAction } from "../../../index"

const CONTROL_ACTION_LABEL: Record<PlayControlAction["action_type"], string> = {
  press: "Press",
  redirect: "Redirect",
  detonate: "Detonate",
  none: "None",
}

function controlMeta(action: PlayControlAction): string {
  const meta: string[] = []
  if (action.target_mode) {
    meta.push(`Target Mode: ${action.target_mode}`)
  }
  if (action.target_kind) {
    meta.push(`Target Kind: ${action.target_kind}`)
  }
  if (action.target_id) {
    meta.push(`Target ID: ${action.target_id}`)
  }
  return meta.join(" · ")
}

export function SuggestedActions({
  storyActions,
  controlActions,
  selectedSuggestionId,
  selectedControlActionId,
  onSelectStoryAction,
  onSelectControlAction,
}: {
  storyActions: PlaySuggestedAction[]
  controlActions: PlayControlAction[]
  selectedSuggestionId: string | null
  selectedControlActionId: string | null
  onSelectStoryAction: (action: PlaySuggestedAction) => void
  onSelectControlAction: (action: PlayControlAction) => void
}) {
  if (storyActions.length === 0 && controlActions.length === 0) {
    return <p className="editorial-support">No more prompts because this session has reached an ending.</p>
  }

  return (
    <>
      <p className="editorial-support">Suggestions are optional. Clicking one only replaces the input draft.</p>

      {storyActions.length > 0 ? (
        <div className="play-suggestion-group">
          <span className="editorial-metadata-label">Story Actions</span>
          <div className="play-suggestion-list">
            {storyActions.map((action) => (
              <button
                className={`play-suggestion ${selectedSuggestionId === action.suggestion_id ? "is-selected" : ""}`}
                key={action.suggestion_id}
                onClick={() => onSelectStoryAction(action)}
                type="button"
              >
                <span className="material-symbols-outlined">arrow_forward</span>
                <div>
                  <strong>{action.label}</strong>
                  <span>{action.prompt}</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {controlActions.length > 0 ? (
        <div className="play-suggestion-group">
          <span className="editorial-metadata-label">Control Actions</span>
          <div className="play-suggestion-list">
            {controlActions.map((action) => {
              const meta = controlMeta(action)
              return (
                <button
                  className={`play-suggestion ${selectedControlActionId === action.action_id ? "is-selected" : ""}`}
                  key={action.action_id}
                  onClick={() => onSelectControlAction(action)}
                  title={meta || undefined}
                  type="button"
                >
                  <span className="material-symbols-outlined">tune</span>
                  <div>
                    <strong>
                      {action.label}
                      <span className="play-suggestion__badge">{CONTROL_ACTION_LABEL[action.action_type]}</span>
                    </strong>
                    <span>{action.prompt}</span>
                    {meta ? <span className="play-suggestion__meta">{meta}</span> : null}
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      ) : null}
    </>
  )
}
