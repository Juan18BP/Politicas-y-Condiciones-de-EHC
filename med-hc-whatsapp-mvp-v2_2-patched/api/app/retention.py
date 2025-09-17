import os, json, datetime as dt
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/var/app/uploads"))
def retention_job():
    now = dt.datetime.utcnow()
    for meta_file in UPLOAD_DIR.glob("*.json"):
        try:
            meta = json.loads(meta_file.read_text())
            delete_after = dt.datetime.fromisoformat(meta["delete_after"].replace("Z",""))
            if now >= delete_after:
                Path(meta["file_path"]).unlink(missing_ok=True)
                meta_file.unlink(missing_ok=True)
        except Exception:
            pass
def start_scheduler(app):
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(retention_job, "cron", hour=3, minute=15)
    scheduler.start()
    @app.on_event("shutdown")
    def shutdown(): scheduler.shutdown()
