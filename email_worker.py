import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import streamlit as st
import os

def send_email(subject, body, to_email, attachment_path=None):
    """
    通用發信函數：支援純文字通知與附件寄送
    """
    sender = st.secrets["email"]["SENDER"]
    password = st.secrets["email"]["PASSWORD"]
    
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = f"Lease AI Assistant <{sender}>"
    msg['To'] = to_email # 這裡動態傳入接收者 (屋主或租客)
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    # 如果有附件路徑且檔案存在，才執行夾帶附件邏輯
    if attachment_path and os.path.exists(attachment_path):
        try:
            with open(attachment_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename={os.path.basename(attachment_path)}"
                )
                msg.attach(part)
        except Exception as e:
            print(f"附件處理失敗: {e}")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"郵件發送失敗: {e}")
        return False