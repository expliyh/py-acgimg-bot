import type { DataTableHeader } from 'vuetify';

import type { IllustrationImportTask } from '@/services/api';

export type IllustrationTaskRowProps = {
  class: string;
  onClick: (event: MouseEvent) => void;
};

export function createIllustrationTaskHeaders(
  tasks: readonly IllustrationImportTask[],
): DataTableHeader<IllustrationImportTask>[] {
  const headers: DataTableHeader<IllustrationImportTask>[] = [
    { title: 'ID', key: 'id', sortable: false },
    { title: 'Pixiv ID', key: 'pixiv_id', sortable: false },
    { title: '标题', key: 'title', sortable: false },
    { title: '状态', key: 'status', sortable: false },
    { title: '进度', key: 'progress', sortable: false },
    { title: '创建时间', key: 'created_at', sortable: false },
  ];

  if (tasks.some((task) => Boolean(task.error_message?.trim()))) {
    headers.push({ title: '错误信息', key: 'error_message', sortable: false });
  }

  return headers;
}

export function createIllustrationTaskRowProps(
  item: IllustrationImportTask,
  selectedId: number | null,
  onSelect: (item: IllustrationImportTask) => void,
): IllustrationTaskRowProps {
  return {
    class: selectedId === item.id ? 'selected-task-row' : '',
    onClick: (_event: MouseEvent) => onSelect(item),
  };
}
