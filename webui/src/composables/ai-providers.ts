import { onMounted, ref, shallowReadonly } from 'vue';
import { aiApi, type AIProvider } from '@/services/ai-api';

const providers = ref<AIProvider[]>([]);
const loading = ref(false);
const error = ref('');
let request: Promise<void> | null = null;

function refresh(): Promise<void> {
  if (request) return request;
  loading.value = true;
  error.value = '';
  request = aiApi.list().then((value) => {
    providers.value = value;
  }).catch(() => {
    error.value = '无法加载 AI 提供商，请重试。';
  }).finally(() => {
    loading.value = false;
    request = null;
  });
  return request;
}

export function useAIProviders() {
  onMounted(refresh);
  return { providers: shallowReadonly(providers), loading: shallowReadonly(loading), error: shallowReadonly(error), refresh };
}
