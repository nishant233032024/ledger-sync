/**
 * Small class-name helper used by the local shadcn-style primitives.
 * It intentionally avoids another dependency for this learning project.
 */
export function cn(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}
