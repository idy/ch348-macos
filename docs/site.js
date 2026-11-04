"use strict";

const { t } = IdySite;
for (const button of document.querySelectorAll("[data-copy]")) {
  const code = document.getElementById(button.dataset.copy);
  if (!code || !navigator.clipboard?.writeText) continue;
  button.hidden = false;
  const status = button.closest(".code-panel").querySelector(".copy-status");
  let feedback;
  let reset;
  const renderCopy = () => {
    button.textContent = t(feedback ? (feedback === "copySuccess" ? "copied" : "selectToCopy") : "copyCommands");
    status.textContent = feedback ? t(feedback) : "";
  };
  document.addEventListener("idy:languagechange", renderCopy);
  button.addEventListener("click", async () => {
    clearTimeout(reset);
    try {
      await navigator.clipboard.writeText(code.textContent.trim());
      feedback = "copySuccess";
    } catch {
      feedback = "copyFailure";
    }
    renderCopy();
    reset = setTimeout(() => { feedback = undefined; renderCopy(); }, 2200);
  });
}

let currentRelease;
let releaseFailed = false;
function renderRelease() {
  const pkg = currentRelease && IdySite.asset(currentRelease, /^CH348-\d+(?:\.\d+){0,2}-build\d+-macos-universal(?:-unsigned)?\.pkg$/);
  const checksum = currentRelease && IdySite.asset(currentRelease, /^SHA256SUMS$/);
  const complete = Boolean(pkg && checksum);
  const unsigned = complete && pkg.name.endsWith("-unsigned.pkg");
  const text = {
    stage: currentRelease ? t(currentRelease.prerelease ? "previewRelease" : "stableRelease") : t("developmentBuilds"),
    version: currentRelease?.tag_name || "GitHub Releases",
    filename: complete ? pkg.name : "",
    size: complete ? `${(pkg.size / 1000000).toFixed(1)} MB · ${t("packagePlatforms")}` : "",
    "warning-title": t(unsigned ? "unsignedTitle" : "signingTitle"),
    "warning-detail": t(unsigned ? "unsignedDetail" : "signingDetail"),
    caveat: t(unsigned ? "unsignedCaveat" : "signingCaveat"),
    status: t(releaseFailed ? "releaseUnavailable" : currentRelease ? (complete ? "releaseReady" : "packageMissing") : "loadingRelease"),
  };
  for (const [field, value] of Object.entries(text)) {
    for (const node of document.querySelectorAll(`[data-release-${field}]`)) node.textContent = value;
  }
  const releaseUrl = currentRelease?.html_url || "https://github.com/idy/ch348-macos/releases";
  for (const link of document.querySelectorAll("[data-release-download]")) {
    link.href = complete ? pkg.browser_download_url : releaseUrl;
    link.textContent = t(complete ? (unsigned ? "downloadUnsigned" : "downloadPackage") : "browseReleases");
  }
  for (const link of document.querySelectorAll("[data-release-notes]")) link.href = releaseUrl;
  for (const link of document.querySelectorAll("[data-release-checksum]")) {
    link.href = complete ? checksum.browser_download_url : releaseUrl;
    link.hidden = !complete;
  }
  for (const node of document.querySelectorAll(".download-file")) node.hidden = !complete;
}

document.addEventListener("idy:languagechange", renderRelease);
renderRelease();
IdySite.loadRelease("idy/ch348-macos").then(release => {
  currentRelease = release;
}).catch(() => {
  releaseFailed = true;
}).finally(renderRelease);
