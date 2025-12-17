import os
import base64
import re
from io import BytesIO

from flask import Flask, request, jsonify, render_template_string, send_file
from mistralai import Mistral

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

app = Flask(__name__)

HTML = r"""
<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>قارئ PDF بالـ OCR</title>
  <style>
    :root{
      --bg:#0b0b0b;
      --fg:#eaeaea;
      --muted:#b6b6b6;
      --card:#121212;
      --border:#2a2a2a;
      --accent:#22c55e;
      --accent2:#60a5fa;
    }
    *{box-sizing:border-box}
    body{
      margin:0; min-height:100vh;
      display:flex; align-items:center; justify-content:center;
      background:var(--bg); color:var(--fg);
      font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;
      padding:28px;
    }
    .wrap{width:min(980px, 100%);}
    h1{margin:0 0 10px 0; font-size:26px}
    .sub{color:var(--muted); margin:0 0 18px 0; font-size:13px; line-height:1.7}

    .card{
      background:var(--card);
      border:1px solid var(--border);
      border-radius:18px;
      padding:18px;
      box-shadow:0 10px 30px rgba(0,0,0,.35);
    }
    .row{display:flex; gap:10px; align-items:center; flex-wrap:wrap}
    .spacer{height:14px}

    input[type=file]{
      color:var(--muted);
      background:#0f0f0f;
      border:1px solid var(--border);
      padding:10px 12px;
      border-radius:12px;
      width:min(520px, 100%);
    }

    button{
      border:1px solid var(--border);
      background:#0f0f0f;
      color:var(--fg);
      padding:10px 14px;
      border-radius:12px;
      cursor:pointer;
      transition:transform .06s ease, border-color .12s ease;
      white-space:nowrap;
    }
    button:hover{border-color:#3a3a3a}
    button:active{transform:scale(.98)}
    button:disabled{opacity:.55; cursor:not-allowed}

    .primary{
      background:rgba(34,197,94,.14);
      border-color:rgba(34,197,94,.35);
    }

    .pill{
      font-size:12px;
      color:var(--muted);
      padding:6px 10px;
      border-radius:999px;
      border:1px solid var(--border);
      background:#0f0f0f;
    }

    .panel-title{
      display:flex; align-items:center; justify-content:space-between;
      margin:0 0 10px 0;
    }
    .panel-title h3{margin:0; font-size:15px; color:var(--fg)}
    .panel-title small{color:var(--muted)}

    .out{
      border:1px solid var(--border);
      background:#0f0f0f;
      border-radius:16px;
      padding:14px;
      min-height:240px;
    }

    #outline{
      margin:0; padding-right:18px;
      color:var(--fg);
      line-height:1.75;
    }
    #outline li{margin:4px 0}

    pre{
      margin:0;
      white-space:pre-wrap;
      word-break:break-word;
      color:#d7ffd7;
      font-size:13px;
      line-height:1.6;
    }

    .hidden{display:none !important;}

    /* Progress bar */
    .progress-wrap{
      width:min(520px, 100%);
      padding:10px 12px;
      border:1px solid var(--border);
      background:#0f0f0f;
      border-radius:14px;
    }
    .progress-top{
      display:flex; justify-content:space-between; align-items:center;
      font-size:12px; color:var(--muted);
      margin-bottom:8px;
    }
    .bar{
      height:10px;
      background:#141414;
      border:1px solid var(--border);
      border-radius:999px;
      overflow:hidden;
    }
    .fill{
      height:100%;
      width:0%;
      background:linear-gradient(90deg, rgba(34,197,94,.85), rgba(96,165,250,.85));
      border-radius:999px;
      transition:width .18s ease;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>قارئ PDF بالـ OCR</h1>
    <p class="sub">ارفع ملف PDF ثم اضغط <b>اقرأ</b>. سيتم عرض العناوين اول، وبعدها يمكنك <b>عرض الكل</b> أو التحميل كـ PDF / MD / TXT.</p>

    <div class="card">
      <div class="row">
        <input id="pdf" type="file" accept="application/pdf"/>
        <button id="readBtn" class="primary" disabled>اقرأ</button>
        <span id="status" class="pill">جاهز</span>
      </div>

      <div class="spacer"></div>

      <div id="progressBox" class="progress-wrap hidden" aria-live="polite">
        <div class="progress-top">
          <span id="progressLabel">جاري القرايه</span>
          <span id="progressPct">0%</span>
        </div>
        <div class="bar"><div id="progressFill" class="fill"></div></div>
      </div>

      <div class="spacer"></div>

      <div id="after" class="row hidden">
        <button id="showAllBtn">عرض الكل</button>
        <button id="dlMdBtn">تحميل MD</button>
        <button id="dlTxtBtn">تحميل TXT</button>
        <button id="dlPdfBtn">تحميل PDF</button>
      </div>
    </div>

    <div class="spacer"></div>

    <div class="card">
      <div class="panel-title">
        <h3>الناتج</h3>
        <small id="meta"></small>
      </div>

      <div class="out">
        <div id="outlineView">
          <ol id="outline"></ol>
        </div>
        <div id="fullView" class="hidden">
          <pre id="full"></pre>
        </div>
      </div>
    </div>
  </div>

<script>
let OCR_MD = "";
let SHOW_ALL = false;

const pdf = document.getElementById("pdf");
const readBtn = document.getElementById("readBtn");
const statusEl = document.getElementById("status");
const afterEl = document.getElementById("after");

const outlineEl = document.getElementById("outline");
const fullEl = document.getElementById("full");
const outlineView = document.getElementById("outlineView");
const fullView = document.getElementById("fullView");
const showAllBtn = document.getElementById("showAllBtn");
const metaEl = document.getElementById("meta");

const dlMdBtn = document.getElementById("dlMdBtn");
const dlTxtBtn = document.getElementById("dlTxtBtn");
const dlPdfBtn = document.getElementById("dlPdfBtn");

const progressBox = document.getElementById("progressBox");
const progressFill = document.getElementById("progressFill");
const progressPct = document.getElementById("progressPct");
const progressLabel = document.getElementById("progressLabel");

let progTimer = null;
let progValue = 0;

pdf.onchange = () => {
  readBtn.disabled = !pdf.files.length;
};

function extractHeadings(md){
  const lines = md.split(/\r?\n/);
  const heads = [];
  for (const line of lines){
    const m = line.match(/^(#{1,6})\s+(.*)\s*$/);
    if (m) heads.push({level: m[1].length, text: m[2]});
  }
  return heads;
}

function renderOutline(md){
  const heads = extractHeadings(md);
  outlineEl.innerHTML = "";

  if (!md || md.trim().length === 0){
    outlineEl.innerHTML = "<li>لم يتم استخراج نص.</li>";
    metaEl.textContent = "";
    return;
  }

  if (heads.length === 0){
    outlineEl.innerHTML = "<li>لم يتم العثور على عناوين. استخدم زر <b>عرض الكل</b>.</li>";
  } else {
    for (const h of heads){
      const li = document.createElement("li");
      li.style.marginRight = `${(h.level - 1) * 12}px`;
      li.textContent = h.text;
      outlineEl.appendChild(li);
    }
  }

  const pages = (md.match(/^# Page\s+\d+/gm) || []).length;
  metaEl.textContent = `${pages || "؟"} صفحة • ${heads.length} عنوان`;
}

function setView(showAll){
  SHOW_ALL = showAll;
  if (SHOW_ALL){
    outlineView.classList.add("hidden");
    fullView.classList.remove("hidden");
    showAllBtn.textContent = "عرض العناوين فقط";
  } else {
    fullView.classList.add("hidden");
    outlineView.classList.remove("hidden");
    showAllBtn.textContent = "عرض الكل";
  }
}

function downloadBlob(filename, mime, content){
  const blob = new Blob([content], {type: mime});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function startProgress(){
  progValue = 0;
  progressBox.classList.remove("hidden");
  progressLabel.textContent = "يلا يلا هذاي اقرا الملف ثواني...";
  setProgress(0);

  // Fake-but-clean progress (real OCR time is unknown).
  // Goes to 95% then waits for server response.
  progTimer = setInterval(() => {
    const cap = 95;
    if (progValue >= cap) return;

    // Smooth increments: faster early, slower later
    const remaining = cap - progValue;
    const step = Math.max(1, Math.round(remaining * 0.06));
    progValue = Math.min(cap, progValue + step);
    setProgress(progValue);
  }, 220);
}

function stopProgress(success=true){
  if (progTimer) clearInterval(progTimer);
  progTimer = null;

  if (success){
    setProgress(100);
    progressLabel.textContent = "اكتمل.";
    setTimeout(() => progressBox.classList.add("hidden"), 700);
  } else {
    progressLabel.textContent = "فشل.";
    // keep visible briefly
    setTimeout(() => progressBox.classList.add("hidden"), 1200);
  }
}

function setProgress(p){
  progressFill.style.width = `${p}%`;
  progressPct.textContent = `${p}%`;
}

readBtn.onclick = async () => {
  if (!pdf.files.length) return;

  readBtn.disabled = true;
  afterEl.classList.add("hidden");
  statusEl.textContent = "جاري القراءة…";
  metaEl.textContent = "";
  outlineEl.innerHTML = "";
  fullEl.textContent = "";
  OCR_MD = "";
  setView(false);
  startProgress();

  const fd = new FormData();
  fd.append("pdf", pdf.files[0]);

  try {
    const r = await fetch("/ocr", { method: "POST", body: fd });
    const ct = r.headers.get("content-type") || "";

    if (!ct.includes("application/json")) {
      const txt = await r.text();
      throw new Error("رد غير متوقع من الجماعه:\n" + txt.slice(0, 400));
    }

    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "فشل الطلب");

    OCR_MD = data.markdown || "";
    fullEl.textContent = OCR_MD;
    renderOutline(OCR_MD);

    afterEl.classList.remove("hidden");
    statusEl.textContent = "تم";
    stopProgress(true);
  } catch (e) {
    statusEl.textContent = "خطأ";
    outlineEl.innerHTML = "<li>" + (e.message || String(e)) + "</li>";
    stopProgress(false);
  } finally {
    readBtn.disabled = false;
  }
};

showAllBtn.onclick = () => setView(!SHOW_ALL);

dlMdBtn.onclick = () => {
  if (!OCR_MD) return;
  downloadBlob("ocr.md", "text/markdown;charset=utf-8", OCR_MD);
};

dlTxtBtn.onclick = () => {
  if (!OCR_MD) return;
  const txt = OCR_MD
    .replace(/!\[[^\]]*\]\([^)]+\)/g, "")          // remove images
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");     // remove links
  downloadBlob("ocr.txt", "text/plain;charset=utf-8", txt);
};

dlPdfBtn.onclick = async () => {
  if (!OCR_MD) return;

  statusEl.textContent = "تجهيز PDF…";
  progressBox.classList.remove("hidden");
  progressLabel.textContent = "جاري إنشاء PDF…";
  setProgress(30);

  try {
    const r = await fetch("/pdf", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ markdown: OCR_MD })
    });

    if (!r.ok) {
      const ct = r.headers.get("content-type") || "";
      const msg = ct.includes("application/json") ? (await r.json()).error : await r.text();
      throw new Error(msg || "فشل إنشاء PDF");
    }

    setProgress(80);
    const blob = await r.blob();
    setProgress(100);

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "ocr.pdf";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    statusEl.textContent = "تم";
    progressLabel.textContent = "اكتمل.";
    setTimeout(() => progressBox.classList.add("hidden"), 700);
  } catch (e) {
    statusEl.textContent = "خطأ";
    outlineEl.innerHTML = "<li>" + (e.message || String(e)) + "</li>";
    progressLabel.textContent = "فشل.";
    setTimeout(() => progressBox.classList.add("hidden"), 1200);
  }
};
</script>
</body>
</html>
"""

