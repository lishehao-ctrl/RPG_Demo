import type { PublishedStoryCard } from "../../index"

export function formatPublishedAt(value: string): string {
  return new Date(value).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function progressWidth(currentValue: number, minValue: number, maxValue: number): string {
  const range = Math.max(1, maxValue - minValue)
  const bounded = Math.min(maxValue, Math.max(minValue, currentValue))
  return `${((bounded - minValue) / range) * 100}%`
}

export function sortStoriesByNewest(stories: PublishedStoryCard[]): PublishedStoryCard[] {
  return [...stories].sort((left, right) => {
    return new Date(right.published_at).getTime() - new Date(left.published_at).getTime()
  })
}
