/** Compare wire values without treating object key order as source identity. */
export function sameValue(left: unknown, right: unknown): boolean {
  if (left === right) return true
  if (Array.isArray(left) && Array.isArray(right)) return left.length === right.length && left.every((value, index) => sameValue(value, right[index]))
  if (typeof left !== 'object' || left === null || Array.isArray(left) || typeof right !== 'object' || right === null || Array.isArray(right)) return false
  const a = left as Record<string, unknown>; const b = right as Record<string, unknown>
  const keys = Object.keys(a).sort()
  return keys.join(',') === Object.keys(b).sort().join(',') && keys.every((key) => sameValue(a[key], b[key]))
}
