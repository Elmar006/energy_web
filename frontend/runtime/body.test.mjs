import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readLimitedBody, readLimitedJson, BodyTooLarge } from './body.mjs';

test('body limit applies with and without content-length, including chunked input', async () => {
  await assert.rejects(readLimitedBody(new Request('http://local', {method:'POST', body:'abcdef', headers:{'content-length':'6'}}), 5), BodyTooLarge);
  let cancelled = false;
  const body = new ReadableStream({ start(c) { c.enqueue(new Uint8Array(4)); c.enqueue(new Uint8Array(4)); }, cancel() { cancelled = true; } });
  await assert.rejects(readLimitedBody(new Request('http://local', { method:'POST', body, duplex:'half' }), 5), BodyTooLarge);
  assert.equal(cancelled, true);
  assert.equal((await readLimitedBody(new Request('http://local', {method:'POST', body:'12345'}), 5)).byteLength, 5);
});
test('JSON reader rejects malformed documents and preserves the supplied object', async () => {
  await assert.rejects(readLimitedJson(new Request('http://local', {method:'POST', body:'{' }), 10), SyntaxError);
  assert.deepEqual(await readLimitedJson(new Request('http://local', {method:'POST', body:'{"x":0}' }), 10), { x: 0 });
});
