# contract_worker.py
from docxtpl import DocxTemplate
import os

def generate_contract(data_dict):
    """
    從 assets 資料夾讀取 Word 模板並渲染資料
    """
    # 1. 動態建立模板路徑
    base_dir = os.path.dirname(os.path.abspath(__file__)) # 取得當前檔案所在目錄
    template_path = os.path.join(base_dir, "assets", "Lease_Agreement_Python_Template.docx")
    
    # 2. 檢查檔案是否存在
    if not os.path.exists(template_path):
        print(f"❌ 錯誤：找不到模板檔案於 {template_path}")
        return None
    
    try:
        # 3. 載入並渲染模板
        doc = DocxTemplate(template_path)
        doc.render(data_dict)
        
        # 4. 產出檔案名稱
        safe_name = data_dict.get('tenant_name', 'Draft').replace(' ', '_')
        output_filename = f"Lease_Agreement_{safe_name}.docx"
        
        # 5. 儲存檔案
        doc.save(output_filename)
        
        return output_filename

    except Exception as e:
        print(f"❌ 生成合約時發生異常: {e}")
        return None