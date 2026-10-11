import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const css = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');
const root = css.match(/:root\s*\{([\s\S]*?)\}/)?.[1];

function color(name) {
  const hex = root?.match(new RegExp(`${name}:\\s*(#[0-9a-f]{6})\\s*;`, 'i'))?.[1];
  assert.ok(hex, `Missing root color: ${name}`);
  return hex;
}

function luminance(hex) {
  const channels = hex.slice(1).match(/../g).map((value) => parseInt(value, 16) / 255)
    .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

test('small secondary labels meet minimum text contrast on the opaque workspace surfaces', () => {
  const foreground = luminance(color('--text-faint'));
  for (const surface of ['--surface-0', '--surface-1', '--surface-2', '--surface-3', '--surface-hover']) {
    const background = luminance(color(surface));
    const ratio = (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
    // WCAG 2.2 SC 1.4.3: small meaningful text requires 4.5:1 without rounding.
    assert.ok(ratio >= 4.5, `${surface}: ${ratio} < 4.5`);
  }
});
