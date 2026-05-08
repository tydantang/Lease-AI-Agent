import streamlit as st
from supabase import create_client, Client

def get_supabase(use_admin=False) -> Client:
    url = st.secrets["supabase"]["SUPABASE_URL"]
    # 如果 use_admin 為 True，就用最強的 service key
    key = st.secrets["supabase"]["SUPABASE_SERVICE_KEY"] if use_admin else st.secrets["supabase"]["SUPABASE_KEY"]
    return create_client(url, key)

def save_application(data):
    """將資料存入 Supabase"""
    supabase = get_supabase()
    # 執行 insert 操作
    response = supabase.table("applications").insert(data).execute()
    return response