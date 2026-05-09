import streamlit as st

import tomllib

import json  # 必須引入，用於解析 AI 回傳的格式

from database import save_application, get_applications_table 

from models import get_model_pipeline, get_gen_config 

import time # 加入這個來做極短暫的緩衝

# --- 1. 配置與讀取 ---

current_env = st.secrets.get("config", {}).get("ENV", "prod").upper()



with open(".streamlit/prompts.toml", "rb") as f:

    prompts = tomllib.load(f)



with open(".streamlit/form_schema.toml", "rb") as f:

    form_config = tomllib.load(f)



# --- 2. 頁面函式化 ---



def render_tenant_portal():

    """租客入口：包含 AI 諮詢與提交申請 (保持原樣)"""

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

            instruction = prompts["chat_bot"]["system_instruction"]

            pipeline = get_model_pipeline(instruction) 

            response_text = None

            

            with st.spinner("AI 思考中..."):

                for model, model_name in pipeline:

                    try:

                        response = model.generate_content(user_quest)

                        response_text = response.text

                        break 

                    except Exception as e:

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

        new_applicant_data = {}

        with st.form("lease_form", clear_on_submit=True):

            for field in form_config["fields"]:

                fid = field["id"]

                label = field["label"]

                ftype = field["type"]

                if ftype == "text":

                    new_applicant_data[fid] = st.text_input(label)

                elif ftype == "date":

                    val = st.date_input(label)

                    new_applicant_data[fid] = val.isoformat()

                elif ftype == "area":

                    new_applicant_data[fid] = st.text_area(label)

            

            submitted = st.form_submit_button("確認送出")

            if submitted:

                missing = [f["label"] for f in form_config["fields"] 

                           if f["required"] and not new_applicant_data.get(f["id"])]

                if not missing:

                    new_applicant_data["ai_status"] = "pending"

                    save_application(new_applicant_data)

                    st.success("✅ 申請已收到！我們會盡快審核。")

                    st.balloons()

                else:

                    st.warning(f"請填寫必填欄位：{', '.join(missing)}")



def render_admin_dashboard():
    """屋主管理後台：純粹的展示與決策中心"""
    st.subheader("📊 租屋申請監控面板")
    table = get_applications_table()
    
    # 1. 頂部狀態列 (讓房東知道系統有在運作)
    pending_count = table.select("id", count="exact").eq("ai_status", "pending").execute().count
    reviewed_count = table.select("id", count="exact").eq("ai_status", "reviewed").execute().count
    
    col_stat1, col_stat2 = st.columns(2)
    col_stat1.metric("待處理 (AI 分析中)", f"{pending_count} 筆")
    col_stat2.metric("已完成分析", f"{reviewed_count} 筆")

    st.divider()

    # 2. 顯示已分析完成的申請 (依分數排序)
    res = table.select("*").eq("ai_status", "reviewed").order("ai_score", desc=True).execute()
    applications = res.data

    if not applications:
        if pending_count > 0:
            st.info("📢 AI 正在努力分析新申請中，請稍後重整。")
        else:
            st.write("目前沒有新的申請資料。")
    else:
        for person in applications:
            score = person.get("ai_score", 0)
            
            # 視覺化評分顏色
            if score >= 85:
                label = f"🌟 優質首選 ({score}分)"
                color = "green"
            elif score >= 70:
                label = f"✅ 符合標準 ({score}分)"
                color = "blue"
            else:
                label = f"⚠️ 需多加考慮 ({score}分)"
                color = "orange"

            with st.expander(f"{label} - {person['full_name']} ({person['occupation']})"):
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.write(f"**預計入住：** {person['move_in_date']}")
                    st.write(f"**分析時間：** {person.get('created_at', '')[:10]}")
                with c2:
                    st.markdown("**AI 核心點評：**")
                    st.success(person.get("ai_summary", "尚無總結"))
                
                st.write(f"**自我介紹：** {person.get('introduction', '無')}")
                
                # 這裡可以預留一個按鈕，未來對接「自動寄送合約」
                if st.button(f"批准並發送合約給 {person['full_name']}", key=person['id']):
                    st.balloons()
                    st.write("🚀 (功能開發中：將觸發寄送合約 Agent)")


# --- 3. 主程式進入點 ---



def main():

    st.set_page_config(page_title="Lease AI 租房助手", layout="wide")

    st.title(f"🏠 Lease AI 租房助手 ({current_env})")



    st.sidebar.title("功能導覽")

    choice = st.sidebar.radio("前往：", ["租客入口", "屋主後台"])



    if choice == "租客入口":

        render_tenant_portal()

    else:

        render_admin_dashboard()



if __name__ == "__main__":

    main()