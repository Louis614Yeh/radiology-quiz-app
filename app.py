import streamlit as st
import pandas as pd
import os
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection

# ==========================================
# ⚙️ 初始設定與 AI 配置
# ==========================================
st.set_page_config(page_title="放射師國考刷題神器 V4.0", layout="wide")

try:
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"].strip())
        # 已升級為精準度更高的 pro 模型
        model = genai.GenerativeModel('gemini-3.1-flash-lite') 
    else:
        st.warning("⚠️ 未偵測到 API Key，請至 Streamlit Secrets 設定。")
        model = None
except Exception as e:
    st.error(f"AI 配置出錯：{e}")
    model = None

# ==========================================
# 📂 建立 Google Sheets 連線與資料處理
# ==========================================
conn = st.connection("gsheets", type=GSheetsConnection)

def clear_cache():
    """當切換科目、使用者或模式時，清除暫存的題號，讓系統重新去資料庫抓進度"""
    if 'current_q_index' in st.session_state:
        del st.session_state['current_q_index']

@st.cache_data
def load_quiz_data():
    try:
        excel_file = pd.ExcelFile('exam_db.xlsx') 
        db = {}
        for sheet in excel_file.sheet_names:
            df = excel_file.parse(sheet)
            df['年度-期別'] = df['年度-期別'].astype(str).str.strip()
            df['題號'] = df['題號'].astype(str).str.strip()
            df['科目'] = sheet
            db[sheet] = df
        return db
    except Exception as e:
        st.error(f"讀取題庫失敗：{e}")
        st.stop()

def load_user_records(data_type):
    """從 Google Sheets 讀取特定分頁的資料"""
    try:
        df = conn.read(worksheet=data_type) 
        # 確保讀下來的是字串，並把全空的 row 丟掉
        return df.dropna(how="all").astype(str)
    except Exception as e:
        st.error(f"讀取 {data_type} 失敗：{e}")
        return pd.DataFrame()

def save_record(data_type, user_id, subject, year, q_num, action="add"):
    """寫入資料到 Google Sheets"""
    df = load_user_records(data_type)
    u, s, y, q = str(user_id), str(subject), str(year), str(q_num)
    
    # 防呆：確保 DataFrame 有正確的欄位
    if not df.empty and all(col in df.columns for col in ['user_id', '科目', '年度-期別', '題號']):
        mask = (df['user_id'] == u) & (df['科目'] == s) & (df['年度-期別'] == y) & (df['題號'] == q)
    else:
        df = pd.DataFrame(columns=['user_id', '科目', '年度-期別', '題號'])
        mask = pd.Series([False])

    if action == "add" and not mask.any():
        new_row = pd.DataFrame([[u, s, y, q]], columns=df.columns)
        df = pd.concat([df, new_row], ignore_index=True)
    elif action == "remove" and mask.any():
        df = df[~mask]
        
    # 覆寫回 Google Sheets
    conn.update(worksheet=data_type, data=df)

def render_content(content):
    content_str = str(content).strip()
    if ".png" in content_str.lower():
        img_path = os.path.join("images", content_str)
        if os.path.exists(img_path):
            st.image(img_path, width=450)
        else:
            st.warning(f"🖼️ 找不到圖檔：{content_str}")
    elif content_str != "nan":
        st.write(content_str)

# ==========================================
# 📱 介面控制 (先定義 u_id 和 subject，供後續邏輯使用)
# ==========================================
st.sidebar.title("🩺 放射師專屬題庫")
u_id = st.sidebar.selectbox("切換使用者：", ["614", "941", "Guest"], on_change=clear_cache)

quiz_db = load_quiz_data()
subject = st.sidebar.radio("選擇科目：", list(quiz_db.keys()), on_change=clear_cache)
df_full = quiz_db[subject].copy()

valid_years = sorted([y for y in df_full['年度-期別'].unique() if str(y).lower() != 'nan'])
selected_year = st.sidebar.selectbox("選擇年度：", ["全部年度"] + valid_years, on_change=clear_cache)

mode = st.sidebar.selectbox("模式：", ["一般練習", "錯題重刷", "標記題庫"], on_change=clear_cache)
st.sidebar.divider()
hide_done = st.sidebar.checkbox("✅ 隱藏已答對題目", value=True, on_change=clear_cache)

# 清除進度功能 (已改寫為清除 Google Sheets 上的該使用者資料)
if st.sidebar.button("🗑️ 清除當前使用者進度"):
    for t in ["history", "wrong", "marks", "progress"]:
        df = load_user_records(t)
        if not df.empty and 'user_id' in df.columns:
            df = df[df['user_id'] != str(u_id)]
            conn.update(worksheet=t, data=df)
    clear_cache()
    st.success("已清除雲端進度！")
    st.rerun()

# ==========================================
# 🧠 核心過濾邏輯 
# ==========================================
df_view = df_full.copy()
if selected_year != "全部年度":
    df_view = df_view[df_view['年度-期別'] == str(selected_year)]

if hide_done and mode != "標記題庫":
    history = load_user_records("history")
    if not history.empty and 'user_id' in history.columns:
        u_hist = history[history['user_id'] == str(u_id)]
        if not u_hist.empty:
            df_view = df_view.merge(u_hist[['年度-期別', '題號']], on=['年度-期別', '題號'], how='left', indicator=True)
            df_view = df_view[df_view['_merge'] == 'left_only'].drop(columns=['_merge'])

if mode != "一般練習":
    rec_t = "wrong" if mode == "錯題重刷" else "marks"
    recs = load_user_records(rec_t)
    if not recs.empty and 'user_id' in recs.columns:
        u_recs = recs[recs['user_id'] == str(u_id)]
        if not u_recs.empty:
            df_view = df_view.merge(u_recs[['年度-期別', '題號']], on=['年度-期別', '題號'])
        else:
            df_view = pd.DataFrame()
    else:
        df_view = pd.DataFrame()