@app.get("/")
def index():
    return render_template_string(HTML)

@app.post("/ocr")
def ocr():
    try:
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            return jsonify(error="متغير البيئة MISTRAL_API_KEY غير مضبوط"), 500

        if "pdf" not in request.files:
            return jsonify(error="لم يتم رفع ملف"), 400

        f = request.files["pdf"]
        if not f.filename.lower().endswith(".pdf"):
            return jsonify(error="الملف يجب أن يكون PDF"), 400

        pdf_bytes = f.read()
        b64 = base64.b64encode(pdf_bytes).decode("utf-8")

        client = Mistral(api_key=api_key)
        resp = client.ocr.process(
            model="mistral-ocr-latest",
            document={
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{b64}",
            },
            include_image_base64=True,
        )

        pages_md = []
        for i, page in enumerate(resp.pages, start=1):
            pages_md.append(f"\n\n---\n\n# Page {i}\n\n")
            pages_md.append(page.markdown or "")

        return jsonify(markdown="".join(pages_md))

    except Exception as e:
        return jsonify(error=str(e)), 500

def md_to_pdf_bytes(markdown: str) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )

    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=13, spaceAfter=6)
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=16, leading=18, spaceAfter=10)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, leading=15, spaceAfter=8)
    h3 = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=11.5, leading=14, spaceAfter=6)

    story = []

    markdown = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", markdown)  # drop images

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            story.append(Spacer(1, 6))
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            text = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            if level == 1:
                story.append(Paragraph(text, h1))
            elif level == 2:
                story.append(Paragraph(text, h2))
            else:
                story.append(Paragraph(text, h3))
            continue

        text = (line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        story.append(Paragraph(text, body))

    doc.build(story)
    return buf.getvalue()

@app.post("/pdf")
def pdf():
    try:
        data = request.get_json(force=True, silent=False)
        md = (data.get("markdown") or "").strip()
        if not md:
            return jsonify(error="لا يوجد نص لتحويله إلى PDF"), 400

        pdf_bytes = md_to_pdf_bytes(md)
        return send_file(
            BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="ocr.pdf",
        )
    except Exception as e:
        return jsonify(error=str(e)), 500

if __name__ == "__main__":
    app.run(port=5000, debug=True)
