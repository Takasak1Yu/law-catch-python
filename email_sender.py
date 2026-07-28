import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formatdate
from urllib.parse import quote
import os


class EmailSender:
    def __init__(self, config: dict):
        self.smtp_server = config["smtp_server"]
        self.smtp_port = config["smtp_port"]
        self.sender = config["sender"]
        self.password = config["password"]
        receivers = config.get("receivers", [])
        if isinstance(receivers, str):
            receivers = [r.strip() for r in receivers.split(",") if r.strip()]
        self.receivers = receivers

    def send(self, subject: str, body: str, attachments: list[str] = None):
        msg = MIMEMultipart()
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.receivers)
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)

        msg.attach(MIMEText(body, "plain", "utf-8"))

        if attachments:
            for filepath in attachments:
                if filepath and os.path.exists(filepath):
                    with open(filepath, "rb") as f:
                        part = MIMEBase(
                            "application",
                            "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    filename = os.path.basename(filepath)
                    encoded_filename = quote(filename)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename=\"{encoded_filename}\"; filename*=UTF-8''{encoded_filename}",
                    )
                    part.add_header("Content-Type", "application/octet-stream", name=encoded_filename)
                    msg.attach(part)

        with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as server:
            server.login(self.sender, self.password)
            for receiver in self.receivers:
                server.sendmail(self.sender, receiver, msg.as_string())
