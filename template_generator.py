def generate_data_template(schema):
    """
    根據 form_schema 自動生成資料區區段
    """
    lines = ["分析以下申請人資料："]
    for field in schema["fields"]:
        if field.get("ai_include", True): # 預設包含，除非標記為 False
            lines.append(f"- {field['label']}: {{{field['id']}}}")
    return "\n".join(lines)