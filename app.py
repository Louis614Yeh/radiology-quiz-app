import streamlit as st
import pandas as pd
import os
import google.generativeai as genai

# ==========================================
# ⚙️ 初始設定與 API Key
# ==========================================
st.set_page_config(page_title="放射師國考刷題神器 V3", layout="wide")

try:
    # 讀取 Streamlit Secrets 中的金鑰
    GOOGLE_API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash') 
except Exception as e:
    st.error("⚠️ 無法讀取 API Key，請確認 Streamlit 後台的 Secrets 是否設定正確。")
    st.stop()

# ==========================================
# 📂 資料存取函數
# ==========================================
@st.cache_data
def load_quiz_data():
    excel_file = pd.ExcelFile('exam_db.xlsx') 
    db = {sheet: excel_file.parse(sheet) for sheet in excel_file.sheet_names}
    return db

def get_user_data_file(data_type):
    return f"user_{data_type}.csv"

def load_user_records(data_type):
    file = get_user_data_file(data_type)
    if os.path.exists(file):
        return pd.read_csv(file)
    return pd.DataFrame(columns=['user_id', 'subject', 'year', 'q_num'])

def save_record(data_type, user_id, subject, year, q_num, action="add"):
    df = load_user_records(data_type)
    mask = (df['user_id'] == str(user_id)) & (df['subject'] == str(subject)) & \
           (df['year'] == str(year)) & (df['q_num'] == str(q_num))
    
    if action == "add" and not df[mask].any().any():
        new_row = pd.DataFrame([[str(user_id), str(subject), str(year), str(q_num)]], columns=df.columns)
        df = pd.concat([df, new_row], ignore_index=True)
    elif action == "remove":
        df = df[~mask]
    
    df.to_csv(get_user_data_file(data_type), index=False)

def render_content(content):
    content_str = str(content).strip()
    if ".png" in content_str.lower():
        img_path = os.path.join("images", content_str)
        if os.path.exists(img_path):
            st.image(img_path, width=400)
        else:
            st.warning(f"⚠️ 找不到圖片檔案：{content_str}")
    else:
        st.write(content_str)

