import streamlit as st
import google.generativeai as genai

# 配置 API Key
genai.configure(api_key=st.secrets["keys"]["GEMINI_API_KEY"])

def get_model_pipeline(instruction, is_json=False):
    """
    這是一個生成器。
    它不負責執行，只負責按順序『產出』配置好的模型物件。
    """
    model_candidates = [
        "gemini-3.1-flash-lite-preview",
        "gemini-2.5-flash"
    ]
    
    for model_name in model_candidates:
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=instruction
        )
        # 把配置好的模型丟出去
        yield model, model_name

def get_gen_config(is_json=False):
    """輔助工具：回傳生成設定"""
    if is_json:
        return {"response_mime_type": "application/json"}
    return None