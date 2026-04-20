export type ConceptVariant = "casefile" | "series"

export type AuthorConceptStage = "create" | "loading"

export function normalizeConceptVariant(value: string | null | undefined): ConceptVariant {
  return value === "series" ? "series" : "casefile"
}

export function normalizeAuthorConceptStage(value: string | null | undefined): AuthorConceptStage {
  return value === "loading" ? "loading" : "create"
}
