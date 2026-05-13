import time
import json
import streamlit as st
import tomllib
from database import get_applications_table
from models import get_model_pipeline, get_gen_config 
from template_generator import generate_data_template 
import email_worker as ew  # 引入剛剛建立的通用發信工具

# --- 1. AI 審核核心邏輯 ---

def analyze_applicant(data):
    """
    讀取 Prompt 設定，調用 AI 模型進行租客背景分析
    """
    # 1. 讀取設定與 Schema
    try:
        with open(".streamlit/prompts.toml", "rb") as f:
            prompts = tomllib.load(f)
        with open(".streamlit/form_schema.toml", "rb") as f:
            schema = tomllib.load(f)
    except FileNotFoundError as e:
        st.error(f"❌ 找不到設定檔：{e}")
        return 0, "系統設定錯誤"

    # 2. 準備 AI 指令與資料模版
    config = prompts["screening"]
    system_instruction = config["system_message"] 
    
    # 生成資料填充模版
    data_template = generate_data_template(schema)
    
    # 拼裝完整的 Prompt 結構
    full_prompt_template = f"{config['criteria']}\n\n{data_template}\n\n{config['json_format']}"
    
    # 將實際租客資料填入模版
    try:
        final_prompt = full_prompt_template.format(**data)
    except KeyError as e:
        st.error(f"❌ 欄位缺失：資料庫中找不到 {e} 欄位。")
        return 0, "資料欄位不匹配"

    # 3. 獲取模型管線 (Gemini 等)
    pipeline = get_model_pipeline(system_instruction)
    
    # 4. 遍歷模型管線直到成功
    for model, model_name in pipeline:
        try:
            response = model.generate_content(
                final_prompt,
                generation_config=get_gen_config(is_json=True)
            )
            
            result = json.loads(response.text)
            st.info(f"✨ 使用模型 {model_name} 分析成功")
            return result.get("score", 0), result.get("summary", "無總結")
            
        except Exception as e:
            st.warning(f"⚠️ 模型 {model_name} 分析失敗，嘗試備援方案... (錯誤: {e})")
            continue

    st.error("❌ 所有 AI 模型皆無法完成審核。")
    return 0, "AI 服務暫時中斷，請稍後手動檢查"

# --- 2. 主迴圈：自動化巡檢流程 ---

def main():
    # 取得當前環境與資料表
    current_env = st.secrets.get("config", {}).get("ENV", "prod").upper()
    owner_email = st.secrets["email"].get("OWNER_EMAIL") # 確保 secrets 有設定屋主信箱
    
    st.title(f"🤖 租房 AI 自動化管家 ({current_env})")
    st.write(f"監控中：正在巡檢資料表...")
    
    app_table = get_applications_table(use_admin=True)
    
    CHECK_INTERVAL = 30 
    status_placeholder = st.empty()

    while True:
        # --- 第一部分：處理 pending 的新申請 (AI 分析) ---
        pending_res = app_table.select("*").eq("ai_status", "pending").execute()
        new_applicants = pending_res.data
        
        if new_applicants:
            for person in new_applicants:
                st.info(f"🔍 發現新申請：{person.get('full_name')}，啟動 AI 分析...")
                score, summary = analyze_applicant(person)
                
                # 更新 AI 分析結果
                app_table.update({
                    "ai_status": "reviewed",
                    "ai_score": score,
                    "ai_summary": summary,
                    "landlord_notified": False 
                }).eq("id", person["id"]).execute()
                st.success(f"✅ {person.get('full_name')} 分析完成 (得分: {score})")
                time.sleep(1)

        # --- 第二部分：處理已分析但尚未通知屋主的資料 (郵件通知) ---
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
                    st.warning(f"🌟 發現高分申請者：{full_name} ({score}分)，準備通知屋主...")
                    
                    subject = f"【優質租客預警】{full_name} 獲得了 {score} 分！"
                    body = f"""屋主您好：

AI 助手發現了一位優質申請者：
姓名：{full_name}
職業：{person.get('occupation', '未填寫')}
AI 評分：{score}
AI 總結：{person.get('ai_summary', '無')}

請儘速登入後台查看詳細資料。"""
                    
                    # 調用獨立出的發信工具
                    mail_success = ew.send_email(subject, body, owner_email)
                    
                    if mail_success:
                        st.success(f"📧 已成功寄信通知屋主：{full_name}")
                        app_table.update({"landlord_notified": True}).eq("id", person["id"]).execute()
                    else:
                        st.error(f"❌ 郵件發送失敗，將於下次巡檢重試：{full_name}")
                
                else:
                    # 分數低於 80 分，不寄信，直接標記為已通知以免重複巡檢
                    st.write(f"📄 已完成分析 (分數未達標)：{full_name} ({score}分)")
                    app_table.update({"landlord_notified": True}).eq("id", person["id"]).execute()

        # --- 狀態顯示與休眠 ---
        status_placeholder.write(f"😴 目前無新進度 ({current_env})，{CHECK_INTERVAL} 秒後再次巡檢...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()