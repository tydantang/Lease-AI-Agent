import streamlit as st
# genai 的配置已移往 models.py，這裡只需 import 必要的工具
import tomllib
from database import save_application
from models import get_model_pipeline, get_gen_config  # 引入新工具

# --- 取得環境標籤 ---
current_env = st.secrets.get("config", {}).get("ENV", "prod").upper()

# --- 讀取設定與指令 ---
with open(".streamlit/prompts.toml", "rb") as f:
    prompts = tomllib.load(f)

with open(".streamlit/form_schema.toml", "rb") as f:
    form_config = tomllib.load(f)

st.title(f"🏠 Lease AI 租房助手 ({current_env})")

# --- UI 分頁 ---
tab1, tab2 = st.tabs(["AI 諮詢", "提交申請"])

with tab1:
    st.subheader("有任何問題嗎？問問 AI")

    def clear_chat_input():
        st.session_state["user_msg"] = st.session_state["temp_input"]
        st.session_state["temp_input"] = ""

    st.text_input(
        "您可以詢問空房時間、居住條款等：", 
        key="temp_input", 
        on_change=clear_chat_input
    )

    if "user_msg" in st.session_state and st.session_state["user_msg"]:
        user_quest = st.session_state["user_msg"]
        
        # --- 改進後的 AI 執行與回報邏輯 ---
        instruction = prompts["chat_bot"]["system_instruction"]
        pipeline = get_model_pipeline(instruction) # 獲取模型管線
        
        response_text = None
        
        with st.spinner("AI 思考中..."):
            for model, model_name in pipeline:
                try:
                    # 執行呼叫
                    response = model.generate_content(user_quest)
                    response_text = response.text
                    break # 成功獲取結果，跳出備援迴圈
                except Exception as e:
                    # 回報錯誤，迴圈會自動進入下一輪拿取下一個 model
                    st.warning(f"⚠️ 模型 {model_name} 暫時無法使用，正在嘗試備援方案... (錯誤: {e})")
                    continue

        if response_text:
            st.markdown(f"**你問：** {user_quest}")
            st.markdown(f"**AI 回覆：**\n\n{response_text}")
        else:
            st.error("❌ 抱歉，目前所有 AI 服務均無法回應，請稍後再試。")
            
        st.session_state["user_msg"] = ""

with tab2:
    st.subheader("填寫租屋申請單")
    
    # 用來暫存表單輸入的字典
    new_applicant_data = {}
    
    with st.form("lease_form", clear_on_submit=True):
        # 根據 schema 自動產生成員
        for field in form_config["fields"]:
            fid = field["id"]
            label = field["label"]
            ftype = field["type"]
            
            if ftype == "text":
                new_applicant_data[fid] = st.text_input(label)
            elif ftype == "date":
                # Streamlit date_input 回傳 date 物件，需轉字串存入 SQL
                val = st.date_input(label)
                new_applicant_data[fid] = val.isoformat()
            elif ftype == "area":
                new_applicant_data[fid] = st.text_area(label)
        
        submitted = st.form_submit_button("確認送出")
        
        if submitted:
            # 檢查必填欄位
            missing = [f["label"] for f in form_config["fields"] 
                       if f["required"] and not new_applicant_data.get(f["id"])]
            
            if not missing:
                # 補上 AI 初始狀態
                new_applicant_data["ai_status"] = "pending"
                save_application(new_applicant_data)
                st.success("✅ 申請已收到！我們會盡快審核。")
                st.balloons()
            else:
                st.warning(f"請填寫必填欄位：{', '.join(missing)}")