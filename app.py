import streamlit as st
import tomllib
import json  # 必須引入，用於解析 AI 回傳的格式
from database import *
from models import get_model_pipeline, get_gen_config 
import time # 加入這個來做極短暫的緩衝
import pandas as pd
from streamlit_calendar import calendar
import uuid
import datetime

# --- 1. 配置與讀取 ---

current_env = st.secrets.get("config", {}).get("ENV", "prod").upper()

with open(".streamlit/prompts.toml", "rb") as f:

    prompts = tomllib.load(f)

with open(".streamlit/form_schema.toml", "rb") as f:

    form_config = tomllib.load(f)

# --- 2. 頁面函式化 ---

def render_tenant_portal():
    """租客入口：包含 AI 諮詢與提交申請"""
    tab1, tab2 = st.tabs(["AI 諮詢", "提交申請"])
    
    with tab1:
        left_space, center_space, right_space = st.columns([1, 2, 1])

        with center_space:
        
            st.subheader("🏠 租屋 AI 小助手")
            
            # 1. 從資料庫抓取即時房間狀態 (自動感應 _dev 表)
            r_table = get_rooms_table()
            rooms_info = r_table.select("room_name, status, lease_end").execute().data
            
            # 格式化房間資訊作為 AI 的背景知識
            room_context = "\n目前的房間供應狀況如下：\n"
            for r in rooms_info:
                status_text = "✅ 目前可立即入住" if r['status'] == 'available' else f"❌ 已出租，預計 {r['lease_end']} 之後空出"
                room_context += f"- {r['room_name']}: {status_text}\n"

            # 2. 建立對話容器 (用來顯示對話紀錄)
            chat_container = st.container()

            # 初始化對話紀錄
            if "messages" not in st.session_state:
                st.session_state.messages = []

            # --- 第二層防禦配置：設定歷史紀錄上限 ---
            # 這裡設定保留最近 10 則訊息（約 5 輪對話），避免對話過長導致 AI 脫離角色 [1]
            MAX_HISTORY = 10

            # --- 第三層防禦配置：頻率限制設定 ---
            MAX_REQUESTS_PER_MINUTE = 3  # 每分鐘最多 3 次發問 (配合 Gemini 2.5 限制) [cite: 112]
            if "request_timestamps" not in st.session_state:
                st.session_state.request_timestamps = []

            chat_container = st.container()
            if "messages" not in st.session_state:
                st.session_state.messages = []

            # 顯示歷史訊息
            with chat_container:
                for message in st.session_state.messages:
                    with st.chat_message(message["role"]):
                        st.markdown(message["content"])

            # 3. 專用的打字框
            if prompt := st.chat_input("請詢問空房時間、居住條款或照片資訊..."):
                
                # --- 第三層防禦實作：檢查請求頻率 ---
                current_time = time.time()
                # 清除超過 60 秒前的紀錄
                st.session_state.request_timestamps = [t for t in st.session_state.request_timestamps if current_time - t < 60]
                
                if len(st.session_state.request_timestamps) >= MAX_REQUESTS_PER_MINUTE:
                    wait_time = int(60 - (current_time - st.session_state.request_timestamps[0]))
                    st.error(f"哎呀，您問得太快，我的 AI 大腦快要冒煙啦！♨️ 請稍等 {wait_time} 秒再試。")
                else:
                    # 紀錄本次請求時間
                    st.session_state.request_timestamps.append(current_time)

                    # 立即顯示使用者輸入
                    st.session_state.messages.append({"role": "user", "content": prompt})
                    with chat_container:
                        with st.chat_message("user"):
                            st.markdown(prompt)

                        with st.chat_message("assistant"):
                            with st.spinner("AI 正在回覆..."):
                                # ... (System Instruction 組合與對話歷史截取邏輯保持不變) ...
                                base_instruction = prompts['chat_bot']['system_instruction']
                                instruction = f"{base_instruction}\n\n{room_context}"
                                recent_history = st.session_state.messages[-(MAX_HISTORY+1):-1]
                                history_text = "\n".join([f"{m['role']}: {m['content']}" for m in recent_history])
                                full_prompt = f"{instruction}\n\n[近期對話紀錄]\n{history_text}\n\nUser: {prompt}"

                                pipeline = get_model_pipeline(instruction)
                                response_text = None
                                for model, model_name in pipeline:
                                    try:
                                        response = model.generate_content(full_prompt)
                                        response_text = response.text
                                        break
                                    except Exception as e:
                                        st.warning(f"⚠️ {model_name} 暫時無法使用: {e}")
                                
                                if response_text:
                                    st.markdown(response_text)
                                    st.session_state.messages.append({"role": "assistant", "content": response_text})
                                    # 強制切片保持歷史長度
                                    if len(st.session_state.messages) > MAX_HISTORY:
                                        st.session_state.messages = st.session_state.messages[-MAX_HISTORY:]
                                else:
                                    st.error("❌ 目前 AI 服務暫時中斷。")

    with tab2:
        
        # 使用 columns 創造置中的窄版區塊 (比例 1:2:1)
        # 這樣表單會佔據中間 50% 的寬度
        left_space, center_space, right_space = st.columns([1, 2, 1])

        with center_space:
            st.subheader("填寫租屋申請單")
            new_applicant_data = {}

            with st.form("lease_form", clear_on_submit=True):
                for field in form_config["fields"]:
                    fid = field["id"]
                    label = field["label"]
                    ftype = field["type"]
                    fhelp = field.get("description", None)

                    if ftype == "text":
                        new_applicant_data[fid] = st.text_input(label, help=fhelp)
                    
                    elif ftype == "number":
                        new_applicant_data[fid] = st.number_input(label, min_value=1, step=1, help=fhelp)
                    
                    elif ftype == "select":
                        # 在選項最前面插入一個空值作為預設
                        original_options = field.get("options", [])
                        options = ["請選擇..."] + original_options
                        
                        selected_val = st.selectbox(label, options=options, help=fhelp)
                        
                        # 如果使用者沒選，存入 None 或空字串，觸發必填檢查
                        new_applicant_data[fid] = selected_val if selected_val != "請選擇..." else None

                    elif ftype == "date":
                        # 將 value 設為 None，會顯示 "YYYY/MM/DD" 的預設文字
                        val = st.date_input(label, value=None, help=fhelp)
                        
                        # 如果 val 為 None，存入空值；否則轉為 isoformat
                        new_applicant_data[fid] = val.isoformat() if val else None

                    elif ftype == "area":
                        new_applicant_data[fid] = st.text_area(label, help=fhelp)

                submitted = st.form_submit_button("確認送出", use_container_width=True)
                
                if submitted:
                    # 檢查必填邏輯維持不變
                    missing = [f["label"] for f in form_config["fields"] 
                            if f["required"] and not str(new_applicant_data.get(f["id"], "")).strip()]
                    
                    if not missing:
                        new_applicant_data["ai_status"] = "pending"
                        save_application(new_applicant_data)
                        st.success("✅ 申請已收到！我們會盡快審核。")
                        st.balloons()
                    else:
                        st.warning(f"請填寫必填欄位：{', '.join(missing)}")


