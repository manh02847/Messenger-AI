const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
vm.runInThisContext(fs.readFileSync(path.join(__dirname, '../experimental/call-lab-extension/pcm.js'), 'utf8'));
const {Resampler, encode, decode} = globalThis.CallLabPCM;

test('PCM is signed little endian, clips and round-trips without more than one quantization step', () => {
  const samples = Float32Array.from([-2, -1, -.5, 0, .5, 1, 2]);
  const bytes = Buffer.from(encode(samples), 'base64');
  assert.equal(bytes.readInt16LE(0), -32768);
  assert.equal(bytes.readInt16LE(12), 32767);
  const out = decode(bytes.toString('base64'));
  for (let i=0; i<samples.length; i++) assert.ok(Math.abs(out[i]-Math.max(-1,Math.min(1,samples[i]))) <= 1/32768);
});

for (const rate of [16000, 24000, 44100, 48000]) {
  test(`streaming ${rate} Hz to 16k keeps sample count and a 440 Hz tone across arbitrary chunk boundaries`, () => {
    const input = Float32Array.from({length:rate}, (_,i)=>.5*Math.sin(2*Math.PI*440*i/rate));
    const resampler = new Resampler(rate);
    const output=[];
    for(let offset=0;offset<input.length;offset+=137) output.push(...resampler.push(input.subarray(offset,offset+137)));
    assert.ok(Math.abs(output.length-16000)<=2);
    let error=0;
    for(let i=0;i<output.length;i++) error+=(output[i]-.5*Math.sin(2*Math.PI*440*i/16000))**2;
    assert.ok(Math.sqrt(error/output.length)<.003);
  });
}
test('invalid rate and odd PCM bytes are rejected', () => {
  assert.throws(()=>new Resampler(0));
  assert.throws(()=>decode(Buffer.from([1]).toString('base64')));
});
