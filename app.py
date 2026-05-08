import streamlit as st
import pandas as pd
import os
import google.generativeai as genai

# ==========================================
# ⚙️ 初始設定與 AI 配置
# ==========================================
st.set_page_config(page_title="放射師國考刷題神器 V3.8", layout="wide")

try:
    if "GEMINI_API_KEY" in st.secrets:
        # .strip() 自動清除可能存在的空格
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"].strip())
        model = genai.GenerativeModel('gemini-1.5-flash') 
    else:
        st.warning("⚠️ 未偵測到 API Key，請至 Streamlit Secrets 設定。")
        model = None
except Exception as e:
    st.error(f"AI 配置出錯，請確認金鑰是否有效：{e}")
    model = None

# ==========================================
# 📂 暫存記憶體設定 (解決題目秒消失問題)
# ==========================================
if 'just_answered_correct' not in st.session_state:
    st.session_state['just_answered_correct'] = []

def clear_temp_list():
    """切換頁面或模式時，才把剛剛答對的題目真正隱藏"""
    st.session_state['just_answered_correct'] = []

# ==========================================
# 📂 資料處理函數 (確保三方數據獨立)
# ==========================================
@st.cache_data
def load_quiz_data():
    try:
        excel_file = pd.ExcelFile('exam_db.xlsx') 
        db = {sheet: excel_file.parse(sheet) for sheet in excel_file.sheet_names}
        return db
    except Exception as e:
        st.error(f"讀取題庫失敗：{e}")
        st.stop()

def load_user_records(data_type):
    file = f"user_{data_type}.csv"
    required_cols = ['user_id', '科目', '年度-期別', '題號']
    if os.path.exists(file):
        try:
            df = pd.read_csv(file).astype(str)
            if all(col in df.columns for col in required_cols):
                return df
        except:
            pass
    return pd.DataFrame(columns=required_cols)

def save_record(data_type, user_id, subject, year, q_num, action="add"):
    df = load_user_records(data_type)
    u, s, y, q = str(user_id), str(subject), str(year), str(q_num)
    mask = (df['user_id'] == u) & (df['科目'] == s) & (df['年度-期別'] == y) & (df['題號'] == q)
    
    if action == "add" and not df[mask].any().any():
        new_row = pd.DataFrame([[u, s, y, q]], columns=df.columns)
        df = pd.concat([df, new_row], ignore_index=True)
    elif action == "remove":
        df = df[~mask]
    df.to_csv(f"user_{data_type}.csv", index=False)

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
# 📱 介面控制
# ==========================================
st.sidebar.title("🩺 放射師專屬題庫")
u_id = st.sidebar.selectbox("切換使用者：", ["614", "941", "Guest"], on_change=clear_temp_list)

quiz_db = load_quiz_data()
subject = st.sidebar.radio("選擇科目：", list(quiz_db.keys()), on_change=clear_temp_list)
df_full = quiz_db[subject].copy()

# 格式統一
df_full['年度-期別'] = df_full['年度-期別'].astype(str).str.strip()
df_full['題號'] = df_full['題號'].astype(str).str.strip()

valid_years = sorted([y for y in df_full['年度-期別'].unique() if y.lower() != 'nan'])
selected_year = st.sidebar.selectbox("選擇年度：", ["全部年度"] + valid_years, on_change=clear_temp_list)

mode = st.sidebar.selectbox("模式：", ["一般練習", "錯題重刷", "標記題庫"], on_change=clear_temp_list)
st.sidebar.divider()
# 只有在一般練習模式下，隱藏功能才有意義
hide_done = st.sidebar.checkbox("✅ 隱藏已答對題目", value=True)

# ==========================================
# 🧠 核心過濾邏輯 (修復標記與隱藏衝突)
# ==========================================
df_view = df_full.copy()
if selected_year != "全部年度":
    df_view = df_view[df_view['年度-期別'] == str(selected_year)]

