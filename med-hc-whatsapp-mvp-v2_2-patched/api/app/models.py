from pydantic import BaseModel
from typing import Optional, Dict, List
class UploadPreview(BaseModel):
    upload_id: str; sha256: str
    detected_email: Optional[str] = None
    detected_phone_e164: Optional[str] = None
    patient_name: Optional[str] = None
    delete_after: str
class WhatsAppSendReq(BaseModel):
    upload_id: str; to_phone_e164: str
    caption: Optional[str] = "Documentación clínica"
class TemplateSendReq(BaseModel):
    to_phone_e164: str
    components: Optional[Dict[str, List[dict]]] = None
class TextSendReq(BaseModel):
    to_phone_e164: str
    body: str