# ==========================================
# 🧠 AI 詳解生成函數 (修復無反應問題)
# ==========================================
def generate_ai_explanation(question_text, option_a, option_b, option_c, option_d, correct_ans):
    prompt = f"""
    你是一位專業的台灣醫事放射師考試補習班名師。請針對以下國考題目給出詳細、易懂的繁體中文詳解。
    請分析正確選項為何正確，並指出其他選項錯誤的原因。
    
    【題目】：{question_text}
    (A) {option_a}
    (B) {option_b}
    (C) {option_c}
    (D) {option_d}
    【官方正確答案】：{correct_ans}
    
    請開始解析：
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ 產生詳解時發生錯誤，可能是 API Key 無效或網路問題。\n系統錯誤訊息：{e}"

# ==========================================
# 📱 側邊欄與介面控制
# ==========================================
st.sidebar.title("🩺 放射師備考系統")
user_id = st.sidebar.selectbox("切換使用者：", ["614", "941", "Guest"])

try:
    quiz_db = load_quiz_data()
    subjects = list(quiz_db.keys())
    subject = st.sidebar.radio("選擇科目：", subjects)
    
    df_current = quiz_db[subject].copy()
    
    # 【修復問題 1】過濾掉 nan 與空白年度
    valid_years = [str(y) for y in df_current['年度-期別'].unique() if pd.notna(y) and str(y).strip().lower() != 'nan']
    exam_years = ["全部年度"] + valid_years
    selected_year = st.sidebar.selectbox("選擇年度：", exam_years)
    
    mode = st.sidebar.selectbox("練習模式：", ["一般練習", "錯題重刷", "標記題庫"])
    
    # 【修復問題 3】新增記憶功能開關
    st.sidebar.divider()
    hide_completed = st.sidebar.checkbox("✅ 隱藏已答對題目", value=False, help="勾選後，您曾答對過的題目將不會顯示，方便快速消耗題庫。")
    
except Exception as e:
    st.error("讀取題庫失敗，請確認 exam_db.xlsx 是否與程式放在同一個資料夾。")
    st.stop()

st.sidebar.divider()
st.title(f"📝 {subject} - {mode}")

# ==========================================
# 🧠 題目過濾邏輯
# ==========================================
df_display = df_current.copy()

# 確保欄位型態一致，避免比對錯誤
df_display['年度-期別'] = df_display['年度-期別'].astype(str)
df_display['題號'] = df_display['題號'].astype(str)

if selected_year != "全部年度":
    df_display = df_display[df_display['年度-期別'] == str(selected_year)]

if mode == "錯題重刷":
    records = load_user_records("wrong")
    records = records[records['user_id'] == str(user_id)]
    df_display = df_display.merge(records, on=['subject', 'year', 'q_num'])
elif mode == "標記題庫":
    records = load_user_records("marks")
    records = records[records['user_id'] == str(user_id)]
    df_display = df_display.merge(records, on=['subject', 'year', 'q_num'])

# 執行「隱藏已答對題目」邏輯
if hide_completed:
    history_df = load_user_records("history")
    user_history = history_df[history_df['user_id'] == str(user_id)]
    # 過濾掉已經存在 history 中的題目
    keys_to_drop = user_history[['subject', 'year', 'q_num']]
    df_display = df_display.merge(keys_to_drop, on=['subject', 'year', 'q_num'], how='left', indicator=True)
    df_display = df_display[df_display['_merge'] == 'left_only'].drop(columns=['_merge'])

# ==========================================
# ✍️ 測驗主循環
# ==========================================
marked_df = load_user_records("marks")

if df_display.empty:
    st.success("🎉 太棒了！此條件下的題目已經全部清空（或無符合題目）！")
else:
    st.info(f"目前顯示題數：{len(df_display)} 題")

for index, row in df_display.iterrows():
    q_key = f"{subject}_{row['年度-期別']}_{row['題號']}"
    
    with st.container(border=True):
        col_q, col_mark = st.columns([8, 2])
        with col_q:
            st.markdown(f"#### 第 {row['題號']} 題 ({row['年度-期別']})")
        with col_mark:
            # 判斷標記狀態
            is_marked = ((marked_df['user_id'] == str(user_id)) & 
                         (marked_df['subject'] == str(subject)) & 
                         (marked_df['year'] == str(row['年度-期別'])) & 
                         (marked_df['q_num'] == str(row['題號']))).any()
            
            if st.button("🌟 取消標記" if is_marked else "☆ 標記題目", key=f"mark_btn_{q_key}_{user_id}"):
                action = "remove" if is_marked else "add"
                save_record("marks", user_id, subject, row['年度-期別'], row['題號'], action)
                st.rerun()

        # 顯示題目與圖片
        render_content(row['題目內容'])
        if pd.notna(row['圖片路徑']) and ".png" in str(row['圖片路徑']):
            render_content(row['圖片路徑'])

        opts = ["A", "B", "C", "D"]
        user_choice = st.radio(
            "選擇答案：",
            options=opts,
            format_func=lambda x: f"({x})",
            key=f"radio_{q_key}_{user_id}",
            index=None,
            horizontal=True
        )
        
        for opt in opts:
            st.write(f"**({opt})**")
            render_content(row[f'選項 {opt}'])

        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if st.button("送出答案", key=f"sub_{q_key}_{user_id}"):
                if user_choice == row['正確答案']:
                    st.success("✅ 正確！")
                    # 答對時，記錄到 history (記憶進度)
                    save_record("history", user_id, subject, row['年度-期別'], row['題號'], "add")
                    # 如果有開「隱藏」功能，答對後重新整理畫面即可讓題目消失
                    if hide_completed:
                        st.rerun()
                elif user_choice is None:
                    st.warning("請先選擇一個選項再送出喔！")
                else:
                    st.error(f"❌ 錯誤！正確答案是 {row['正確答案']}")
                    # 答錯時，記錄到錯題本
                    save_record("wrong", user_id, subject, row['年度-期別'], row['題號'], "add")
                    
        with c2:
            if st.button("💡 AI 詳解", key=f"ai_{q_key}_{user_id}"):
                with st.spinner("AI 老師正在思考中..."):
                    explanation = generate_ai_explanation(
                        row['題目內容'], row['選項 A'], row['選項 B'], row['選項 C'], row['選項 D'], row['正確答案']
                    )
                    st.info(explanation)
