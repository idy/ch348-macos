"use strict";

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const root = join(__dirname, "..");
const read = file => readFileSync(join(root, "docs", file), "utf8");
const repository = "https://github.com/idy/ch348-macos";

function release({ version = "0.1.1", build = 13, published = "2026-11-04T06:53:51Z", prerelease = true, unsigned = true } = {}) {
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
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
const previewFetcher = releases => async url => url.endsWith("/latest") ? response({}, 404) : response(releases);

async function render(fetcher, { languages = ["en"], stored = {}, dark = false, blockedStorage = false, timeoutImmediately = false } = {}) {
  const fields = {};
  for (const field of ["download", "notes", "checksum", "stage", "version", "filename", "size", "warning-title", "warning-detail", "caveat", "status"]) {
    fields[`[data-release-${field}]`] = Array.from({ length: field === "download" ? 2 : 1 },
      () => ({ href: `${repository}/releases`, textContent: "", hidden: false }));
  }
  fields[".download-file"] = [{ hidden: true }];
  const listeners = new Map();
  const events = {};
  const media = { matches: dark, addEventListener: (_, callback) => { events.systemTheme = callback; } };
  const control = () => ({ value: "", addEventListener: (_, callback) => { const handle = callback; return handle; } });
  const languageControl = control();
  const themeControl = control();
  languageControl.addEventListener = (_, callback) => { events.languageControl = callback; };
  themeControl.addEventListener = (_, callback) => { events.themeControl = callback; };
  fields["[data-idy-language]"] = [languageControl];
  fields["[data-idy-theme]"] = [themeControl];
  const star = {
    label: "Star CH348 on GitHub (opens in a new tab)",
    getAttribute(name) { return name === "data-i18n-aria-label" ? "starLabel" : this.label; },
    setAttribute(name, value) { if (name === "aria-label") this.label = value; },
  };
  fields["[data-i18n-aria-label]"] = [star];
  const document = {
    readyState: "loading",
    documentElement: { dataset: {}, style: {}, lang: "en" },
    querySelector: () => null,
    querySelectorAll: selector => fields[selector] || [],
    addEventListener(type, callback) { listeners.set(type, [...(listeners.get(type) || []), callback]); },
    dispatchEvent(event) { for (const callback of listeners.get(event.type) || []) callback(event); },
  };
  const requests = [];
  const deadlines = [];
  const context = {
    document, navigator: { languages }, AbortController,
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
    localStorage: {
      getItem(key) { if (blockedStorage) throw new Error("blocked"); return stored[key]; },
      setItem(key, value) { if (blockedStorage) throw new Error("blocked"); stored[key] = value; },
    },
    matchMedia: () => media,
    addEventListener: (type, callback) => { events[type] = callback; },
    setTimeout(callback, delay) { deadlines.push(delay); return setTimeout(callback, timeoutImmediately ? 0 : delay); },
    clearTimeout,
    fetch(url, options) { requests.push({ url, options }); return fetcher(url, options); },
  };
  context.window = context;
  document.defaultView = context;
  vm.createContext(context);
  vm.runInContext(read("shared/sdk/idy-site.min.js"), context);
  vm.runInContext(read("translations.js"), context);
  await vm.runInContext(read("site.js"), context);
  document.dispatchEvent({ type: "DOMContentLoaded" });
  return {
    fields, context, requests, deadlines, stored, star,
    node: field => fields[`[data-release-${field}]`][0],
    language(value) { context.IdySite.setLanguage(value); },
    theme(value) { context.IdySite.setTheme(value); },
    systemTheme(value) { media.matches = value; events.systemTheme(); },
    load() { events.load(); },
  };
}

function assertSelected(page, selected) {
  for (const link of page.fields["[data-release-download]"]) assert.equal(link.href, selected.assets[0].browser_download_url);
  assert.equal(page.node("version").textContent, selected.tag_name);
  assert.equal(page.node("filename").textContent, selected.assets[0].name);
  assert.equal(page.node("notes").href, selected.html_url);
  assert.equal(page.node("checksum").href, selected.assets[1].browser_download_url);
  assert.equal(page.node("checksum").hidden, false);
}
function assertFallback(page) {
  assert.equal(page.node("download").href, `${repository}/releases`);
  assert.equal(page.node("version").textContent, "GitHub Releases");
  assert.equal(page.node("checksum").hidden, true);
  assert.match(page.node("status").textContent, /unavailable/);
}

test("selects the latest stable release and never constructs download links", async () => {
  const stable = release({ prerelease: false });
  const page = await render(async () => response(stable));
  assertSelected(page, stable);
  assert.equal(page.requests.length, 1);
  assert.equal(page.requests[0].url, "https://api.github.com/repos/idy/ch348-macos/releases/latest");
  assert.equal(page.requests[0].options.credentials, "omit");
  assert.equal(page.node("stage").textContent, "Stable release");
});

test("falls back to the newest published preview when no stable release exists", async () => {
  const preview = release();
  const old = release({ version: "9.0.0", published: "2026-10-01T00:00:00Z" });
  const draft = { ...release({ version: "2.0.0", published: "2026-11-05T00:00:00Z" }), draft: true };
  const page = await render(previewFetcher([old, null, draft, preview]));
  assertSelected(page, preview);
  assert.equal(page.requests.length, 2);
  assert.match(page.requests[1].url, /releases\?per_page=100$/);
  assert.equal(page.node("stage").textContent, "Preview release");
});

test("keeps latest metadata truthful when packages or checksums are missing", async () => {
  for (const assets of [[], [release().assets[0]], [{ ...release().assets[0], state: "new" }, release().assets[1]]]) {
    const current = { ...release(), assets };
    const page = await render(previewFetcher([current]));
    assert.equal(page.node("version").textContent, current.tag_name);
    assert.equal(page.node("download").href, current.html_url);
    assert.equal(page.node("checksum").hidden, true);
    assert.match(page.node("status").textContent, /no complete PKG/);
  }
});

test("rejects asset URLs from a different repository or release tag", async () => {
  for (const url of ["javascript:alert(1)", "https://example.com/pkg", release({ version: "0.0.1" }).assets[0].browser_download_url]) {
    const current = release(); current.assets[0].browser_download_url = url;
    const page = await render(previewFetcher([current]));
    assert.equal(page.node("download").href, current.html_url);
    assert.equal(page.fields[".download-file"][0].hidden, true);
  }
});

test("does not infer signing or notarization from a filename without unsigned", async () => {
  const current = release({ unsigned: false, prerelease: false });
  const page = await render(async () => response(current));
  assertSelected(page, current);
  assert.equal(page.node("download").textContent, "Download PKG");
  assert.equal(page.node("warning-title").textContent, "Review signing before activation.");
});

for (const status of [403, 500]) {
  test(`shows a usable fallback on HTTP ${status}`, async () => {
    const page = await render(async () => response({}, status));
    assertFallback(page); assert.equal(page.requests.length, 1);
  });
}
test("handles empty or malformed release lists and network/JSON failures", async () => {
  for (const body of [[], null, {}, [{ ...release(), published_at: "invalid" }]]) assertFallback(await render(previewFetcher(body)));
  assertFallback(await render(async () => { throw new Error("offline"); }));
  assertFallback(await render(async () => ({ ok: true, json: async () => { throw new SyntaxError("JSON"); } })));
});
test("aborts stalled requests after the shared deadline", async () => {
  let signal;
  const page = await render((url, options) => new Promise((resolve, reject) => {
    signal = options.signal;
    signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
  }), { timeoutImmediately: true });
  assertFallback(page);
  assert.equal(signal.aborted, true);
  assert.deepEqual(page.deadlines, [8000]);
});

test("uses browser language and translates live release details without losing links", async () => {
  const current = release();
  const page = await render(previewFetcher([current]), { languages: ["zh-HK", "en-US"] });
  assert.equal(page.context.document.documentElement.lang, "zh-CN");
  assert.equal(page.node("download").textContent, "下载未签名 PKG");
  page.language("en"); assertSelected(page, current);
  assert.equal(page.node("download").textContent, "Download unsigned PKG");
  assert.equal(page.stored["idy-language"], "en");
  page.language("auto"); assert.equal(page.node("download").textContent, "下载未签名 PKG");
});
test("follows system changes until an explicit theme is chosen", async () => {
  const page = await render(async () => response(release()), { dark: true });
  const element = page.context.document.documentElement;
  assert.equal(element.dataset.theme, "dark");
  page.systemTheme(false); assert.equal(element.dataset.theme, "light");
  page.theme("dark"); page.systemTheme(false); assert.equal(element.dataset.theme, "dark");
  page.theme("system"); assert.equal(element.dataset.theme, "light");
});
test("works without browser storage and honors saved explicit language", async () => {
  const page = await render(async () => response(release()), { blockedStorage: true, languages: ["fr-FR"] });
  assert.equal(page.context.document.documentElement.lang, "en");
  page.language("zh"); page.theme("dark");
  assert.equal(page.context.document.documentElement.lang, "zh-CN");
  assert.equal(page.context.document.documentElement.dataset.theme, "dark");
  const saved = await render(async () => response(release()), { stored: { "idy-language": "en", "idy-theme": "light" }, languages: ["zh-CN"], dark: true });
  assert.equal(saved.context.document.documentElement.lang, "en");
  assert.equal(saved.context.document.documentElement.dataset.theme, "light");
});
test("shared SDK finishes early preference initialization before load", async () => {
  const page = await render(async () => response(release()));
  assert.equal(page.context.document.documentElement.dataset.idyHeaderPending, undefined);
  page.load();
  assert.equal(page.context.document.documentElement.dataset.idyHeaderPending, undefined);
});

test("header preserves desktop and mobile navigation and bilingual accessible labels", async () => {
  const html = read("index.html");
  const header = html.match(/<header class="idy-header compact-header">([\s\S]*?)<\/header>/)[1];
  const navigation = [...header.matchAll(/<nav class="idy-(?:nav|mobile-panel)"[^>]*>([\s\S]*?)<\/nav>/g)];
  const links = nav => [...nav[1].matchAll(/<a\b([^>]*)>([^<]*)<\/a>/g)].map(match => {
    const attrs = Object.fromEntries([...match[1].matchAll(/([\w:-]+)="([^"]*)"/g)].map(attr => [attr[1], attr[2]]));
    return [attrs.href, match[2], attrs["data-i18n"] || null];
  });
  assert.equal(navigation.length, 2);
  assert.deepEqual(links(navigation[0]), links(navigation[1]));
  assert.deepEqual(links(navigation[0]), [
    ["#download", "Downloads", "downloads"],
    ["https://github.com/idy/ch348-macos/blob/main/README.md", "Docs", "docs"],
    [repository, "GitHub", null], ["https://idy.dev/", "idy.dev", null],
  ]);
  assert.match(header, /<a class="idy-home" href="#main">CH348<\/a>/);
  assert.match(header, /<details class="idy-mobile">\s*<summary aria-label="Main navigation" data-i18n-aria-label="navigation">/);
  assert.match(header, /<select data-idy-language>/);
  assert.match(header, /<select data-idy-theme>/);
  const action = Object.fromEntries([...header.match(/<a class="idy-action"([^>]*)>/)[1]
    .matchAll(/([\w:-]+)="([^"]*)"/g)].map(attr => [attr[1], attr[2]]));
  assert.equal(action.href, repository);
  assert.equal(action.target, "_blank");
  assert.match(action.rel, /noopener/);
  assert.equal(action["aria-label"], "Star CH348 on GitHub (opens in a new tab)");
  assert.equal(action["data-i18n-aria-label"], "starLabel");
  assert.match(header, /<i class="ph ph-star" aria-hidden="true"><\/i><span>star<\/span>/);
  const page = await render(async () => response(release()));
  assert.equal(page.star.getAttribute("aria-label"), action["aria-label"]);
  page.language("zh");
  assert.match(page.star.getAttribute("aria-label"), /^star\b.*GitHub.*CH348.*新标签页/);
  page.language("en");
  assert.equal(page.star.getAttribute("aria-label"), action["aria-label"]);
});

test("enhanced preferences support keyboard selection and restore focus", () => {
  let document;
  class Element {
    constructor() {
      this.children = []; this.listeners = new Map(); this.attributes = {}; this.dataset = {};
      this.classList = { add() {} }; this.style = {};
    }
    addEventListener(type, listener) {
      this.listeners.set(type, [...(this.listeners.get(type) || []), listener]);
    }
    dispatchEvent(event) {
      event.target ||= this;
      for (const listener of this.listeners.get(event.type) || []) listener(event);
      if (event.bubbles && this !== document) document.dispatchEvent(event);
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] ?? null; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    focus() { document.activeElement = this; }
    contains(node) { return this === node || this.children.some(child => child.contains(node)); }
    getBoundingClientRect() { return { left: 100, right: 280 }; }
  }
  const select = (values, selected) => {
    const node = new Element();
    node.options = values.map(([value, textContent]) => ({ value, textContent }));
    node.value = selected;
    Object.defineProperty(node, "selectedIndex", { get: () => node.options.findIndex(option => option.value === node.value) });
    return node;
  };
  const theme = select([["system", "System"], ["light", "Light"], ["dark", "Dark"]], "system");
  const language = select([["auto", "Auto"], ["en", "English"], ["zh", "中文"]], "auto");
  const native = new Element();
  native.querySelector = selector => selector === "select[data-idy-theme]" ? theme : language;
  native.after = element => { native.next = element; };
  const summary = new Element();
  const mobile = new Element();
  mobile.querySelector = () => summary;
  const header = new Element();
  header.querySelector = selector => selector === ".idy-preferences" ? native : mobile;
  document = new Element();
  document.readyState = "loading";
  document.documentElement = { dataset: {}, style: {}, lang: "en" };
  document.createElement = () => new Element();
  document.getElementById = () => null;
  document.querySelector = selector => selector === ".compact-header .idy-mobile[open]" && mobile.open ? mobile : null;
  document.querySelectorAll = selector => {
    if (selector === ".compact-header") return [header];
    if (selector === ".compact-header .idy-mobile[open]") return mobile.open ? [mobile] : [];
    if (selector === "select[data-idy-theme]") return [theme];
    if (selector === "select[data-idy-language]") return [language];
    return [];
  };
  const media = new Element();
  media.matches = false;
  const window = new Element();
  window.document = document;
  window.navigator = { languages: ["en"] };
  window.localStorage = { getItem: () => null, setItem() {} };
  window.matchMedia = () => media;
  window.innerWidth = 1000;
  window.Event = class { constructor(type, options) { this.type = type; this.bubbles = options?.bubbles; } };
  window.CustomEvent = class { constructor(type, options) { this.type = type; this.detail = options?.detail; } };
  document.defaultView = window;
  const context = { document, window, AbortController, setTimeout, clearTimeout };
  vm.runInNewContext(read("shared/sdk/idy-site.min.js"), context);
  document.dispatchEvent({ type: "DOMContentLoaded" });

  assert.equal(native.hidden, true);
  assert.equal(document.documentElement.dataset.idyHeaderPending, undefined);
  const [themeRoot, languageRoot] = native.next.children;
  const [themeTrigger, themeMenu] = themeRoot.children;
  const [languageTrigger, languageMenu] = languageRoot.children;
  assert.equal(themeTrigger.getAttribute("aria-label"), "Theme: System");
  assert.equal(themeMenu.getAttribute("role"), "menu");
  assert.equal(themeMenu.children[0].getAttribute("role"), "menuitemradio");
  const key = value => ({ type: "keydown", key: value, preventDefault() {} });
  themeTrigger.dispatchEvent(key("ArrowDown"));
  assert.equal(themeMenu.hidden, false);
  assert.equal(document.activeElement, themeMenu.children[0]);
  themeMenu.dispatchEvent(key("ArrowDown"));
  assert.equal(document.activeElement, themeMenu.children[1]);
  themeMenu.children[1].dispatchEvent({ type: "click" });
  assert.equal(theme.value, "light");
  assert.equal(themeMenu.children[1].getAttribute("aria-checked"), "true");
  assert.equal(themeMenu.hidden, true);
  assert.equal(document.activeElement, themeTrigger);

  languageTrigger.dispatchEvent({ type: "click" });
  assert.equal(languageMenu.hidden, false);
  // Safari can blur the focused option with no related target before a tap's click.
  languageRoot.dispatchEvent({ type: "focusout", relatedTarget: null });
  assert.equal(languageMenu.hidden, false);
  languageMenu.children[2].dispatchEvent({ type: "click" });
  assert.equal(language.value, "zh");
  assert.equal(languageMenu.hidden, true);
  assert.equal(document.activeElement, languageTrigger);

  languageTrigger.dispatchEvent({ type: "click" });
  languageRoot.dispatchEvent({ type: "focusout", relatedTarget: themeTrigger });
  assert.equal(languageMenu.hidden, true);
  languageTrigger.dispatchEvent({ type: "click" });
  window.dispatchEvent({ type: "blur" });
  assert.equal(languageMenu.hidden, true);
  languageTrigger.dispatchEvent({ type: "click" });
  document.dispatchEvent(key("Escape"));
  assert.equal(languageMenu.hidden, true);
  assert.equal(document.activeElement, languageTrigger);
  mobile.open = true;
  themeTrigger.dispatchEvent({ type: "click" });
  assert.equal(mobile.open, false);
  document.dispatchEvent(key("Escape"));
  mobile.open = true;
  document.dispatchEvent(key("Escape"));
  assert.equal(mobile.open, false);
  assert.equal(document.activeElement, summary);
  language.value = "auto";
  language.options[0].textContent = "自动";
  window.IdySite.init({ en: { language: "语言" } });
  assert.equal(languageTrigger.getAttribute("aria-label"), "语言: 自动");
});

test("static HTML has no pinned latest release and retains historical validation context", () => {
  const html = read("index.html");
  assert.doesNotMatch(html, /https:\/\/github\.com\/idy\/ch348-macos\/releases\/(download|tag)\//);
  assert.match(html, /Hardware smoke tests were recorded with/);
  assert.equal((html.match(/data-release-download/g) || []).length, 2);
  assert.match(html, /shared\/sdk\/idy-site\.min\.js/);
});
