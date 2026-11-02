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
