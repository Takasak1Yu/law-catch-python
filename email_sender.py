import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


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

    def send(self, subject: str, body: str):
        msg = MIMEMultipart()
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.receivers)
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as server:
            server.login(self.sender, self.password)
            for receiver in self.receivers:
                server.sendmail(self.sender, receiver, msg.as_string())
