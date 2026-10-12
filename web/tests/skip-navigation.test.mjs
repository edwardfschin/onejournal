import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

test('every private workspace template has a matching keyboard skip target', () => {
  // Trades/Journal share one template; Portfolio's canonical route re-exports
  // its existing template. Today/Data/Settings share the overview template.
  for (const path of [
    '../app/local/reports/page.tsx', '../app/portfolio/local/page.tsx',
    '../app/journal/local/page.tsx', '../components/local-workspace-overview.tsx',
  ]) {
    const source = readFileSync(new URL(path, import.meta.url), 'utf8');
    const link = /<a className="workspace-skip-link" href="#workspace-content">Skip to content<\/a>/;
    assert.match(source, link, path);
    assert.match(source, /<div className="content-frame" id="workspace-content" tabIndex=\{-1\}>/, path);
    assert.equal((source.match(/id="workspace-content"/g) ?? []).length, 1, path);
    assert.ok(source.search(link) < source.indexOf('<section className="workspace">'), path);
  }
});

test('journal search can shrink beside the mobile menu and search action', () => {
  const css = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');
  assert.match(css, /\.local-journal-route \.search-box\s*\{\s*min-width:\s*0\s*;\s*\}/);
});
