let renderId = 0;

function send(action, event, path) {
  const image = document.getElementById("calendar");
  const rect = image.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  Streamlit.setComponentValue({
    action,
    path: path || "",
    x: (event.clientX - rect.left) * (1080 / rect.width),
    y: (event.clientY - rect.top) * (1920 / rect.height),
    nonce: `${Date.now()}-${Math.random()}`,
  });
}

Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, event => {
  const args = event.detail.args || {};
  const library = document.getElementById("library");
  const image = document.getElementById("calendar");
  const stage = document.getElementById("stage");
  const width = Number(args.width || 700);
  stage.style.width = `${width}px`;
  image.style.width = `${width}px`;
  if (image.src !== args.calendar_src) image.src = args.calendar_src || "";

  library.replaceChildren();
  (args.assets || []).forEach(asset => {
    const item = document.createElement("div");
    item.className = "asset";
    item.draggable = true;
    item.title = asset.label || "画像";
    item.dataset.path = asset.path;
    const thumb = document.createElement("img");
    thumb.src = asset.src;
    thumb.alt = asset.label || "画像";
    item.appendChild(thumb);
    item.addEventListener("dragstart", e => {
      e.dataTransfer.setData("text/plain", asset.path);
      e.dataTransfer.effectAllowed = "copy";
      item.classList.add("dragging");
    });
    item.addEventListener("dragend", () => item.classList.remove("dragging"));
    library.appendChild(item);
  });

  if (!renderId) {
    image.addEventListener("click", e => send("click", e, ""));
    stage.addEventListener("dragover", e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      stage.classList.add("over");
    });
    stage.addEventListener("dragleave", () => stage.classList.remove("over"));
    stage.addEventListener("drop", e => {
      e.preventDefault();
      stage.classList.remove("over");
      send("drop", e, e.dataTransfer.getData("text/plain"));
    });
    image.addEventListener("load", () => Streamlit.setFrameHeight(document.body.scrollHeight + 4));
  }
  renderId += 1;
  requestAnimationFrame(() => Streamlit.setFrameHeight(document.body.scrollHeight + 4));
});

Streamlit.setComponentReady();
