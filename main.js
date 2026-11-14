let initialized = false;
let timer = null;

Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, event => {
  const args = event.detail.args;
  const editor = document.getElementById("editor");
  const label = document.getElementById("label");
  const frameHeight = Number(args.height || 220) + 38;

  document.documentElement.style.setProperty("--primary", event.detail.theme.primaryColor);
  document.documentElement.style.setProperty("--background", event.detail.theme.backgroundColor);
  document.documentElement.style.setProperty("--secondary", event.detail.theme.secondaryBackgroundColor);
  document.documentElement.style.setProperty("--text", event.detail.theme.textColor);
  document.documentElement.style.setProperty("--font", event.detail.theme.font);
  label.textContent = args.label || "";
  editor.style.height = `${Number(args.height || 220)}px`;

  if (!initialized) {
    editor.value = args.value || "";
    editor.addEventListener("input", () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(
        () => Streamlit.setComponentValue(editor.value),
        Number(args.debounce || 300)
      );
    });
    initialized = true;
  }
  Streamlit.setFrameHeight(frameHeight);
});

Streamlit.setComponentReady();
