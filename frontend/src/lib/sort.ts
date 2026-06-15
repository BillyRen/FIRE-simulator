/**
 * Compare two sortable values for table sorting.
 * null/undefined ALWAYS sort last, regardless of direction (so missing data
 * never floats to the top on a descending sort). Numbers compare numerically;
 * everything else via localeCompare on the string form.
 *
 * @param dir 1 = ascending, -1 = descending
 */
export function compareNullable(
  a: number | string | null | undefined,
  b: number | string | null | undefined,
  dir: 1 | -1,
): number {
  const aNull = a === null || a === undefined;
  const bNull = b === null || b === undefined;
  if (aNull && bNull) return 0;
  if (aNull) return 1; // a is null → after b
  if (bNull) return -1; // b is null → after a
  if (typeof a === "number" && typeof b === "number") return (a - b) * dir;
  return String(a).localeCompare(String(b)) * dir;
}
