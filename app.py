import streamlit as st
import pandas as pd
import os
import google.generativeai as genai

# ==========================================
# ⚙️ 初始設定與 API Key (安全版)
# ==========================================
st.set_page_config(page_title="放射師國考刷題神器 V2", layout="wide")

# 改用 Streamlit Secrets 來讀取金鑰，保護您的帳號安全！
try:
    GOOGLE_API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash') 
except Exception as e:
    st.error("請先在 Streamlit 後台設定 GEMINI_API_KEY！")
    st.stop()

# ==========================================
# 📂 資料存取函數
# ==========================================

# 1. 讀取題庫 Excel
@st.cache_data
def load_quiz_data():
    excel_file = pd.ExcelFile('exam_db.xlsx') 
    db = {sheet: excel_file.parse(sheet) for sheet in excel_file.sheet_names}
    return db

# 2. 處理「標記」與「錯題」的本地儲存
def get_user_data_file(data_type):
    return f"user_{data_type}.csv"

def load_user_records(data_type):
    file = get_user_data_file(data_type)
    if os.path.exists(file):
        return pd.read_csv(file)
    return pd.DataFrame(columns=['user_id', 'subject', 'year', 'q_num'])

def save_record(data_type, user_id, subject, year, q_num, action="add"):
    df = load_user_records(data_type)
    mask = (df['user_id'] == user_id) & (df['subject'] == subject) & \
           (df['year'] == year) & (df['q_num'] == q_num)
    
    if action == "add" and not df[mask].any().any():
        new_row = pd.DataFrame([[user_id, subject, year, q_num]], columns=df.columns)
        df = pd.concat([df, new_row], ignore_index=True)
    elif action == "remove":
        df = df[~mask]
    
    df.to_csv(get_user_data_file(data_type), index=False)

# 3. 圖片偵測顯示元件
def render_content(content):
    """偵測內容是否含 .png，是則顯示圖片，否則顯示文字"""
    content_str = str(content).strip()
    if ".png" in content_str.lower():
        # 假設圖片都放在 images 資料夾內
        img_path = os.path.join("images", content_str)
        if os.path.exists(img_path):
            st.image(img_path, use_container_width=False, width=400)
        else:
            st.warning(f"找不到圖片檔案：{content_str}")
    else:
        st.write(content_str)

# ==========================================
# 📱 側邊欄與介面控制
# ==========================================
st.sidebar.title("🩺 放射師備考系統")
user_id = st.sidebar.selectbox("切換使用者：", ["614", "941", "Guest"])

try:
    quiz_db = load_quiz_data()
    subjects = list(quiz_db.keys())
    subject = st.sidebar.radio("選擇科目：", subjects)
    
    df_current = quiz_db[subject]
    exam_years = ["全部年度"] + list(df_current['年度-期別'].unique())
    selected_year = st.sidebar.selectbox("選擇年度：", exam_years)
    
    # 模式切換：全部練習 / 錯題重刷 / 標記題庫
    mode = st.sidebar.selectbox("練習模式：", ["一般練習", "錯題重刷", "標記題庫"])
    
except Exception as e:
    st.error("讀取題庫失敗，請確認 exam_db.xlsx 是否與程式放在同一個資料夾。")
    st.stop()

st.sidebar.divider()
st.title(f"📝 {subject} - {mode}")

# ==========================================
# 🧠 題目過濾邏輯
# ==========================================
df_display = df_current.copy()
if selected_year != "全部年度":
    df_display = df_display[df_display['年度-期別'] == selected_year]

if mode == "錯題重刷":
    records = load_user_records("wrong")
    records = records[records['user_id'] == user_id]
    df_display = df_display.merge(records, on=['subject', 'year', 'q_num'])
elif mode == "標記題庫":
    records = load_user_records("marks")
    records = records[records['user_id'] == user_id]
    df_display = df_display.merge(records, on=['subject', 'year', 'q_num'])

# ==========================================
# ✍️ 測驗主循環
# ==========================================
marked_df = load_user_records("marks")

for index, row in df_display.iterrows():
    q_key = f"{subject}_{row['年度-期別']}_{row['題號']}"
    
    with st.container(border=True):
        # 標題與標記按鈕列
        col_q, col_mark = st.columns([8, 2])
        with col_q:
            st.markdown(f"#### 第 {row['題號']} 題 ({row['年度-期別']})")
        with col_mark:
            # 判斷目前題目是否已被該使用者標記
            is_marked = ((marked_df['user_id'] == user_id) & 
                         (marked_df['subject'] == subject) & 
                         (marked_df['year'] == row['年度-期別']) & 
                         (marked_df['q_num'] == row['題號'])).any()
            
            if st.button("🌟 取消標記" if is_marked else "☆ 標記題目", key=f"mark_btn_{q_key}_{user_id}"):
                action = "remove" if is_marked else "add"
                save_record("marks", user_id, subject, row['年度-期別'], row['題號'], action)
                st.rerun()

        # 顯示題目內容 (自動偵測圖片)
        render_content(row['題目內容'])
        
        # 題目如果有額外的圖片路徑 (舊欄位相容)
        if pd.notna(row['圖片路徑']) and ".png" in str(row['圖片路徑']):
            render_content(row['圖片路徑'])

        # 選項渲染
        opts = ["A", "B", "C", "D"]
        user_choice = st.radio(
            "選擇答案：",
            options=opts,
            format_func=lambda x: f"({x})", # 僅顯示代號，內容在下方 render
            key=f"radio_{q_key}_{user_id}",
            index=None,
            horizontal=True
        )
        
        # 顯示選項內容 (自動偵測圖片)
        for opt in opts:
            st.write(f"**({opt})**")
            render_content(row[f'選項 {opt}'])

        # 功能按鈕
        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if st.button("送出答案", key=f"sub_{q_key}_{user_id}"):
                if user_choice == row['正確答案']:
                    st.success("✅ 正確！")
                else:
                    st.error(f"❌ 錯誤！正確答案是 {row['正確答案']}")
                    save_record("wrong", user_id, subject, row['年度-期別'], row['題號'], "add")
        with c2:
            if st.button("💡 AI 詳解", key=f"ai_{q_key}_{user_id}"):
                # 這裡調用先前教您的 AI 生成邏輯
                st.info("AI 正在分析中... (需串接 API)")