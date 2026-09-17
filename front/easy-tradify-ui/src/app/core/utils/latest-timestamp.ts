/** Latest timestamp across a list, for panels whose liveness proof is a stream, not a single record. */
export function latestTimestamp<T>(items: readonly T[], select: (item: T) => number, fallback = Date.now()): number {
  return items.length ? items.reduce((max, item) => Math.max(max, select(item)), 0) : fallback;
}
