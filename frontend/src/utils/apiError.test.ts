import { describe, it, expect } from 'vitest';
import { describeApiError } from './apiError';

describe('describeApiError', () => {
  it('reports a 500 as a server fault rather than a form problem', () => {
    // The case that cost real debugging time: the LLM Configuration page showed
    // "Failed to save provider" for a missing database column.
    const message = describeApiError({ response: { status: 500, data: {} } },
                                     'Failed to save provider');
    expect(message).toContain('500');
    expect(message).toContain('server-side');
    expect(message).toContain('logs');
  });

  it('uses the backend detail when there is one', () => {
    const message = describeApiError(
      { response: { status: 400, data: { detail: 'env_var_name is required' } } },
      'Failed to save provider');
    expect(message).toContain('env_var_name is required');
    expect(message).toContain('400');
  });

  it('flattens FastAPI validation arrays instead of rendering [object Object]', () => {
    const message = describeApiError(
      { response: { status: 422, data: { detail: [
        { loc: ['body', 'model_name'], msg: 'Field required' },
        { loc: ['body', 'api_type'], msg: 'Input should be a valid string' },
      ] } } },
      'Failed to save provider');
    expect(message).toContain('model_name: Field required');
    expect(message).toContain('api_type: Input should be a valid string');
    expect(message).not.toContain('object Object');
  });

  it('distinguishes a request that never reached the server', () => {
    const message = describeApiError({ message: 'Network Error' },
                                     'Failed to save provider');
    expect(message).toContain('could not be reached');
    expect(message).toContain('Network Error');
  });

  it('always carries the status code, even with nothing else to say', () => {
    const message = describeApiError({ response: { status: 403, data: {} } },
                                     'Failed to save provider');
    expect(message).toContain('403');
  });

  it('ignores an empty detail string rather than showing a blank error', () => {
    const message = describeApiError(
      { response: { status: 400, data: { detail: '   ' } } }, 'Failed to save');
    expect(message).toContain('400');
    expect(message.trim().length).toBeGreaterThan(10);
  });
});
