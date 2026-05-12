import streamlit as st
from supabase import create_client, Client
import datetime

# --- 基礎配置 ---

def get_env():
    """統一獲取當前環境標籤 (prod 或 dev)"""
    return st.secrets.get("config", {}).get("ENV", "prod").lower()

@st.cache_resource
def get_supabase(use_admin=False) -> Client:
    """根據權限需求初始化 Supabase 連線"""
    url = st.secrets["supabase"]["SUPABASE_URL"]
    # 自動切換 Key：Admin 使用 Service Key 繞過 RLS，一般則用 Anon Key
    key = st.secrets["supabase"]["SUPABASE_SERVICE_KEY"] if use_admin else st.secrets["supabase"]["SUPABASE_KEY"]
    return create_client(url, key)

def get_table(base_name, use_admin=False):
    """
    通用資料表導流器：
    根據 ENV 自動決定是否加上 _dev 後綴
    """
    env = get_env()
    table_name = base_name if env == "prod" else f"{base_name}_dev"
    return get_supabase(use_admin=use_admin).table(table_name)

# --- 功能模組 (指揮官調用的具體接口) ---

def get_applications_table(use_admin=False):
    """獲取申請人資料表"""
    return get_table("applications", use_admin=use_admin)

def get_rooms_table(use_admin=False):
    """獲取房間狀態表"""
    return get_table("rooms", use_admin=use_admin)

def get_leases_table(use_admin=False):
    """
    獲取租約排程表 (leases)
    用於處理一間房多筆租約的邏輯
    """
    return get_table("leases", use_admin=use_admin)

def save_application(data):
    """將申請資料寫入資料庫"""
    table = get_applications_table(use_admin=True) 
    try:
        response = table.insert(data).execute()
        return response
    except Exception as e:
        st.error(f"🚨 資料庫寫入失敗！")
        st.exception(e) 
        raise e

def update_lease_record(lease_id, data):
    """
    更新特定租約紀錄
    會自動包含 updated_at 時間戳
    """
    table = get_leases_table(use_admin=True)
    data["updated_at"] = datetime.datetime.now().isoformat()
    return table.update(data).eq("id", lease_id).execute()

def create_lease_record(data):
    """
    新增租約紀錄
    """
    table = get_leases_table(use_admin=True)
    data["updated_at"] = datetime.datetime.now().isoformat()
    return table.insert(data).execute()

def delete_lease_record(lease_id):
    """
    從租約表中刪除特定紀錄
    """
    table = get_leases_table(use_admin=True) # 使用 admin 權限執行刪除
    try:
        response = table.delete().eq("id", lease_id).execute()
        return response
    except Exception as e:
        st.error(f"🚨 刪除失敗！")
        st.exception(e)
        raise e