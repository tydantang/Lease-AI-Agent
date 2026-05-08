import time
import smtplib
import json
from email.mime.text import MIMEText
from email.header import Header
import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai

# 1. 初始化連線
@st.cache_resource
def init_connection():
    url = st.secrets["supabase"]["SUPABASE_URL"]
    key = st.secrets["supabase"]["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# 2. 發信模組
def send_email(subject, body):
    sender = st.secrets["email"]["SENDER"]
    password = st.secrets["email"]["PASSWORD"]
    receiver = st.secrets["email"]["RECEIVER"]
    
    # 設定 SMTP 伺服器 (Gmail)
    smtp_server = "smtp.gmail.com"
    smtp_port = 465 # SSL
    
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = f"Lease AI Assistant <{sender}>"
    msg['To'] = receiver

    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender, password)
            server.sendmail(sender, [receiver], msg.as_string())
        return True
    except Exception as e:
        print(f"發信失敗: {e}")
        return False

# 3. AI 審核模組
def analyze_applicant(data):
    # 1. 從 prompts.toml 讀取設定
    with open(".streamlit/prompts.toml", "rb") as f:
        import tomllib
        prompts = tomllib.load(f)
    
    config = prompts["screening"]
    
    # 2. 設定 Gemini API
    # 確保你的 secrets.toml 裡有 GEMINI_API_KEY
    genai.configure(api_key=st.secrets["keys"]["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-3.1-flash-lite-preview') # 使用 flash 版本，速度快且免費額度高
    
    # 3. 組合 Prompt
    prompt_content = f"{config['system_message']}\n{config['criteria']}\n{config['template'].format(**data)}"
    st.write(prompt_content)

    # 4. 呼叫 Gemini
    response = model.generate_content(
        prompt_content,
        generation_config={"response_mime_type": "application/json"} # 強制要求 JSON
    )

    st.write(json.loads(response.text))
    
    # 5. 解析回傳結果
    try:
        result = json.loads(response.text)
        return result.get("score"), result.get("summary")
    except Exception as e:
        st.error(f"AI 解析失敗: {e}")
        return 0, "AI 回傳格式錯誤"

# 4. 主迴圈：監控資料庫
def main():
    st.title("🤖 租房 AI 自動化管家")
    st.write("監控中：等待新申請或處理待寄通知...")
    
    CHECK_INTERVAL = 30  # 檢查頻率
    
    # 建立一個佔位符，用來顯示倒數計時，避免畫面一直跳動
    status_placeholder = st.empty()

    while True:
        # --- 第一部分：AI 審核流程 (處理 pending) ---
        pending_res = supabase.table("applications").select("*").eq("ai_status", "pending").execute()
        new_applicants = pending_res.data
        
        if new_applicants:
            for person in new_applicants:
                st.info(f"🔍 發現新申請：{person['full_name']}，啟動 AI 分析...")
                score, summary = analyze_applicant(person)
                
                if score is not None:
                    # 更新 AI 評分結果，但此時 landlord_notified 預設仍為 false
                    supabase.table("applications").update({
                        "ai_status": "reviewed",
                        "ai_score": score,
                        "ai_summary": summary
                    }).eq("id", person["id"]).execute()
                    st.success(f"✅ {person['full_name']} 分析完成 (得分: {score})")
                time.sleep(1) # 短暫停頓避免連發

        # --- 第二部分：通知流程 (處理已審核但未通知房東的資料) ---
        # 這裡會抓取 ai_status='reviewed' 且 landlord_notified=False 的人
        notify_res = supabase.table("applications").select("*")\
            .eq("ai_status", "reviewed")\
            .eq("landlord_notified", False).execute()
        
        to_notify = notify_res.data
        
        if to_notify:
            for person in to_notify:
                st.warning(f"📧 正在為 {person['full_name']} 發送通知信...")
                
                # 只有分數大於等於 80 才寄信（或是你想全部寄，就把 if 刪掉）
                should_send = person.get('ai_score', 0) >= 80
                
                if should_send:
                    subject = f"🔔 高分租客通知：{person['full_name']} ({person['ai_score']}分)"
                    body = f"""
                    屋主您好，系統發現一位優秀申請者：
                    
                    姓名：{person['full_name']}
                    評分：{person['ai_score']}
                    分析：{person['ai_summary']}
                    
                    面試預約狀態：目前尚未預約
                    """
                    
                    # 寄信並根據結果更新資料庫
                    if send_email(subject, body):
                        supabase.table("applications").update({
                            "landlord_notified": True
                        }).eq("id", person["id"]).execute()
                        st.success(f"📬 {person['full_name']} 的通知已送達房東信箱")
                    else:
                        st.error(f"❌ {person['full_name']} 的通知信發送失敗，稍後重試")
                else:
                    # 分數不到 80 分，雖然不寄信，但也要標記為「已處理通知」，否則會卡在迴圈
                    supabase.table("applications").update({
                        "landlord_notified": True 
                    }).eq("id", person["id"]).execute()
                    st.write(f"ℹ️ {person['full_name']} 分數未達標，不寄發通知。")

        # --- 無新資料時的狀態顯示 ---
        if not new_applicants and not to_notify:
            status_placeholder.write(f"😴 目前無新進度，{CHECK_INTERVAL} 秒後再次巡檢...")
        else:
            status_placeholder.empty()

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()