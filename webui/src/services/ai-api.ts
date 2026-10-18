import axios from 'axios';

export interface AISelection {
  provider_id: string;
  model: string;
}

export type AIModality = 'text' | 'image' | 'audio' | 'video' | 'file';

export interface AIModel {
  id: string;
  max_input_tokens: number | null;
  max_output_tokens: number | null;
  input_types: AIModality[];
  output_types: AIModality[];
}

export const modalityOptions: { title: string; value: AIModality }[] = [
  { title: '文本', value: 'text' }, { title: '图片', value: 'image' },
  { title: '音频', value: 'audio' }, { title: '视频', value: 'video' },
  { title: '文件', value: 'file' },
];

export function newAIModel(): AIModel {
  return { id: '', max_input_tokens: null, max_output_tokens: null, input_types: ['text'], output_types: ['text'] };
}

export function supportsModel(model: AIModel, inputs: AIModality[], outputs: AIModality[]) {
  return inputs.every((type) => model.input_types.includes(type)) && outputs.every((type) => model.output_types.includes(type));
}

export interface AIProviderInput {
  name: string;
  base_url: string;
  api_key?: string | null;
  models: AIModel[];
  timeout: number;
  concurrency: number;
}

export interface AIProvider extends Omit<AIProviderInput, 'api_key'> {
  id: string;
  has_api_key: boolean;
}

const client = axios.create({ baseURL: '/api/ai/providers', timeout: 30000 });
export const aiApi = {
  list: async (): Promise<AIProvider[]> => (await client.get('')).data,
  create: async (value: AIProviderInput): Promise<AIProvider> => (await client.post('', value)).data,
  update: async (id: string, value: AIProviderInput): Promise<AIProvider> =>
    (await client.put(`/${encodeURIComponent(id)}`, value)).data,
  remove: async (id: string): Promise<void> => { await client.delete(`/${encodeURIComponent(id)}`); },
};
