import os, re, json, datetime as dt, asyncio
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pdfminer.high_level import extract_text
import httpx
from dotenv import load_dotenv

from .models import UploadPreview, WhatsAppSendReq, TemplateSendReq, TextSendReq
from .utils import sha256_bytes, EMAIL_RE, PHONE_RE, normalize_phone_colombia
from .retention import start_scheduler

load_dotenv()

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/var/app/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PENDING_FILE = UPLOAD_DIR / "pending.json"

RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "7"))
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PNID")
WHATSAPP_TEMPLATE_NAME = os.getenv("WHATSAPP_TEMPLATE_NAME", "hello_world")
WHATSAPP_TEMPLATE_LANG = os.getenv("WHATSAPP_TEMPLATE_LANG", "en_US")
WHATSAPP_API_BASE = "https://graph.facebook.com/v20.0"

app = FastAPI(title="Envio HC por WhatsApp")
app.mount("/ui", StaticFiles(directory=str(Path(__file__).parent / "static"), html=True), name="ui")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

@app.post("/upload_pdf/")
async def upload_pdf(file: UploadFile = File(...)):
    file_path = UPLOAD_DIR / file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"url": f"/uploads/{file.filename}"}

@app.get("/")
def root():
    return RedirectResponse(url="/ui")

def detect_contacts_from_pdf_bytes(pdf_bytes: bytes):
    tmp = UPLOAD_DIR / "tmp_extract.pdf"
    tmp.write_bytes(pdf_bytes)
    try:
        text = extract_text(str(tmp)) or ""
    finally:
        tmp.unlink(missing_ok=True)

    email = None; phone = None; patient_name = None
    emails = EMAIL_RE.findall(text)
    if emails: email = emails[0]
    phones = PHONE_RE.findall(text)
    for p in phones:
        candidate = "".join(p)
        norm = normalize_phone_colombia(candidate)
        if norm: phone = norm; break
    for label in ["Paciente", "Nombre del paciente", "Nombre paciente"]:
        m = re.search(label + r"\s*[:\-]\s*(.+)", text, flags=re.IGNORECASE)
        if m: patient_name = m.group(1).strip().split("\n")[0][:120]; break
    return email, phone, patient_name

@app.post("/api/upload", response_model=UploadPreview)
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se permiten archivos PDF")
    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0 or len(pdf_bytes) > 25 * 1024 * 1024:
        raise HTTPException(400, "PDF vacío o demasiado grande (máx 25MB)")

    digest = sha256_bytes(pdf_bytes)
    file_path = UPLOAD_DIR / f"{digest}.pdf"
    file_path.write_bytes(pdf_bytes)

    email, phone_e164, patient_name = detect_contacts_from_pdf_bytes(pdf_bytes)

    delete_after = (dt.datetime.utcnow() + dt.timedelta(days=RETENTION_DAYS)).isoformat() + "Z"
    meta = {
        "upload_id": digest,
        "file_path": str(file_path),
        "detected_email": email,
        "detected_phone_e164": phone_e164,
        "patient_name": patient_name,
        "delete_after": delete_after,
        "created_at": dt.datetime.utcnow().isoformat() + "Z"
    }
    (UPLOAD_DIR / f"{digest}.json").write_text(json.dumps(meta))

    return UploadPreview(
        upload_id=digest, sha256=digest,
        detected_email=email, detected_phone_e164=phone_e164,
        patient_name=patient_name, delete_after=delete_after
    )

@app.post("/api/send/template")
async def send_template(req: TemplateSendReq):
    to = req.to_phone_e164.strip()
    if not to.startswith("+"):
        n = normalize_phone_colombia(to)
        if not n: raise HTTPException(400, "Número destino inválido; use formato E.164 (+57...)")
        to = n
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        raise HTTPException(500, "Config WhatsApp faltante")
    if not WHATSAPP_TEMPLATE_NAME:
        raise HTTPException(500, "Falta WHATSAPP_TEMPLATE_NAME")

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {"name": WHATSAPP_TEMPLATE_NAME, "language": {"code": WHATSAPP_TEMPLATE_LANG}}
    }
    url = f"{WHATSAPP_API_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 300:
            raise HTTPException(502, f"Error enviando plantilla: {r.text[:400]}")
        return JSONResponse({"ok": True, "wa_response": r.json()})

@app.post("/api/send/text")
async def send_text(req: TextSendReq):
    to = req.to_phone_e164.strip()
    if not to.startswith("+"):
        n = normalize_phone_colombia(to)
        if not n: raise HTTPException(400, "Número destino inválido")
        to = n
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        raise HTTPException(500, "Config WhatsApp faltante")
    url = f"{WHATSAPP_API_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    payload = {"messaging_product":"whatsapp","to":to,"type":"text","text":{"body": req.body[:4096]}}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 300:
            raise HTTPException(502, f"Error enviando texto: {r.text[:400]}")
        return JSONResponse({"ok": True, "wa_response": r.json()})

@app.post("/api/send/whatsapp")
async def send_whatsapp(req: WhatsAppSendReq):
    meta_path = UPLOAD_DIR / f"{req.upload_id}.json"
    pdf_path  = UPLOAD_DIR / f"{req.upload_id}.pdf"
    if not meta_path.exists() or not pdf_path.exists():
        raise HTTPException(404, "upload_id no encontrado o expirado")
    to = req.to_phone_e164.strip()
    if not to.startswith("+"):
        n = normalize_phone_colombia(to)
        if not n: raise HTTPException(400, "Número destino inválido; use formato +57XXXXXXXXXX")
        to = n
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        raise HTTPException(500, "Config WhatsApp faltante")

    media_url = f"{WHATSAPP_API_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {"file": ("historia_clinica.pdf", pdf_path.read_bytes(), "application/pdf"),
                     "messaging_product": (None, "whatsapp")}
            r = await client.post(media_url, headers=headers, files=files)
            if r.status_code >= 300:
                raise HTTPException(502, f"Error subiendo media a WhatsApp: {r.text[:400]}")
            media_id = r.json().get("id")
            await asyncio.sleep(2.0)  # pequeña pausa
            messages_url = f"{WHATSAPP_API_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
            payload = {"messaging_product":"whatsapp","to":to,"type":"document",
                       "document":{"id":media_id,"caption": req.caption or "Documentación clínica","filename":"historia_clinica.pdf"}}
            r2 = await client.post(messages_url, headers=headers, json=payload)
            if r2.status_code >= 300:
                raise HTTPException(502, f"Error enviando WhatsApp: {r2.text[:400]}")
            resp = r2.json()
    except httpx.ReadTimeout:
        raise HTTPException(504, "Tiempo de espera excedido al contactar WhatsApp Cloud API")
    return JSONResponse({"ok": True, "wa_response": resp})

from .retention import start_scheduler
start_scheduler(app)
