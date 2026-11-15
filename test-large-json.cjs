'use strict';
const assert = require('node:assert/strict'), parse = require('./large-json.cjs');
const cases = [null, true, false, 0, -0, -1.25e40, '', '中文 😀 \\" ] }', [], {},
  {a: [1, null, {b: 'x\\y\"z'}], '__proto__': null, constructor: 'kept'},
  Array.from({length: 1000}, (_, i) => ({i, nested: [i, 'text,{}[]中文', false]}))];
for (const value of cases) {
  const json = JSON.stringify(value);
  for (const chunk of [1, 7, 1024, 8 * 1024 * 1024]) assert.deepEqual(parse(Buffer.from(' \n' + json + '\t'), chunk), JSON.parse(json));
}
const keys = '{"__proto__":{"kept":true},"constructor":4,"x":1,"x":2}';
assert.deepEqual(parse(Buffer.from(keys), 1), JSON.parse(keys));
assert.equal(Object.getPrototypeOf(parse(Buffer.from(keys), 1)), Object.prototype);
for (const bad of ['', ' ', '{', '[}', '{"x":}', '[1,]', '{"x":1,}', '{"x":1 "y":2}', '[true false]', '01', 'true false', '"bad\\q"', '{"x":NaN}', '{"x":1}junk', '{"x":[1,2}', '[1,,2]', '["unterminated]']) {
  for (const chunk of [1, 7, 1024]) assert.throws(() => parse(Buffer.from(bad), chunk), SyntaxError, bad);
}
if (process.argv.includes('--over-v8-limit')) {
  const {MAX_STRING_LENGTH} = require('node:buffer').constants;
  const prefix = Buffer.from('{"payload":['), suffix = Buffer.from('1]}');
  const bytes = Buffer.alloc(MAX_STRING_LENGTH + 64, 32);
  prefix.copy(bytes); suffix.copy(bytes, bytes.length - suffix.length);
  assert.throws(() => JSON.parse(bytes), {code: 'ERR_STRING_TOO_LONG'});
  assert.deepEqual(parse(bytes), {payload: [1]});
  console.log('PASS: JSON Buffer above V8 string limit, exact values retained');
}
console.log('PASS: exact JSON values, Unicode, escaping, duplicate/prototype keys and invalid syntax');