# --- 隱藏邏輯 (僅限非標記模式) ---
if hide_done and mode != "標記題庫":
    history = load_user_records("history")
    u_hist = history[history['user_id'] == str(u_id)].copy()
    if not u_hist.empty:
        # 建立題目 ID 用於比對
        u_hist['q_key'] = u_hist['年度-期別'] + "_" + u_hist['題號']
        # 排除掉本回合剛剛才答對的題目 (讓它們暫時留在畫面上)
        u_hist_to_hide = u_hist[~u_hist['q_key'].isin(st.session_state['just_answered_correct'])]
        
        df_view = df_view.merge(u_hist_to_hide[['年度-期別', '題號']], on=['年度-期別', '題號'], how='left', indicator=True)
        df_view = df_view[df_view['_merge'] == 'left_only'].drop(columns=['_merge'])

# --- 模式過濾 (確保標記與錯題獨立) ---
if mode != "一般練習":
    rec_t = "wrong" if mode == "錯題重刷" else "marks"
    recs = load_user_records(rec_t)
    u_recs = recs[recs['user_id'] == str(u_id)]
    # 只取符合標記/錯題紀錄的題目
    df_view = df_view.merge(u_recs[['年度-期別', '題號']], on=['年度-期別', '題號'])

df_view = df_view.drop_duplicates(subset=['年度-期別', '題號'])

# --- 🚀 分頁器 ---
q_per_page = 5 
total_q = len(df_view)
total_pages = max((total_q - 1) // q_per_page + 1, 1)

if total_q > 0:
    page = st.sidebar.number_input(f"頁數 (共 {total_pages} 頁)", 1, total_pages, 1, on_change=clear_temp_list)
    df_page = df_view.iloc[(page-1)*q_per_page : page*q_per_page]
    st.caption(f"篩選出 {total_q} 題，顯示第 {page} 頁")
else:
    st.success("🎉 目前此條件下已無題目！")
    df_page = pd.DataFrame()

# ==========================================
# ✍️ 測驗主畫面
# ==========================================
marked_df = load_user_records("marks")

for _, row in df_page.iterrows():
    q_key = f"{subject}_{row['年度-期別']}_{row['題號']}"
    str_key = f"{row['年度-期別']}_{row['題號']}"
    
    with st.container(border=True):
        col_q, col_mark = st.columns([8, 2])
        col_q.markdown(f"#### 第 {row['題號']} 題 ({row['年度-期別']})")
        
        # 標記功能
        is_m = ((marked_df['user_id'] == str(u_id)) & 
                (marked_df['年度-期別'] == str(row['年度-期別'])) & 
                (marked_df['題號'] == str(row['題號']))).any()
        
        if col_mark.button("🌟 已標記" if is_m else "☆ 標記", key=f"mark_{q_key}"):
            save_record("marks", u_id, subject, row['年度-期別'], row['題號'], "remove" if is_m else "add")
            st.rerun()

        render_content(row['題目內容'])
        if pd.notna(row['圖片路徑']) and ".png" in str(row['圖片路徑']):
            render_content(row['圖片路徑'])

        user_choice = st.radio("作答：", ["A", "B", "C", "D"], key=f"radio_{q_key}", index=None, horizontal=True)
        for o in ["A", "B", "C", "D"]:
            st.write(f"**({o})**")
            render_content(row[f'選項 {o}'])

        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button("送出答案", key=f"sub_{q_key}"):
            if user_choice == str(row['正確答案']):
                st.success("✅ 正確！")
                save_record("history", u_id, subject, row['年度-期別'], row['題號'], "add")
                # 關鍵：加入暫存清單，這題就不會在本頁立即消失
                st.session_state['just_answered_correct'].append(str_key)
            elif user_choice is None:
                st.warning("請先選擇一個選項。")
            else:
                st.error(f"❌ 錯誤！正確答案：{row['正確答案']}")
                save_record("wrong", u_id, subject, row['年度-期別'], row['題號'], "add")

        if c2.button("💡 AI 詳解", key=f"ai_{q_key}"):
            if model:
                with st.spinner("AI 老師分析中..."):
                    try:
                        p = f"解析放射師國考題：\n題目：{row['題目內容']}\n選項：(A){row['選項 A']} (B){row['選項 B']} (C){row['選項 C']} (D){row['選項 D']}\n正確答案是 {row['正確答案']}。"
                        resp = model.generate_content(p)
                        st.info(resp.text)
                    except Exception as ai_e:
                        st.error(f"AI 回應失敗，請確認 API 啟用狀態。錯誤：{ai_e}")
            else:
                st.error("請確認 Secrets 中的 GEMINI_API_KEY 是否正確。")
