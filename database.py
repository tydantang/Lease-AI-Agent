import streamlit as st
from supabase import create_client, Client
import datetime

# --- 基礎配置 ---

def get_env():
    return st.secrets.get("config", {}).get("ENV", "prod").lower()

@st.cache_resource
def get_supabase(use_admin=False) -> Client:
    url = st.secrets["supabase"]["SUPABASE_URL"]
    key = st.secrets["supabase"]["SUPABASE_SERVICE_KEY"] if use_admin else st.secrets["supabase"]["SUPABASE_KEY"]
    return create_client(url, key)

def get_table(base_name, use_admin=False):
    env = get_env()
    table_name = base_name if env == "prod" else f"{base_name}_dev"
    return get_supabase(use_admin=use_admin).table(table_name)

# --- 功能模組 ---

def get_applications_table(use_admin=False): return get_table("applications", use_admin=use_admin)
def get_rooms_table(use_admin=False): return get_table("rooms", use_admin=use_admin)
def get_leases_table(use_admin=False): return get_table("leases", use_admin=use_admin)

# --- [新功能] 合約資料抓取與自動計算 ---

def get_contract_data(application_id):
    """
    正規版：利用 Supabase 實體外鍵關聯進行 Join 查詢
    """
    env = st.secrets.get("config", {}).get("ENV", "prod").lower()
    rooms_table = "rooms_dev" if env == "dev" else "rooms"

    # 因為有了 Foreign Key，我們可以用 table!hint(*) 語法
    # 或者如果只有一個關聯，直接寫 rooms_table(*) 即可
    try:
        res = get_table("applications", use_admin=True)\
            .select(f"*, {rooms_table}!room_name(*)")\
            .eq("id", application_id)\
            .single().execute()
        
        if not res.data:
            return None
            
        app = res.data
        room = app.get(rooms_table) # 直接從回傳結果拿關聯的 room 物件
        
        if not room:
            return None

    # 2. 解析日期與計算
        try:
            # 如果申請單有填 move_in_date 則優先使用
            start_date = datetime.date.fromisoformat(app.get("move_in_date"))
            end_date = datetime.date.fromisoformat(app.get("move_out_date"))
        except (TypeError, ValueError):
            # 否則預設今天開始租一年
            start_date = datetime.date.today()
            end_date = start_date + datetime.timedelta(days=365)
        
        total_days = (end_date - start_date).days
        payment_1_date = datetime.date.today()
        payment_2_date = start_date + datetime.timedelta(days=total_days // 2)
        
        # 3. 金額計算
        daily_rent = room.get("daily_rent", 0)
        total_rent = daily_rent * total_days
        deposit = daily_rent * 30
        payment_1 = total_rent * 0.5 
        
        # 4. 回傳 Word 標籤字典
        return {
            "tenant_name": app.get("full_name", "N/A"),
            "room_name": room.get("room_name", "N/A"),
            "room_name_en": room.get("room_name_en", "N/A"), 
            "lease_start": start_date.strftime("%Y年%m月%d日"),
            "lease_end": end_date.strftime("%Y年%m月%d日"),
            "lease_start_en": start_date.strftime("%B %d, %Y"),
            "lease_end_en": end_date.strftime("%B %d, %Y"),
            "total_days": total_days,
            "daily_rent": f"{daily_rent:,.0f}",
            "total_rent": f"{total_rent:,.0f}",
            "deposit": f"{deposit:,.0f}",
            "payment_1": f"{payment_1:,.0f}",
            "payment_2": f"{(total_rent - payment_1):,.0f}",
            "payment_1_date": payment_1_date.strftime("%Y年%m月%d日"),
            "payment_2_date": payment_2_date.strftime("%Y年%m月%d日"),
            "payment_1_date_en": payment_1_date.strftime("%B %d, %Y"),
            "payment_2_date_en": payment_2_date.strftime("%B %d, %Y")
        }
    except Exception as e:
        st.error(f"資料庫關聯查詢失敗: {e}")
        return None

# --- 優化後的 CRUD 操作 ---

def save_application(data):
    """將申請資料寫入資料庫"""
    try:
        # 移除 st.error，改由調用端決定如何顯示錯誤，保持 database.py 純淨
        return get_applications_table(use_admin=True).insert(data).execute()
    except Exception as e:
        raise e

def create_lease_record(data):
    """新增租約並自動加上時間戳"""
    data["updated_at"] = datetime.datetime.now().isoformat()
    return get_leases_table(use_admin=True).insert(data).execute()

def update_lease_record(lease_id, data):
    """更新租約"""
    data["updated_at"] = datetime.datetime.now().isoformat()
    return get_leases_table(use_admin=True).update(data).eq("id", lease_id).execute()

def delete_lease_record(lease_id):
    """刪除租約"""
    return get_leases_table(use_admin=True).delete().eq("id", lease_id).execute()