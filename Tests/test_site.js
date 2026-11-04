"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = join(__dirname, "..");
const source = readFileSync(join(root, "docs/site.js"), "utf8");
const repository = "https://github.com/idy/ch348-macos";

function release({ version = "0.1.1", build = 13,
  published = "2026-11-04T06:53:51Z", prerelease = true, unsigned = true } = {}) {
  const tag = prerelease ? `v${version}-dev.${build}-pkg.1` : `v${version}`;
  const prefix = `${repository}/releases/download/${tag}/`;
  const name = `CH348-${version}-build${build}-macos-universal${unsigned ? "-unsigned" : ""}.pkg`;
  return {
    tag_name: tag, published_at: published, prerelease, draft: false,
    html_url: `${repository}/releases/tag/${tag}`,
    assets: [
      { name, size: 1431257, state: "uploaded", browser_download_url: prefix + name },
      { name: "SHA256SUMS", size: 115, state: "uploaded", browser_download_url: prefix + "SHA256SUMS" },
    ],
  };
}

const response = releases => ({ ok: true, json: async () => releases });

async function render(fetcher, { timeoutImmediately = false } = {}) {
  const fields = {};
  for (const field of ["download", "notes", "checksum", "stage", "version", "filename", "size",
    "warning-title", "warning-detail", "caveat"]) {
    fields[`[data-release-${field}]`] = Array.from({ length: field === "download" ? 2 : 1 },
      () => ({ href: "fallback-link", textContent: "fallback-text" }));
  }
  const original = JSON.stringify(fields);
  const requests = [];
  const deadlines = [];
  await vm.runInNewContext(source, {
    document: { querySelectorAll: selector => fields[selector] || [] },
    navigator: {}, AbortController,
    setTimeout: (callback, delay) => {
      deadlines.push(delay);
      return setTimeout(callback, timeoutImmediately ? 0 : delay);
    },
    clearTimeout,
    fetch: (url, options) => { requests.push({ url, options }); return fetcher(url, options); },
  });
  return {
    fields, original, requests, deadlines,
    node: field => fields[`[data-release-${field}]`][0],
  };
}

function assertSelected(page, selected) {
  for (const link of page.fields["[data-release-download]"])
    assert.equal(link.href, selected.assets[0].browser_download_url);
  assert.equal(page.node("version").textContent, selected.tag_name);
  assert.equal(page.node("filename").textContent, selected.assets[0].name);
  assert.equal(page.node("size").textContent, "1.4 MB · Apple Silicon + Intel");
  assert.equal(page.node("notes").href, selected.html_url);
  assert.equal(page.node("checksum").href, selected.assets[1].browser_download_url);
}

function assertFallback(page) {
  assert.equal(JSON.stringify(page.fields), page.original);
  assert.equal(page.requests.length, 1);
}

test("uses the public releases list and includes the newest prerelease", async () => {
  const preview = release();
  const stable = release({ version: "0.1.0", build: 12, prerelease: false, published: "2026-11-02T00:00:00Z" });
  const page = await render(async () => response([stable, preview]));
  assertSelected(page, preview);
  assert.equal(page.requests.length, 1);
  assert.equal(page.requests[0].url, "https://api.github.com/repos/idy/ch348-macos/releases?per_page=100");
  assert.equal(page.requests[0].options.credentials, "omit");
  assert.equal(page.node("stage").textContent, "Development preview");
  assert.equal(page.node("download").textContent, "Download unsigned PKG");
});

test("ignores drafts, source-only releases, and unfinished uploads", async () => {
  const selected = release();
  const draft = { ...release({ version: "0.2.0", build: 14, published: "2026-11-05T00:00:00Z" }), draft: true };
  const sourceOnly = release({ version: "0.3.0", build: 15, published: "2026-11-06T00:00:00Z" });
  sourceOnly.assets[0].name = "source.zip";
  const pending = release({ version: "0.4.0", build: 16, published: "2026-11-07T00:00:00Z" });
  pending.assets[0].state = "new";
  const page = await render(async () => response([draft, sourceOnly, pending, selected]));
  assertSelected(page, selected);
});

