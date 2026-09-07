function cloneField<T>(value: T): T {
  return (Array.isArray(value) ? [...value] : value) as T;
}

function fieldsEqual(left: unknown, right: unknown): boolean {
  if (Array.isArray(left) && Array.isArray(right)) {
    return (
      left.length === right.length &&
      left.every((value, index) => Object.is(value, right[index]))
    );
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
