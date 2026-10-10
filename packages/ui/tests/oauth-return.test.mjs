import { test } from 'node:test';
import assert from 'node:assert/strict';
import { consentReturn } from '../src/lib/oauthReturn.ts';

const nonce = 'a'.repeat(43);
test('login resumes only a valid local OAuth consent request', () => {
  const next = `/connect/?request=${nonce}`;
  assert.equal(consentReturn(`?next=${encodeURIComponent(next)}`), next);
  assert.equal(consentReturn(`?next=${encodeURIComponent(`/connect?request=${nonce}&other=discard`)}`), next);
});
test('login return cannot become an external or unrelated redirect', () => {
  for (const next of [
    `https://evil.example/connect?request=${nonce}`, `//evil.example/connect?request=${nonce}`,
    `/\\evil.example/connect?request=${nonce}`, '/admin', '/connect/?request=short',
    `/connect/?request=${nonce}#fragment`, `/connect/nested?request=${nonce}`,
  ]) assert.equal(consentReturn(`?next=${encodeURIComponent(next)}`), null);
  assert.equal(consentReturn(''), null);
});