test("selects by publication time rather than array order or version number", async () => {
  const newer = release();
  const older = release({ version: "9.0.0", build: 99, published: "2026-10-01T00:00:00Z" });
  const page = await render(async () => response([older, newer]));
  assertSelected(page, newer);
});

test("keeps package, checksum, and notes on the same complete release", async () => {
  const complete = release();
  const incomplete = release({ version: "0.2.0", build: 14, published: "2026-11-05T00:00:00Z" });
  incomplete.assets.pop();
  assertSelected(await render(async () => response([incomplete, complete])), complete);
});

test("does not label a package without the unsigned suffix as signed or notarized", async () => {
  const stable = release({ version: "0.2.0", build: 14, prerelease: false, unsigned: false });
  const page = await render(async () => response([stable]));
  assertSelected(page, stable);
  assert.equal(page.node("stage").textContent, "Release");
  assert.equal(page.node("download").textContent, "Download PKG");
  assert.match(page.node("warning-detail").textContent, /release notes/);
  assert.doesNotMatch(page.node("caveat").textContent, /is signed|is notarized/i);
});

test("rejects download URLs outside the selected repository and tag", async () => {
  const valid = release();
  for (const url of ["javascript:alert(1)", "https://example.com/pkg", valid.assets[0].browser_download_url]) {
    const wrong = release({ version: "0.2.0", build: 14, published: "2026-11-05T00:00:00Z" });
    wrong.assets[0].browser_download_url = url;
    assertSelected(await render(async () => response([wrong, valid])), valid);
  }
});

test("skips malformed release entries without losing the valid package", async () => {
  const valid = release();
  const malformed = [null, {}, { published_at: "invalid", assets: [] }, { ...valid, assets: null }];
  assertSelected(await render(async () => response([...malformed, valid])), valid);
});

for (const status of [403, 404, 500]) {
  test(`preserves the complete static fallback on HTTP ${status}`, async () => {
    assertFallback(await render(async () => ({ ok: false, status })));
  });
}

test("preserves fallback links when the network or JSON decoding fails", async () => {
  assertFallback(await render(async () => { throw new Error("offline"); }));
  assertFallback(await render(async () => ({ ok: true, json: async () => { throw new SyntaxError("invalid JSON"); } })));
});

test("preserves fallback links for empty, unavailable, or malformed release lists", async () => {
  for (const body of [[], null, {}, { message: "rate limited" }, [release({ published: "invalid" })]])
    assertFallback(await render(async () => response(body)));
});

test("bounds a stalled request with an abort timeout", async () => {
  let signal;
  const page = await render((url, options) => new Promise((resolve, reject) => {
    signal = options.signal;
    signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
  }), { timeoutImmediately: true });
  assertFallback(page);
  assert.equal(signal.aborted, true);
  assert.deepEqual(page.deadlines, [5000]);
});

test("HTML fallback serves build 13 and exposes every metadata update target", () => {
  const html = readFileSync(join(root, "docs/index.html"), "utf8");
  const downloads = [...html.matchAll(/<a\b([^>]*)>/g)]
    .filter(match => match[1].includes("data-release-download"));
  assert.equal(downloads.length, 2);
  for (const match of downloads)
    assert.match(match[1], /href="https:\/\/github\.com\/idy\/ch348-macos\/releases\/download\/v0\.1\.1-dev\.13-pkg\.1\/CH348-0\.1\.1-build13-macos-universal-unsigned\.pkg"/);
  for (const field of ["notes", "checksum", "stage", "version", "filename", "size", "warning-title", "warning-detail", "caveat"])
    assert.ok(html.includes(`data-release-${field}`), `Missing release ${field} binding`);
  assert.match(html, /Hardware smoke tests were recorded with/);
});
