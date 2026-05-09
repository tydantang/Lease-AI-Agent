import time
import smtplib
import json
from email.mime.text import MIMEText
from email.header import Header
import streamlit as st
import tomllib # 確保有引入
from database import get_applications_table
from models import get_model_pipeline, get_gen_config # 引入新工具
from template_generator import generate_data_template # 引入資料模版生成工具

# --- 1. 初始化連線與環境隔離邏輯 ---

@st.cache_resource

# --- 2. 發信模組 (維持原樣) ---

def send_email(subject, body):
    sender = st.secrets["email"]["SENDER"]
    password = st.secrets["email"]["PASSWORD"]
    receiver = st.secrets["email"]["RECEIVER"]
    
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

# --- 3. AI 審核模組 (維持原樣，僅微調註解) ---

def analyze_applicant(data):
    # 1. 讀取設定與 Schema
    with open(".streamlit/prompts.toml", "rb") as f:
        prompts = tomllib.load(f)
    with open(".streamlit/form_schema.toml", "rb") as f:
        schema = tomllib.load(f)
    
    # 2. 準備 AI 指令與資料模版
    config = prompts["screening"]
    # 這裡的 instruction 是傳給 get_model_pipeline 當 system_instruction 用的
    system_instruction = config["system_message"] 
    
    # 生成資料填充區 (例如: - 全名*: {full_name} ...)
    data_template = generate_data_template(schema)
    
    # 拼裝完整的 Prompt 結構
    # 順序：審核標準 -> 動態資料區 -> JSON 格式要求
    full_prompt_template = f"{config['criteria']}\n\n{data_template}\n\n{config['json_format']}"
    
    # 【關鍵步驟】將實際的租客資料 (data) 填入模版
    try:
        final_prompt = full_prompt_template.format(**data)
    except KeyError as e:
        st.error(f"❌ 欄位缺失：資料庫中找不到 {e} 欄位，請檢查 Schema 與資料庫是否同步。")
        return 0, "資料欄位不匹配"

    # 3. 獲取模型管線
    pipeline = get_model_pipeline(system_instruction)
    
    # 4. 遍歷管線中的模型，直到成功為止
    for model, model_name in pipeline:
        try:
            # 呼叫 Gemini
            response = model.generate_content(
                final_prompt,
                generation_config=get_gen_config(is_json=True)
            )
            
            # 嘗試解析結果
            result = json.loads(response.text)
            st.info(f"✨ 使用模型 {model_name} 分析成功")
            
            # 回傳分數與總結
            return result.get("score", 0), result.get("summary", "無總結")
            
        except Exception as e:
            # 如果是 API 失敗或 JSON 解析失敗，回報並試下一個
            st.warning(f"⚠️ 模型 {model_name} 分析失敗，嘗試備援方案... (錯誤: {e})")
            continue

    # 5. 如果所有模型都試過且都失敗
    st.error("❌ 所有 AI 模型皆無法完成審核。")
    return 0, "AI 服務暫時中斷，請稍後手動檢查"

# --- 4. 主迴圈：監控資料庫 (引入動態 Table) ---

def main():
    # 取得當前環境標籤
    current_env = st.secrets.get("config", {}).get("ENV", "prod").upper()
    st.title(f"🤖 租房 AI 自動化管家 ({current_env})")
    st.write(f"監控中：正在巡檢資料表...")
    
    app_table = get_applications_table(use_admin=True)
    
    CHECK_INTERVAL = 30 
    status_placeholder = st.empty()

    while True:
        # --- 第一部分：AI 審核流程 ---
        pending_res = app_table.select("*").eq("ai_status", "pending").execute()
        new_applicants = pending_res.data
        
        if new_applicants:
            for person in new_applicants:
                st.info(f"🔍 發現新申請：{person['full_name']}，啟動 AI 分析...")
                score, summary = analyze_applicant(person)
                
                if score is not None:
                    # 更新 AI 分析結果
                    app_table.update({
                        "ai_status": "reviewed",
                        "ai_score": score,
                        "ai_summary": summary,
                        "landlord_notified": False # 確保進入下一階段的屋主查看流程
                    }).eq("id", person["id"]).execute()
                    st.success(f"✅ {person['full_name']} 分析完成 (得分: {score})")
                time.sleep(1)

# --- 第二部分：屋主查看與郵件通知流程 ---
        notify_res = app_table.select("*")\
            .eq("ai_status", "reviewed")\
            .eq("landlord_notified", False).execute()
        
        to_notify = notify_res.data
        
        if to_notify:
            for person in to_notify:
                score = person.get('ai_score', 0)
                full_name = person.get('full_name', '未知姓名')
                
                # 只有分數 >= 80 才需要寄信
                if score >= 80:
                    st.warning(f"🌟 發現高分申請者：{full_name} ({score}分)，準備寄送 Email...")
                    
                    # 準備郵件內容
                    subject = f"【優質租客預警】{full_name} 獲得了 {score} 分！"
                    body = f"""
                    屋主您好：
                    
                    AI 助手發現了一位優質申請者：
                    姓名：{full_name}
                    職業：{person.get('occupation')}
                    AI 評分：{score}
                    AI 總結：{person.get('ai_summary')}
                    
                    請儘速登入後台查看詳細資料。
                    """
                    
                    # 執行寄信
                    mail_success = send_email(subject, body)
                    
                    if mail_success:
                        st.success(f"📧 已成功寄信通知屋主：{full_name}")
                        # 寄信成功，才更新資料庫標記為 True
                        app_table.update({
                            "landlord_notified": True 
                        }).eq("id", person["id"]).execute()
                    else:
                        st.error(f"❌ 郵件發送失敗，將於下次巡檢重試：{full_name}")
                        # 失敗則不做更新，下一次 while True 迴圈會再次抓到這筆資料重試
                
                else:
                    # 分數低於 80 分，不需要寄信，直接標記為「已處理」以免重複盤查
                    st.write(f"📄 已完成分析 (分數未達標)：{full_name} ({score}分)")
                    app_table.update({
                        "landlord_notified": True 
                    }).eq("id", person["id"]).execute()

        # --- 狀態顯示 ---
        if not new_applicants and not to_review:
            status_placeholder.write(f"😴 目前無新進度 ({current_env})，{CHECK_INTERVAL} 秒後再次巡檢...")
        else:
            status_placeholder.empty()

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()