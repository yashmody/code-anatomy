"""Email service.

In DEV_MODE, writes each email (with attachments) to ./outbox/ as a .eml file.
In production, uses configured SMTP.

The PDF certificate is sent as an attachment.
"""
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict

from app.core import config


def _build_message(to_email: str, to_name: str, record: Dict, cert_path: Path) -> MIMEMultipart:
    cert_id = record["cert_id"]
    score_pct = int(round(record["score"] * 100))
    difficulty = record["difficulty"].capitalize()

    msg = MIMEMultipart()
    msg["From"] = f"{config.FROM_NAME} <{config.FROM_EMAIL}>"
    msg["To"] = f"{to_name} <{to_email}>"
    msg["Subject"] = f"Your DEPT® Academy certificate · {cert_id}"

    body = f"""Hi {to_name},

Congratulations — you've passed The Anatomy of Code · CCA-F at the {difficulty}
level with a score of {score_pct}%.

Your certificate is attached.

A few ways to use it:
  · Add the PDF to your LinkedIn profile (Licenses & Certifications section).
  · Share it on your team channel.
  · Keep it for your CV.

Certificate ID: {cert_id}
Issued: {datetime.utcnow().strftime("%d %B %Y")}

Anyone can verify the ID against your record. The certificate is digitally
recorded in our system.

— DEPT® Academy
"""
    msg.attach(MIMEText(body, "plain"))

    # Attach PDF
    with open(cert_path, "rb") as f:
        part = MIMEBase("application", "pdf")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f'attachment; filename="{cert_id}.pdf"',
    )
    msg.attach(part)

    return msg


def send_certificate(to_email: str, to_name: str, record: Dict, cert_path: Path) -> Path:
    """Send the certificate email.

    Returns the path of the file written (in dev) or the outbox entry recorded.
    """
    msg = _build_message(to_email, to_name, record, cert_path)

    if config.DEV_MODE:
        # Write to outbox as a .eml file
        date = datetime.utcnow().strftime("%Y-%m-%dT%H%M%S")
        safe = to_email.replace("@", "_at_").replace(".", "_")
        eml_path = config.OUTBOX_DIR / f"{date}_{safe}.eml"
        with open(eml_path, "w", encoding="utf-8") as f:
            f.write(msg.as_string())
        return eml_path

    # Real SMTP
    if not config.SMTP_HOST:
        raise RuntimeError("SMTP_HOST not configured; set DEV_MODE=true for local testing")

    server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
    try:
        server.ehlo()
        if config.SMTP_USE_TLS:
            server.starttls()
            server.ehlo()
        if config.SMTP_USER and config.SMTP_PASS:
            server.login(config.SMTP_USER, config.SMTP_PASS)
        server.sendmail(config.FROM_EMAIL, [to_email], msg.as_string())
    finally:
        server.quit()

    return cert_path
