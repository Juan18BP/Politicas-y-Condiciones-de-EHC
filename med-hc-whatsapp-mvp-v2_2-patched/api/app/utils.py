import re, hashlib
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?57)?\s*(3\d{2}|\d{1,3})[\s-]?(\d{3})[\s-]?(\d{4})")
def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256(); h.update(b); return h.hexdigest()
def normalize_phone_colombia(s: str) -> str | None:
    digits = re.sub(r"\D", "", s)
    if len(digits) == 10 and digits.startswith("3"): return "+57" + digits
    if len(digits) == 12 and digits.startswith("57") and digits[2] == "3": return "+" + digits
    if s.startswith("+57") and len(s) == 13: return s
    return None
