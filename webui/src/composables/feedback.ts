import { reactive } from 'vue';

const defaultConfirmationHeader = '确认操作';

type ConfirmationCallback = () => void;

export interface ConfirmationPayload {
  message?: string;
  header?: string;
  icon?: string;
  acceptLabel?: string;
  rejectLabel?: string;
  accept?: ConfirmationCallback;
  reject?: ConfirmationCallback;
}

interface ConfirmationState {
  open: boolean;
  message: string;
  header: string;
  icon: string;
  acceptLabel: string;
  rejectLabel: string;
  accept?: ConfirmationCallback;
  reject?: ConfirmationCallback;
}

export const feedbackState = reactive({
  open: false,
  severity: 'info',
  summary: '',
  detail: '',
  life: 3500
});

export const confirmState = reactive<ConfirmationState>({
  open: false,
  message: '',
  header: defaultConfirmationHeader,
  icon: '',
  acceptLabel: '确认',
  rejectLabel: '取消',
  accept: undefined,
  reject: undefined
});

export function normalizeVuetifyColor(color: string): string {
  if (color === 'danger') return 'error';
  if (color === 'warn') return 'warning';
  if (color === 'help') return 'info';
  return color;
}

export function closeConfirmation() {
  confirmState.open = false;
  confirmState.accept = undefined;
  confirmState.reject = undefined;
}

function resolveConfirmation(callback?: ConfirmationCallback) {
  closeConfirmation();
  callback?.();
}

export function acceptConfirmation() {
  resolveConfirmation(confirmState.accept);
}

export function rejectConfirmation() {
  resolveConfirmation(confirmState.reject);
}

export function useFeedback() {
  return {
    toast: {
      add(payload: { severity?: string; summary?: string; detail?: string; life?: number }) {
        feedbackState.severity = normalizeVuetifyColor(payload.severity ?? 'info');
        feedbackState.summary = payload.summary ?? '';
        feedbackState.detail = payload.detail ?? '';
        feedbackState.life = payload.life ?? 3500;
        feedbackState.open = true;
      }
    },
    confirm: {
      require(payload: ConfirmationPayload) {
        confirmState.message = payload.message ?? '确认执行此操作？';
        confirmState.header = payload.header?.trim() ? payload.header : defaultConfirmationHeader;
        confirmState.icon = payload.icon ?? '';
        confirmState.acceptLabel = payload.acceptLabel ?? '确认';
        confirmState.rejectLabel = payload.rejectLabel ?? '取消';
        confirmState.accept = payload.accept;
        confirmState.reject = payload.reject;
        confirmState.open = true;
      },
      close() {
        closeConfirmation();
      }
    }
  };
}
