import streamlit as st
from supabase import create_client, Client

@st.cache_resource
def get_supabase(use_admin=False) -> Client:
    url = st.secrets["supabase"]["SUPABASE_URL"]
    # 根據需求切換 Key
    key = st.secrets["supabase"]["SUPABASE_SERVICE_KEY"] if use_admin else st.secrets["supabase"]["SUPABASE_KEY"]
    return create_client(url, key)

def get_applications_table(use_admin=False):
    supabase = get_supabase(use_admin=use_admin)
    env = st.secrets.get("config", {}).get("ENV", "prod")
    
    if env == "dev":
        return supabase.table("applications_dev")
    return supabase.table("applications")

def save_application(data):
    table = get_applications_table()
    try:
        response = table.insert(data).execute()
        return response
    except Exception as e:
        # 這樣錯誤訊息就會直接出現在網頁上，不用翻 Terminal
        st.error(f"🚨 資料庫寫入失敗！請檢查 Supabase 欄位是否與 TOML 對齊。")
        st.exception(e) # 這會把詳細錯誤碼 (PGRST204) 摺疊顯示在下面
        raise e