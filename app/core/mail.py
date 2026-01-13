import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
from dotenv import load_dotenv

load_dotenv()  

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT_STR = os.getenv("SMTP_PORT")
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

if not all([SMTP_SERVER, SMTP_PORT_STR, SMTP_USER, SMTP_PASSWORD]):
    raise ValueError("SMTP configuration is missing in environment variables")

try:
    SMTP_PORT = int(SMTP_PORT_STR)
except ValueError:
    raise ValueError(f"Invalid SMTP_PORT value: {SMTP_PORT_STR}")


def send_email(to_email: str, subject: str, body: str):
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Failed to send email: {e}")
        raise e
