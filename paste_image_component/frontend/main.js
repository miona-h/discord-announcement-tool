const MAX_SIDE = 1200;
let initialized = false;
let parentDoc = null;

const zone = () => document.getElementById("dropzone");

function setMessage(html, state) {
  document.getElementById("message").innerHTML = html;
  zone().classList.remove("done", "error");
  if (state) zone().classList.add(state);
}

function imageFileFrom(dataTransfer) {
  if (!dataTransfer) return null;
  for (const item of dataTransfer.items || []) {
    if (item.kind === "file" && item.type.startsWith("image/")) return item.getAsFile();
  }
  for (const file of dataTransfer.files || []) {
    if (file.type.startsWith("image/")) return file;
  }
  return null;
}

// 大きな画像はブラウザ側で長辺1200pxへ縮小してから送る（透過は保持）。
function toPngBase64(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, MAX_SIDE / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(img.width * scale));
      canvas.height = Math.max(1, Math.round(img.height * scale));
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL("image/png"));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("画像を読み込めませんでした"));
    };
    img.src = url;
  });
}

async function handleFile(file) {
  if (!file) return false;
  setMessage("<strong>⏳ 読み込み中…</strong>");
  try {
    const dataUrl = await toPngBase64(file);
    const preview = document.getElementById("preview");
    preview.src = dataUrl;
    preview.classList.add("show");
    setMessage("<strong>✅ 貼り付けました</strong><br /><span>続けて別の画像を貼り付けることもできます。</span>", "done");
    const baseName = (file.name && file.name !== "image.png") ? file.name.replace(/\.[^.]+$/, "") : "pasted";
    Streamlit.setComponentValue({
      data: dataUrl.split(",", 2)[1],
      name: `${baseName}_${new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14)}.png`,
      nonce: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    });
  } catch (err) {
    setMessage(`<strong>⚠️ ${err.message}</strong><br /><span>PNG・JPG・WEBPの画像をコピーしてください。</span>`, "error");
  }
  return true;
}

function onPaste(event) {
  const file = imageFileFrom(event.clipboardData);
  if (!file) {
    // ボックス内に文字が入らないようにし、画像が無いことを知らせる。
    if (zone().contains(event.target)) {
      event.preventDefault();
      setMessage("<strong>⚠️ クリップボードに画像がありません</strong><br /><span>画像を右クリック →「画像をコピー」してから貼り付けてください。</span>", "error");
    }
    return;
  }
  event.preventDefault();
  handleFile(file);
}

function onParentPaste(event) {
  // 文字入力欄への貼り付けは通常どおりにする。
  const target = event.target;
  const tag = (target && target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || (target && target.isContentEditable)) return;
  if (!imageFileFrom(event.clipboardData)) return;
  onPaste(event);
}

function init() {
  const dz = zone();
  document.addEventListener("paste", onPaste);
  dz.addEventListener("keydown", e => {
    // 貼り付けショートカット以外のキー入力は無効化
    if (!(e.ctrlKey || e.metaKey) && e.key.length === 1) e.preventDefault();
  });
  dz.addEventListener("beforeinput", e => {
    if (e.inputType !== "insertFromPaste") e.preventDefault();
  });
  dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("dragover"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
  dz.addEventListener("drop", e => {
    e.preventDefault();
    dz.classList.remove("dragover");
    handleFile(imageFileFrom(e.dataTransfer));
  });

  // 画面のどこかで ⌘V / Ctrl+V しても受け取れるよう、親ページにも登録する（同一オリジン時のみ）。
  try {
    parentDoc = window.parent && window.parent.document;
    if (parentDoc) {
      parentDoc.addEventListener("paste", onParentPaste);
      window.addEventListener("pagehide", () => parentDoc.removeEventListener("paste", onParentPaste));
    }
  } catch (_) {
    parentDoc = null;
  }
}

Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, event => {
  const args = event.detail.args;
  const theme = event.detail.theme || {};
  for (const [name, value] of Object.entries({
    "--primary": theme.primaryColor, "--secondary": theme.secondaryBackgroundColor,
    "--text": theme.textColor, "--font": theme.font,
  })) {
    if (value) document.documentElement.style.setProperty(name, value);
  }
  document.getElementById("label").textContent = args.label || "";
  if (!initialized) {
    init();
    initialized = true;
  }
  Streamlit.setFrameHeight(Number(args.height || 120));
});

Streamlit.setComponentReady();
