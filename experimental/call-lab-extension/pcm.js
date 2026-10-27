/* PCM helpers have no browser or account access; also used by offline tests. */
(() => {
  class Resampler {
    constructor(inputRate, outputRate = 16000) {
      if (!(inputRate > 0 && outputRate > 0)) throw new Error("sample rate");
      this.step = inputRate / outputRate;
      this.tail = new Float32Array(0);
      this.position = 0;
    }
    push(samples) {
      const input = new Float32Array(this.tail.length + samples.length);
      input.set(this.tail);
      input.set(samples, this.tail.length);
      if (!input.length) return new Float32Array(0);
      const output = [];
      while (this.position + 1 < input.length) {
        const index = Math.floor(this.position);
        const fraction = this.position - index;
        output.push(input[index] + (input[index + 1] - input[index]) * fraction);
        this.position += this.step;
      }
      const keep = Math.min(Math.floor(this.position), input.length - 1);
      this.tail = input.slice(keep);
      this.position -= keep;
      return Float32Array.from(output);
    }
  }
  function encode(samples) {
    const bytes = new Uint8Array(samples.length * 2);
    const view = new DataView(bytes.buffer);
    for (let i = 0; i < samples.length; i++) {
      const value = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(i * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
    }
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary);
  }
  function decode(encoded) {
    const binary = atob(encoded);
    if (binary.length % 2) throw new Error("PCM size");
    const bytes = Uint8Array.from(binary, value => value.charCodeAt(0));
    const view = new DataView(bytes.buffer);
    const samples = new Float32Array(bytes.length / 2);
    for (let i = 0; i < samples.length; i++) samples[i] = view.getInt16(i * 2, true) / 32768;
    return samples;
  }
  globalThis.CallLabPCM = Object.freeze({Resampler, encode, decode});
})();
