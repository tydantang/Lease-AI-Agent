import time
import json
import google.generativeai as genai
import tomllib
import streamlit as st
from database import get_supabase

# 1. 載入 prompts 與設定
with open(".streamlit/prompts.toml", "rb") as f:
    prompts = tomllib.load(f)

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
supabase = get_supabase(use_admin=True)

def process_one_application(app):
    app_id = app['id']
    print(f"[*] 正在處理 ID: {app_id} | 申請人: {app['full_name']}")

    context = f"職業: {app.get('occupation')}, 訊息: {app.get('message')}"

    try:
        model = genai.GenerativeModel(
            model_name='gemini-2.5-flash',
            system_instruction=prompts["agent"]["ideal_conditions"]
        )
        
        response = model.generate_content(
            f"請審核：\n{context}",
            generation_config={"response_mime_type": "application/json"}
        )
        
        result = json.loads(response.text)
        
        # --- 關鍵修正區 ---
        # 1. 執行更新並抓取回傳結果來驗證
        update_res = supabase.table("applications").update({
            "ai_score": int(result.get("score", 0)), # 強制轉 int
            "ai_summary": result.get("reason", "無"),
            "ai_status": "completed"
        }).eq("id", app_id).execute()

        # 2. 檢查更新是否真的成功（檢查回傳的 data 長度）
        if len(update_res.data) > 0:
            print(f"✅ 更新成功！ID {app_id} 狀態已改為 completed")
            return True
        else:
            print(f"⚠️ 更新無效：找不到 ID {app_id} 或權限不足。")
            return False

    except Exception as e:
        print(f"❌ 發生錯誤: {str(e)}")
        return False

# 2. 主迴圈：持續監控資料庫
if __name__ == "__main__":
    print("=== Lease AI Worker 已啟動，監控中... ===")
    while True:
        # 抓取一筆狀態為 pending 的資料
        res = supabase.table("applications").select("*").eq("ai_status", "pending").limit(1).execute()
        
        if res.data:
            process_one_application(res.data[0])
            # 遵守 gemini-2.5-flash 每分鐘 5 次的免費規定，處理完一筆強制休息 15 秒
            print("[...] 等待 15 秒避開 API 限制...")
            time.sleep(15)
        else:
            # 沒資料時，每 10 秒檢查一次即可
            time.sleep(10)