export type ServerTableOptions = {
  page: number;
  itemsPerPage: number;
  sortBy: ReadonlyArray<{ key: string; order?: 'asc' | 'desc' }>;
};

export type ApiTableParams = {
  page: number;
  page_size: number;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
};

export async function collectAllPages<T>(
  loadPage: (page: number, pageSize: number) => Promise<{ items: T[]; pages: number }>,
  pageSize: number,
): Promise<T[]> {
  const items: T[] = [];

  for (let page = 1; ; page += 1) {
    const response = await loadPage(page, pageSize);
    items.push(...response.items);
    if (page >= response.pages || response.items.length === 0) return items;
  }
}

export type ServerTableRequestGuard = {
  begin: (key: string) => number;
  isLatest: (requestId: number) => boolean;
  shouldLoad: (key: string) => boolean;
  invalidateFailed: (requestId: number) => void;
};

export function createServerTableRequestGuard(): ServerTableRequestGuard {
  let latestRequestId = 0;
  let lastLoadedOptionsKey: string | undefined;

  return {
    begin(key) {
      const requestId = ++latestRequestId;
      lastLoadedOptionsKey = key;
      return requestId;
    },
    isLatest(requestId) {
      return requestId === latestRequestId;
    },
    shouldLoad(key) {
      return key !== lastLoadedOptionsKey;
    },
    invalidateFailed(requestId) {
      if (requestId === latestRequestId) {
        lastLoadedOptionsKey = undefined;
      }
    },
  };
}

export function toApiTableParams(
  options: ServerTableOptions,
  supportedKeys: ReadonlyArray<string>,
): ApiTableParams {
  const params: ApiTableParams = {
    page: options.page,
    page_size: options.itemsPerPage,
  };
  const firstSort = options.sortBy[0];

  if (
    firstSort &&
    supportedKeys.includes(firstSort.key) &&
    (firstSort.order === 'asc' || firstSort.order === 'desc')
  ) {
    params.sort_by = firstSort.key;
    params.sort_order = firstSort.order;
  }

  return params;
}