df_view = df_view.drop_duplicates(subset=['年度-期別', '題號'])
# 重設 index，確保我們用 iloc 抓取單題時不會對應錯誤
df_view = df_view.reset_index(drop=True)

# ==========================================
# 🧠 閃卡進度記憶邏輯 (必須放在 u_id、subject 以及過濾器之後)
# ==========================================
progress_df = load_user_records("progress")

# 防呆：如果 progress 表格是空的，先給它預設欄位避免報錯
if progress_df.empty or 'user_id' not in progress_df.columns:
    progress_df = pd.DataFrame(columns=['user_id', '科目', 'current_index'])

current_prog_mask = (progress_df['user_id'] == str(u_id)) & (progress_df['科目'] == subject)

if 'current_q_index' not in st.session_state:
    if current_prog_mask.any():
        # 如果雲端有進度，抓取雲端進度
        saved_index = int(progress_df[current_prog_mask]['current_index'].values[0])
        st.session_state['current_q_index'] = saved_index
    else:
        # 如果沒有進度，從第 0 題開始
        st.session_state['current_q_index'] = 0

def next_question():
    """切換到下一題，並將進度存回 Google Sheets"""
    st.session_state['current_q_index'] += 1
    
    # 更新進度表
    prog_df = load_user_records("progress")
    if prog_df.empty or 'user_id' not in prog_df.columns:
        prog_df = pd.DataFrame(columns=['user_id', '科目', 'current_index'])
        
    mask = (prog_df['user_id'] == str(u_id)) & (prog_df['科目'] == subject)
    
    if mask.any():
        prog_df.loc[mask, 'current_index'] = str(st.session_state['current_q_index'])
    else:
        new_prog = pd.DataFrame([[str(u_id), subject, str(st.session_state['current_q_index'])]], columns=['user_id', '科目', 'current_index'])
        prog_df = pd.concat([prog_df, new_prog], ignore_index=True)
        
    conn.update(worksheet="progress", data=prog_df)

# ==========================================
# ✍️ 測驗主畫面 (一頁一題模式)
# ==========================================
total_q = len(df_view)

if total_q > 0:
    # 防呆：如果篩選後的題數變少（例如隱藏了剛答對的題目），導致索引越界，自動歸零
    if st.session_state['current_q_index'] >= total_q:
        st.session_state['current_q_index'] = 0  
        
    # 🟢 只抓取當前這 "1" 題的資料
    row = df_view.iloc[st.session_state['current_q_index']]
    q_key = f"{subject}_{row['年度-期別']}_{row['題號']}"
    
    st.progress((st.session_state['current_q_index'] + 1) / total_q, text=f"進度：{st.session_state['current_q_index'] + 1} / {total_q} 題")
    
    with st.container(border=True):
        col_q, col_mark = st.columns([8, 2])
        col_q.markdown(f"#### 第 {row['題號']} 題 ({row['年度-期別']})")
        
        # 標記按鈕邏輯
        marked_df = load_user_records("marks")
        is_m = False
        if not marked_df.empty and 'user_id' in marked_df.columns:
            is_m = ((marked_df['user_id'] == str(u_id)) & 
                    (marked_df['年度-期別'] == str(row['年度-期別'])) & 
                    (marked_df['題號'] == str(row['題號']))).any()
        
        if col_mark.button("🌟 已標記" if is_m else "☆ 標記", key=f"mark_{q_key}"):
            save_record("marks", u_id, subject, row['年度-期別'], row['題號'], "remove" if is_m else "add")
            st.rerun()

        # 渲染題目與圖片
        render_content(row['題目內容'])
        if pd.notna(row['圖片路徑']) and ".png" in str(row['圖片路徑']):
            render_content(row['圖片路徑'])

        # 作答區
        user_choice = st.radio("作答：", ["A", "B", "C", "D"], key=f"radio_{q_key}", index=None, horizontal=True)
        for o in ["A", "B", "C", "D"]:
            st.write(f"**({o})**")
            render_content(row[f'選項 {o}'])

        st.divider()
        
        # 按鈕區
        c1, c2, c3 = st.columns([1, 1, 2])
        
        if c1.button("送出答案", key=f"sub_{q_key}"):
            if user_choice == str(row['正確答案']):
                st.success("✅ 正確！")
                save_record("history", u_id, subject, row['年度-期別'], row['題號'], "add")
            elif user_choice is None:
                st.warning("請先選擇一個選項。")
            else:
                st.error(f"❌ 錯誤！正確答案：{row['正確答案']}")
                save_record("wrong", u_id, subject, row['年度-期別'], row['題號'], "add")

        if c2.button("💡 AI 詳解", key=f"ai_{q_key}"):
            if model:
                with st.spinner("AI 老師分析中..."):
                    try:
                        prompt = f"請詳細解析放射師國考題，用繁體中文回答：\n題目：{row['題目內容']}\n選項：(A){row['選項 A']} (B){row['選項 B']} (C){row['選項 C']} (D){row['選項 D']}\n正確答案是 {row['正確答案']}。"
                        response = model.generate_content(prompt)
                        st.info(response.text)
                    except Exception as ai_e:
                        st.error(f"連線失敗：{ai_e}")
            else:
                st.error("請先在 Secrets 設定正確的 GEMINI_API_KEY。")

        # 下一題按鈕 (綁定進度儲存功能)
        if c3.button("➡️ 下一題", type="primary"):
            next_question()
            st.rerun()
else:
    st.success("🎉 目前已無題目！太棒了！")
