"use strict";

for (const button of document.querySelectorAll("[data-copy]")) {
  const code = document.getElementById(button.dataset.copy);
  if (!code || !navigator.clipboard?.writeText) continue;

  button.hidden = false;
  const status = button.closest(".code-panel").querySelector(".copy-status");
  const label = button.textContent;
  let reset;

  button.addEventListener("click", async () => {
    clearTimeout(reset);
    try {
      await navigator.clipboard.writeText(code.textContent.trim());
      button.textContent = "Copied";
      status.textContent = "Build commands copied to the clipboard.";
    } catch {
      button.textContent = "Select to copy";
      status.textContent = "Clipboard access is unavailable. Select the commands to copy them.";
    }
    reset = setTimeout(() => { button.textContent = label; }, 2200);
  });
}

const repositoryUrl = "https://github.com/idy/ch348-macos";
const releasesApi = "https://api.github.com/repos/idy/ch348-macos/releases?per_page=100";

function findPackageRelease(releases) {
  if (!Array.isArray(releases)) return null;
  const published = releases.filter(release => release && !release.draft &&
    typeof release.tag_name === "string" && release.tag_name.length > 0 &&
    typeof release.published_at === "string" &&
    Number.isFinite(Date.parse(release.published_at)) && Array.isArray(release.assets));
  published.sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at));

  for (const release of published) {
    const prefix = `${repositoryUrl}/releases/download/${encodeURIComponent(release.tag_name)}/`;
    const ready = asset => asset && asset.state === "uploaded" &&
      Number.isFinite(asset.size) && asset.size > 0 &&
      asset.browser_download_url === prefix + encodeURIComponent(asset.name);
    const pkg = release.assets.find(asset => ready(asset) &&
      /^CH348-\d+(?:\.\d+){0,2}-build\d+-macos-universal(?:-unsigned)?\.pkg$/.test(asset.name));
    const checksum = release.assets.find(asset => ready(asset) && asset.name === "SHA256SUMS");
    if (pkg && checksum &&
        release.html_url === `${repositoryUrl}/releases/tag/${encodeURIComponent(release.tag_name)}`) {
      return { release, pkg, checksum };
    }
  }
  return null;
}

async function updateReleaseDownloads() {
  if (!document.querySelectorAll("[data-release-download]").length) return;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(releasesApi, {
      headers: { Accept: "application/vnd.github+json" },
      credentials: "omit",
      signal: controller.signal,
    });
    if (!response.ok) return;
    const selected = findPackageRelease(await response.json());
    if (!selected) return;
    const { release, pkg, checksum } = selected;
    const unsigned = pkg.name.endsWith("-unsigned.pkg");
    const text = {
      stage: release.prerelease ? "Development preview" : "Release",
      version: release.tag_name,
      filename: pkg.name,
      size: `${(pkg.size / 1000000).toFixed(1)} MB · Apple Silicon + Intel`,
      "warning-title": unsigned ? "This PKG is unsigned." : "Review signing before activation.",
      "warning-detail": unsigned ? "Distribution signing and notarization are pending." :
        "See the release notes for signing and notarization details.",
      caveat: unsigned ? "Unsigned and not notarized. This preview cannot activate the driver without valid signing." :
        "Read the release notes for signing and activation requirements.",
    };
    for (const [field, value] of Object.entries(text)) {
      for (const node of document.querySelectorAll(`[data-release-${field}]`)) node.textContent = value;
    }
    for (const link of document.querySelectorAll("[data-release-download]")) {
      link.href = pkg.browser_download_url;
      link.textContent = unsigned ? "Download unsigned PKG" : "Download PKG";
    }
    for (const link of document.querySelectorAll("[data-release-notes]")) link.href = release.html_url;
    for (const link of document.querySelectorAll("[data-release-checksum]")) link.href = checksum.browser_download_url;
  } catch {
    // Keep the versioned HTML links usable when GitHub is unavailable or rate-limited.
  } finally {
    clearTimeout(timeout);
  }
}

updateReleaseDownloads();
