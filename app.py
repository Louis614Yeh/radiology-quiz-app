import streamlit as st
import pandas as pd
import os
import google.generativeai as genai

# ==========================================
# ⚙️ 初始設定與 AI 配置
# ==========================================
st.set_page_config(page_title="放射師國考刷題神器 V3.4", layout="wide")

try:
    GOOGLE_API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash') 
except Exception as e:
    st.error("⚠️ 無法連線 AI。請確認 Streamlit 後台 Secrets 設定。")
    st.stop()

# ==========================================
# 📂 資料處理函數 (加入防呆機制)
# ==========================================
@st.cache_data
def load_quiz_data():
    try:
        excel_file = pd.ExcelFile('exam_db.xlsx') 
        db = {sheet: excel_file.parse(sheet) for sheet in excel_file.sheet_names}
        return db
    except:
        st.error("找不到題庫檔 `exam_db.xlsx`。")
        st.stop()

def load_user_records(data_type):
    """【升級】自動檢查欄位，若舊檔案格式不對則自動重建，防止 KeyError"""
    file = f"user_{data_type}.csv"
    expected_cols = ['user_id', '科目', '年度-期別', '題號']
    
    if os.path.exists(file):
        try:
            df = pd.read_csv(file).astype(str)
            # 檢查是否包含所有必須的欄位
            if all(col in df.columns for col in expected_cols):
                return df
            else:
                st.toast(f"⚠️ 發現舊版 {data_type} 紀錄檔，已自動重置欄位格式。")
        except:
            pass # 讀取失敗也當作空檔案處理
            
    return pd.DataFrame(columns=expected_cols)

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
            st.warning(f"找不到圖片：{content_str}")
    elif content_str != "nan":
        st.write(content_str)

# ==========================================
# 📱 介面控制
# ==========================================
st.sidebar.title("🩺 放射師專屬題庫")
u_id = st.sidebar.selectbox("切換使用者：", ["614", "941", "Guest"])

quiz_db = load_quiz_data()
subject = st.sidebar.radio("選擇科目：", list(quiz_db.keys()))
df_full = quiz_db[subject].copy()

df_full['年度-期別'] = df_full['年度-期別'].astype(str)
df_full['題號'] = df_full['題號'].astype(str)

valid_years = sorted([y for y in df_full['年度-期別'].unique() if y.lower() != 'nan'])
selected_year = st.sidebar.selectbox("選擇年度：", ["全部年度"] + valid_years)

mode = st.sidebar.selectbox("模式：", ["一般練習", "錯題重刷", "標記題庫"])
st.sidebar.divider()
hide_done = st.sidebar.checkbox("✅ 隱藏已答對題目", value=True)

# ==========================================
# 🧠 題目過濾與重複項排除
# ==========================================
df_view = df_full.copy()
if selected_year != "全部年度":
    df_view = df_view[df_view['年度-期別'] == selected_year]

if hide_done:
    history = load_user_records("history")
    u_hist = history[history['user_id'] == str(u_id)]
    df_view = df_view.merge(u_hist[['年度-期別', '題號']], on=['年度-期別', '題號'], how='left', indicator=True)
    df_view = df_view[df_view['_merge'] == 'left_only'].drop(columns=['_merge'])

if mode != "一般練習":
    rec_t = "wrong" if mode == "錯題重刷" else "marks"
    recs = load_user_records(rec_t)
    u_recs = recs[recs['user_id'] == str(u_id)]
    df_view = df_view.merge(u_recs[['年度-期別', '題號']], on=['年度-期別', '題號'])

df_view = df_view.drop_duplicates(subset=['年度-期別', '題號'])

# --- 分頁器 ---
q_per_page = 5 
total_q = len(df_view)
total_pages = max((total_q - 1) // q_per_page + 1, 1)

if total_q > 0:
    page = st.sidebar.number_input(f"頁數 (共 {total_pages} 頁)", 1, total_pages, 1)
    df_page = df_view.iloc[(page-1)*q_per_page : page*q_per_page]
else:
    st.success("🎉 目前已無題目！請嘗試切換年度或模式。")
    df_page = pd.DataFrame()

# ==========================================
# ✍️ 測驗主畫面渲染
# ==========================================
marked_df = load_user_records("marks")

for _, row in df_page.iterrows():
    q_key = f"{subject}_{row['年度-期別']}_{row['題號']}"
    
    with st.container(border=True):
        col_q, col_mark = st.columns([8, 2])
        col_q.markdown(f"#### 第 {row['題號']} 題 ({row['年度-期別']})")
        
        is_m = ((marked_df['user_id'] == str(u_id)) & 
                (marked_df['年度-期別'] == row['年度-期別']) & 
                (marked_df['題號'] == row['題號'])).any()
        
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
                if hide_done: st.rerun()
            elif user_choice is None:
                st.warning("請先選擇一個選項。")
            else:
                st.error(f"❌ 錯誤！正確答案：{row['正確答案']}")
                save_record("wrong", u_id, subject, row['年度-期別'], row['題號'], "add")

        if c2.button("💡 AI 詳解", key=f"ai_{q_key}"):
            with st.spinner("AI 老師分析中..."):
                try:
                    prompt = f"請詳細解析放射師國考題，用繁體中文回答：\n題目：{row['題目內容']}\n選項：(A){row['選項 A']} (B){row['選項 B']} (C){row['選項 C']} (D){row['選項 D']}\n正確答案是 {row['正確答案']}。"
                    response = model.generate_content(prompt)
                    st.info(response.text)
                except Exception as e:
                    st.error(f"AI 服務目前無法回應：{e}")
