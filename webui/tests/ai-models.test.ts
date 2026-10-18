import assert from 'node:assert/strict';
import { test } from 'node:test';
import { newAIModel, supportsModel } from '../src/services/ai-api.ts';

test('models are filtered by required input and output capabilities', () => {
  const model = newAIModel();
  assert.ok(supportsModel(model, ['text'], ['text']));
  assert.equal(supportsModel(model, ['text', 'image'], ['text']), false);
  model.input_types.push('image');
  assert.ok(supportsModel(model, ['text', 'image'], ['text']));
  model.output_types = ['audio'];
  assert.equal(supportsModel(model, ['text'], ['text']), false);
  assert.deepEqual(newAIModel().input_types, ['text']);
});
