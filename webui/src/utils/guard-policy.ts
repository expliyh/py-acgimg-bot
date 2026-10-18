function cloneField<T>(value: T): T {
  if (Array.isArray(value)) return value.map(cloneField) as T;
  if (value !== null && typeof value === 'object') return cloneGuardPolicy(value) as T;
  return value;
}

function fieldsEqual(left: unknown, right: unknown): boolean {
  if (Array.isArray(left) && Array.isArray(right)) {
    return (
      left.length === right.length &&
      left.every((value, index) => fieldsEqual(value, right[index]))
    );
  }
  if (left !== null && right !== null && typeof left === 'object' && typeof right === 'object') {
    const keys = Object.keys(left);
    return keys.length === Object.keys(right).length && keys.every((key) =>
      Object.prototype.hasOwnProperty.call(right, key) && fieldsEqual((left as Record<string, unknown>)[key], (right as Record<string, unknown>)[key]));
  }
  return Object.is(left, right);
}

export function cloneGuardPolicy<T extends object>(policy: T): T {
  const clone = {} as T;
  for (const key of Object.keys(policy) as (keyof T)[]) {
    clone[key] = cloneField(policy[key]);
  }
  return clone;
}

export function changedGuardPolicy<T extends object>(
  current: T,
  baseline: T,
): Partial<T> {
  const changes: Partial<T> = {};
  for (const key of Object.keys(current) as (keyof T)[]) {
    if (!fieldsEqual(current[key], baseline[key])) {
      changes[key] = cloneField(current[key]);
    }
  }
  return changes;
}
