import streamlit as st
import google.generativeai as genai
import tomllib
import json
from database import save_application

# 1. 讀取設定與指令
with open(".streamlit/prompts.toml", "rb") as f:
    prompts = tomllib.load(f)

# 2. 設定 Gemini (確保 secrets 有設好)
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

st.title("🏠 Lease AI 租房助手")

# --- UI 分頁 ---
tab1, tab2 = st.tabs(["AI 諮詢", "提交申請"])

with tab1:
    st.subheader("有任何問題嗎？問問 AI")

    # 1. 定義一個清空輸入框的函式
    def clear_chat_input():
        # 把目前輸入的東西存到一個暫存變數
        st.session_state["user_msg"] = st.session_state["temp_input"]
        # 清空輸入框
        st.session_state["temp_input"] = ""

    # 2. 使用 st.text_input 並綁定回調
    st.text_input(
        "您可以詢問空房時間、居住條款等：", 
        key="temp_input", 
        on_change=clear_chat_input
    )

    # 3. 處理對話邏輯
    # 檢查 session_state 裡有沒有剛剛存下來的 user_msg
    if "user_msg" in st.session_state and st.session_state["user_msg"]:
        user_quest = st.session_state["user_msg"]
        
        chat_model = genai.GenerativeModel(
            model_name='gemini-2.5-flash',
            system_instruction=prompts["chat_bot"]["system_instruction"]
        )
        
        with st.spinner("AI 思考中..."):
            response = chat_model.generate_content(user_quest)
            st.markdown(f"**你問：** {user_quest}")
            st.markdown(f"**AI 回覆：**\n\n{response.text}")
            
        # 處理完後清空，避免下次重新整理又跑一次
        st.session_state["user_msg"] = ""

with tab2:
    st.subheader("填寫租屋申請單")
    with st.form("lease_form", clear_on_submit=True):
        name = st.text_input("全名*")
        email = st.text_input("信箱*")
        occ = st.text_input("職業")
        msg = st.text_area("給屋主的話")
        submitted = st.form_submit_button("確認送出")
        
        if submitted:
            if name and email:
                # 這裡「只存資料」，完全不呼叫 AI
                new_data = {
                    "full_name": name,
                    "email": email,
                    "occupation": occ,
                    "message": msg,
                    "ai_status": "pending"  # 標記為待處理
                }
                save_application(new_data)
                st.success("✅ 申請已收到！我們會盡快審核並聯繫您。")
                st.balloons() # 給使用者正向反饋
            else:
                st.warning("請填寫必填欄位。")