@st.dialog("預約詳細資訊")
def show_event_details(event_info):
    st.write(f"**租客姓名:** {event_info.get('title', '未知')}")
    st.write(f"**開始時間:** {event_info.get('start')}")
    st.write(f"**結束時間:** {event_info.get('end')}")
    
    # 這裡可以加入你之前處理過的合約連結或備註
    st.info("備註：租客已預付押金，需於入住前提供身份證件複印本。")
    
    if st.button("關閉"):
        st.rerun()


# 1. 定義右側面板的 CSS 與 JS (隱藏邏輯)
def inject_side_panel_css():
    st.markdown("""
    <style>
    .side-panel {
        position: fixed;
        right: -400px;
        top: 0;
        width: 400px;
        height: 100%;
        background-color: white;
        box-shadow: -2px 0 5px rgba(0,0,0,0.1);
        transition: right 0.3s ease;
        z-index: 9999;
        padding: 20px;
        border-left: 1px solid #ddd;
    }
    .side-panel.open {
        right: 0;
    }
    .overlay {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.3);
        display: none;
        z-index: 9998;
    }
    .overlay.open {
        display: block;
    }
    </style>
    """, unsafe_allow_html=True)


def render_admin_dashboard():
    st.subheader("📊 租屋管理總部 (開發版)")

    # --- 狀態初始化 ---
    if "selected_room_id" not in st.session_state:
        st.session_state.selected_room_id = None
    if "last_calendar_click" not in st.session_state:
        st.session_state.last_calendar_click = None

    today = datetime.date.today()
    tab_room, tab_app = st.tabs(["🏠 房間狀態管理", "📋 申請人審核"])

    with tab_room:
        # 1. 取得資料
        rooms_table = get_rooms_table(use_admin=True)
        leases_table = get_leases_table(use_admin=True)
        app_table = get_applications_table(use_admin=True)

        rooms_data = rooms_table.select("*").order("room_name").execute().data
        all_leases = leases_table.select("*").execute().data

        # 顏色配置檔 (確保全域一致)
        COLOR_CURRENT = "#FF4B4B" # 紅
        COLOR_FUTURE = "#3D9DF3"  # 藍
        COLOR_PAST = "#9E9E9E"    # 灰
        
        potential_tenants = app_table.select("id, full_name").eq("ai_status", "reviewed").execute().data
        tenant_dict = {p['id']: p['full_name'] for p in potential_tenants}
        tenant_options = {p['full_name']: p['id'] for p in potential_tenants}

        col_cal, col_manage = st.columns([3.5, 3.5])

        # --- 左側：租約排程看板 (修正重點) ---
        with col_cal:
            st.write("### 📅 租約排程看板")
            
            calendar_events = []
            for lease in all_leases:
                t_name = tenant_dict.get(lease['tenant_id'], "未知房客")
                room_info = next((r for r in rooms_data if str(r['id']) == str(lease['room_id'])), None)
                r_name = room_info['room_name'] if room_info else "未知房間"
                
                # 確保日期是 ISO 格式字串 (YYYY-MM-DD)
                s_str = str(lease['start_date'])
                e_str = str(lease['end_date'])
                
                is_active = s_str <= str(today) <= e_str

                # 統一顏色判斷邏輯
                if s_str <= str(today) <= e_str:
                    event_color = COLOR_CURRENT
                elif s_str > str(today):
                    event_color = COLOR_FUTURE
                else:
                    event_color = COLOR_PAST

                calendar_events.append({
                    "id": str(lease['id']), 
                    "title": f"👤 {t_name} ({r_name})",
                    "start": s_str,
                    "end": (datetime.datetime.strptime(e_str, '%Y-%m-%d') + datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
                    "color": event_color,
                    "allDay": True,
                    "extendedProps": {"room_id": str(lease['room_id'])}
                })
            
            # 修正後的月曆設定
            calendar_options = {
                "initialView": "dayGridMonth",
                "headerToolbar": {
                    "left": "prev,next today",
                    "center": "title",
                    "right": "dayGridMonth,timeGridWeek"
                },
                "editable": False,
                "selectable": True,
                "navLinks": True,
                # 關鍵：讓事件看起來可以點擊
                "eventClick": True,
                "eventMouseEnter": True, 
                "handleWindowResize": True,
            }

            state = calendar(
                events=calendar_events,
                options={"initialView": "dayGridMonth", "selectable": True},
                key="admin_calendar_static",
                custom_css=".fc-event { cursor: pointer; }"
            )
            
            if state and "eventClick" in state:
                current_click = str(state["eventClick"])
                if current_click != st.session_state.last_click_feature:
                    # 取得房間 ID
                    clicked_room_id = state["eventClick"]["event"]["extendedProps"]["room_id"]
                    
                    # 關鍵：更新選中的房間 ID
                    st.session_state.selected_room_id = clicked_room_id
                    st.session_state.last_click_feature = current_click
                    
                    # 這裡強制 rerun，讓下方的 expander 重新判斷 expanded 參數
                    st.rerun()

        # --- 右側：房間排程明細 (邏輯維持) ---
        with col_manage:
            st.write("### ⚙️ 房間排程明細")
            
            current_selected_id = str(st.session_state.get("selected_room_id", ""))

            for room in rooms_data:
                room_id_str = str(room['id'])
                is_target = (room_id_str == current_selected_id)
                
                # 1. 動態生成標題 (強化選中狀態)
                expander_title = f"🎯 【目前選中】 {room['room_name']}" if is_target else f"📍 {room['room_name']}"
                
                with st.expander(expander_title, expanded=is_target):
                    # 2. 篩選該房間的所有租約並按日期排序
                    room_leases = [l for l in all_leases if str(l['room_id']) == room_id_str]
                    
                    if not room_leases:
                        st.success("🟢 目前此房間尚無任何租約排程")
                    else:
                        # 依開始日期排序，讓排程看起來有順序感
                        sorted_leases = sorted(room_leases, key=lambda x: x['start_date'])
                        
                        for lease in sorted(room_leases, key=lambda x: x['start_date']):
                            l_s = datetime.datetime.strptime(lease['start_date'], '%Y-%m-%d').date()
                            l_e = datetime.datetime.strptime(lease['end_date'], '%Y-%m-%d').date()
                            t_n = tenant_dict.get(lease['tenant_id'], "未知")
                            
                            # 增加一個容器，讓按鈕排整齊
                            c1, c2, c3 = st.columns([5, 1, 1], vertical_alignment="center")
                            
                            # 顏色與天數顯示 (維持你要求的配色)
                            if l_s <= today <= l_e:
                                days_left = (l_e - today).days
                                c1.error(f"🔴 當前：{t_n} ({l_s} ~ {l_e}) ⏳ 剩餘 {days_left} 天")
                            elif l_s > today:
                                days_until = (l_s - today).days
                                c1.info(f"🔵 未來：{t_n} ({l_s} ~ {l_e}) 📅 還有 {days_until} 天開始")
                            else:
                                c1.markdown(f"<span style='color:{COLOR_PAST}'>⚪ 歷史：{t_n} ({l_s} ~ {l_e})</span>", unsafe_allow_html=True)
                            
                            # 按鈕 1：詳情
                            if c2.button("詳情", key=f"det_{lease['id']}", use_container_width=True):
                                st.toast(f"查看 {t_n} 資料")

                            # 按鈕 2：刪除 (觸發二次確認)
                            if c3.button("🗑️", key=f"del_btn_{lease['id']}", use_container_width=True):
                                st.session_state[f"confirm_delete_{lease['id']}"] = True

                            # 二次確認邏輯
                            if st.session_state.get(f"confirm_delete_{lease['id']}", False):
                                st.warning(f"確定刪除 {t_n} 的這筆租約？")
                                col_confirm = st.columns(2)
                                if col_confirm[0].button("確定刪除", key=f"real_del_{lease['id']}", type="primary", use_container_width=True):
                                    # 執行刪除
                                    delete_lease_record(lease['id'])
                                    st.session_state[f"confirm_delete_{lease['id']}"] = False
                                    st.success("已刪除紀錄")
                                    st.rerun() # 刪除後立即更新月曆與列表
                                if col_confirm[1].button("取消", key=f"cancel_{lease['id']}", use_container_width=True):
                                    st.session_state[f"confirm_delete_{lease['id']}"] = False
                                    st.rerun()

                    st.divider()

                    # 編輯表單 (新增/覆蓋邏輯)
                    with st.form(key=f"lease_form_v4_{room['id']}"):
                        selected_tenant = st.selectbox("指定房客", list(tenant_options.keys()), key=f"t_sel_{room['id']}")
                        dc1, dc2 = st.columns(2)
                        new_start = dc1.date_input("開始日期", value=today, key=f"ds_{room['id']}")
                        new_end = dc2.date_input("結束日期", value=today + datetime.timedelta(days=30), key=f"de_{room['id']}")
                        force_confirm = st.checkbox("⚠️ 我確認此時段重疊，並同意覆蓋既有紀錄", key=f"f_check_{room['id']}")

                        if st.form_submit_button("💾 儲存租約設定", use_container_width=True):
                            
                            # --- 關鍵檢查：日期合理性 ---
                            if new_end <= new_start:
                                st.error(f"❌ 儲存失敗：結束日期 ({new_end}) 必須晚於開始日期 ({new_start})！")
                            else:
                                # 日期檢查通過，繼續執行原本的重疊判定與儲存邏輯
                                overlap_id = None
                                for l in room_leases:
                                    ex_s = datetime.datetime.strptime(l['start_date'], '%Y-%m-%d').date()
                                    ex_e = datetime.datetime.strptime(l['end_date'], '%Y-%m-%d').date()
                                    if (new_start <= ex_e) and (new_end >= ex_s):
                                        overlap_id = l['id']
                                        break
                                
                                payload = {
                                    "room_id": room['id'],
                                    "tenant_id": tenant_options[selected_tenant],
                                    "start_date": new_start.isoformat(),
                                    "end_date": new_end.isoformat()
                                }

                                if overlap_id:
                                    if not force_confirm:
                                        st.error("❌ 日期重疊！請勾選確認框。")
                                    else:
                                        update_lease_record(overlap_id, payload)
                                        st.success("✅ 租約已成功更新")
                                        st.rerun()
                                else:
                                    create_lease_record(payload)
                                    st.success("✅ 預約已成功新增")
                                    st.rerun()

    with tab_app:
        # --- 保留你原本的申請人審核邏輯 ---
        table = get_applications_table()
        pending_count = table.select("id", count="exact").eq("ai_status", "pending").execute().count
        reviewed_count = table.select("id", count="exact").eq("ai_status", "reviewed").execute().count
        
        c1, c2 = st.columns(2)
        c1.metric("待處理 (AI 分析中)", f"{pending_count} 筆")
        c2.metric("已完成分析", f"{reviewed_count} 筆")
        st.divider()

        res = table.select("*").eq("ai_status", "reviewed").order("ai_score", desc=True).execute()
        applications = res.data

        if not applications:
            st.write("目前沒有新的申請資料。")
        else:
            for person in applications:
                score = person.get("ai_score", 0)
                label = "🌟 優質首選" if score >= 85 else "✅ 符合標準" if score >= 70 else "⚠️ 需多加考慮"
                
                with st.expander(f"{label} ({score}分) - {person['full_name']}"):
                    st.write(f"**分析點評：** {person.get('ai_summary', '尚無總結')}")
                    if st.button(f"批准並發送合約", key=f"app_v2_{person['id']}"):
                        st.balloons()


# --- 3. 主程式進入點 ---


def check_auth():
    """管理員登入驗證"""
    # 初始化 session_state
    if "is_logged_in" not in st.session_state:
        st.session_state["is_logged_in"] = False

    # 如果已經登入成功，直接返回 True
    if st.session_state["is_logged_in"]:
        return True

    # 未登入，顯示簡易登入畫面
    st.markdown("### 🔐 屋主後台登入")
    input_pwd = st.text_input("請輸入管理密碼", type="password")
    
    if st.button("確認登入"):
        if input_pwd == st.secrets["auth"]["ADMIN_PASSWORD"]:
            st.session_state["is_logged_in"] = True
            st.success("登入成功！")
            st.rerun()  # 重新整理以載入後台內容
        else:
            st.error("❌ 密碼錯誤")
    
    return False


def set_bg_hack(main_bg):
    '''
    A function to unpack an image from a local file and set it as the background.
    '''
    # 如果是本地檔案，需要轉成 base64
    # main_bg_ext = "png"
    # st.markdown(
    #     f"""
    #     <style>
    #     .stApp {{
    #         background: url(data:image/{main_bg_ext};base64,{base64.b64encode(open(main_bg, "rb").read()).decode()});
    #         background-size: cover;
    #         background-attachment: fixed;
    #     }}
    #     </style>
    #     """,
    #     unsafe_allow_html=True
    # )
    
    # 如果是網路連結 (URL) 直接使用：
    st.markdown(
        f"""
        <style>
        .stApp {{
            background: url("{main_bg}");
            background-size: cover;
            background-position: center;
            background-attachment: fixed; /* 關鍵：讓背景固定不隨捲動位移 */
            background-repeat: no-repeat;
        }}
        
        /* 為了讓表單文字清楚，幫 Tab 內容增加一點半透明白底 */
        [data-testid="stExpander"], [data-testid="stForm"] {{
            background-color: rgba(255, 255, 255, 0.85);
            border-radius: 15px;
            padding: 20px;
        }}
        </style>
        """,
        unsafe_allow_html=True
    )

# 呼叫函數（替換成你的圖片連結）
set_bg_hack("你的圖片URL_或是剛才生成的圖片路徑")


# --- 修改你的主導航邏輯 ---
def main():
    st.set_page_config(page_title="Lease AI 租房助手", layout="wide")
    
    # 1. 從 secrets 取得秘密標籤
    admin_key = st.secrets["auth"].get("ADMIN_MODE_KEY", "secret-not-set")
    
    # 2. 檢查 URL 參數 (例如：?mode=boss)
    query_params = st.query_params
    is_admin_entry = query_params.get("mode") == admin_key

    st.title(f"🏠 Lease AI 租房助手 ({current_env})")
    st.sidebar.title("Lease AI 導航")
    
    # 3. 根據網址參數決定要顯示哪些選單
    if is_admin_entry:
        # 只有在網址符合秘密參數時，才會出現後台選項
        page = st.sidebar.radio("前往頁面", ["租客申請表單", "屋主管理後台"])
    else:
        # 一般人進來，預設只能待在租客表單，且看不到任何切換選項
        page = "租客申請表單"

    # 4. 分頁渲染邏輯 [cite: 368]
    if page == "租客申請表單":
        render_tenant_portal()
    elif page == "屋主管理後台":
        # 雖然網址對了，但進入後台依然要通過第二重密碼檢查
        if check_auth():
            render_admin_dashboard()

if __name__ == "__main__":
    main()
