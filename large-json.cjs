/* Parse a JSON Buffer without converting the entire archive to one V8 string.
 * Individual leaves still use JSON.parse, preserving values and validation.
 * This only changes build-time decoding, never the archived bytes or scores.
 */
'use strict';
module.exports = function parseLargeJSON(input, chunkBytes = 8 * 1024 * 1024) {
  const bytes = Buffer.isBuffer(input) ? input : Buffer.from(input);
  if (!Number.isSafeInteger(chunkBytes) || chunkBytes < 1) throw new RangeError('Invalid JSON chunk size');
  const whitespace = n => n === 32 || n === 9 || n === 10 || n === 13;
  const fail = pos => { throw new SyntaxError(`Invalid JSON at byte ${pos}`); };
  const skip = pos => { while (pos < bytes.length && whitespace(bytes[pos])) pos++; return pos; };
  function stringEnd(pos) {
    for (let i = pos + 1; i < bytes.length; i++) {
      if (bytes[i] === 92) i++;
      else if (bytes[i] === 34) return i + 1;
    }
    return fail(pos);
  }
  function valueEnd(pos) {
    const first = bytes[pos];
    if (first === 34) return stringEnd(pos);
    if (first !== 123 && first !== 91) {
      let i = pos;
      while (i < bytes.length && !whitespace(bytes[i]) && ![44, 93, 125].includes(bytes[i])) i++;
      if (i === pos) fail(pos);
      return i;
    }
    const stack = [first === 123 ? 125 : 93];
    let i = pos + 1;
    while (i < bytes.length) {
      const b = bytes[i];
      if (b === 34) { i = stringEnd(i); continue; }
      if (b === 123 || b === 91) stack.push(b === 123 ? 125 : 93);
      else if (b === 125 || b === 93) {
        if (stack.pop() !== b) fail(i);
        if (!stack.length) return i + 1;
      }
      i++;
    }
    return fail(pos);
  }
  function parse(start, end) {
    const first = bytes[start];
    if (end - start <= chunkBytes || (first !== 123 && first !== 91)) {
      return JSON.parse(bytes.toString('utf8', start, end));
    }
    const object = first === 123, close = object ? 125 : 93, out = object ? {} : [];
    let pos = skip(start + 1);
    if (bytes[pos] === close && pos === end - 1) return out;
    while (pos < end) {
      let key;
      if (object) {
        if (bytes[pos] !== 34) fail(pos);
        const keyEnd = stringEnd(pos);
        key = JSON.parse(bytes.toString('utf8', pos, keyEnd));
        pos = skip(keyEnd);
        if (bytes[pos] !== 58) fail(pos);
        pos = skip(pos + 1);
      }
      const next = valueEnd(pos);
      if (next >= end) fail(next);
      const value = parse(pos, next);
      // Assignment would give __proto__ a different meaning from JSON.parse.
      if (object) Object.defineProperty(out, key, {value, writable: true, enumerable: true, configurable: true});
      else out.push(value);
      pos = skip(next);
      if (bytes[pos] === close && pos === end - 1) return out;
      if (bytes[pos] !== 44) fail(pos);
      pos = skip(pos + 1);
      if (bytes[pos] === close) fail(pos);
    }
    return fail(pos);
  }
  const start = skip(0), end = valueEnd(start);
  if (skip(end) !== bytes.length) fail(end);
  return parse(start, end);
};
