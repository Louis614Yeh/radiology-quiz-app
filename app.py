import streamlit as st
import pandas as pd
import os
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection

# ==========================================
# ⚙️ 初始設定與 AI 配置
# ==========================================
st.set_page_config(page_title="放射師國考刷題神器 V4.4", layout="wide")

try:
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"].strip())
        model = genai.GenerativeModel('gemini-3.1-pro') 
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

# 🌟 V4.4 修復：初始化「這回合答對」的保護傘
if 'answered_this_round' not in st.session_state:
    st.session_state['answered_this_round'] = []

def clear_cache():
    if 'current_q_index' in st.session_state:
        del st.session_state['current_q_index']
    # 切換科目時，清空保護傘
    st.session_state['answered_this_round'] = []

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
    session_key = f"db_{data_type}"
    if session_key not in st.session_state:
        try:
            df = conn.read(worksheet=data_type, ttl=600) 
            df = df.dropna(how="all").astype(str)
            for col in df.columns:
                df[col] = df[col].str.replace(r'\.0$', '', regex=True).str.strip()
            st.session_state[session_key] = df
        except Exception as e:
            st.error(f"⚠️ 讀取 {data_type} 失敗！可能是 Google API 暫時阻擋，請稍後重試。")
            return pd.DataFrame()
    return st.session_state[session_key].copy()

def save_record(data_type, user_id, subject, year, q_num, action="add"):
    df = load_user_records(data_type)
    u, s, y, q = str(user_id), str(subject), str(year), str(q_num)
    
    if df.empty or not all(col in df.columns for col in ['user_id', '科目', '年度-期別', '題號']):
        df = pd.DataFrame(columns=['user_id', '科目', '年度-期別', '題號'])

    mask = (df['user_id'] == u) & (df['科目'] == s) & (df['年度-期別'] == y) & (df['題號'] == q)
    
    changed = False
    if action == "add" and not mask.any():
        new_row = pd.DataFrame([[u, s, y, q]], columns=df.columns)
        df = pd.concat([df, new_row], ignore_index=True)
        changed = True
    elif action == "remove" and mask.any():
        df = df[~mask]
        changed = True
        
    if changed:
        st.session_state[f"db_{data_type}"] = df
        try:
            conn.update(worksheet=data_type, data=df)
            st.cache_data.clear() 
        except Exception as e:
            st.toast("⚠️ 點擊過快，雲端同步失敗，但不影響目前網頁進度！")

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
u_id = st.sidebar.selectbox("切換使用者：", ["614", "941", "Guest"], on_change=clear_cache)

quiz_db = load_quiz_data()
subject = st.sidebar.radio("選擇科目：", list(quiz_db.keys()), on_change=clear_cache)
df_full = quiz_db[subject].copy()

valid_years = sorted([y for y in df_full['年度-期別'].unique() if str(y).lower() != 'nan'])
selected_year = st.sidebar.selectbox("選擇年度：", ["全部年度"] + valid_years, on_change=clear_cache)

mode = st.sidebar.selectbox("模式：", ["一般練習", "錯題重刷", "標記題庫"], on_change=clear_cache)
st.sidebar.divider()
hide_done = st.sidebar.checkbox("✅ 隱藏已答對題目", value=True, on_change=clear_cache)

if st.sidebar.button("🗑️ 清除當前使用者進度"):
    for t in ["history", "wrong", "marks", "progress"]:
        df = load_user_records(t)
        if not df.empty and 'user_id' in df.columns:
            df = df[df['user_id'] != str(u_id)]
            st.session_state[f"db_{t}"] = df  
            try:
                conn.update(worksheet=t, data=df) 
            except:
                pass
    st.cache_data.clear()
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
        u_hist = history[history['user_id'] == str(u_id)].copy() # 🌟 加上 .copy() 避免警告
        if not u_hist.empty:
            # 🌟 V4.4 修復：保護「這回合」剛答對的題目，不要把它們從清單刪除，避免跳題位移
            u_hist['q_key_str'] = u_hist['年度-期別'].astype(str) + "_" + u_hist['題號'].astype(str)
            u_hist_to_hide = u_hist[~u_hist['q_key_str'].isin(st.session_state['answered_this_round'])]
            
            df_view = df_view.merge(u_hist_to_hide[['年度-期別', '題號']], on=['年度-期別', '題號'], how='left', indicator=True)
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
df_view = df_view.reset_index(drop=True)

# ==========================================
# 🧠 閃卡進度記憶與切換邏輯 
# ==========================================
progress_df = load_user_records("progress")

if progress_df.empty or 'user_id' not in progress_df.columns:
    progress_df = pd.DataFrame(columns=['user_id', '科目', 'current_index'])

current_prog_mask = (progress_df['user_id'] == str(u_id)) & (progress_df['科目'] == subject)

if 'current_q_index' not in st.session_state:
    if current_prog_mask.any():
        saved_index = int(float(progress_df[current_prog_mask]['current_index'].values[0]))
        st.session_state['current_q_index'] = saved_index
    else:
        st.session_state['current_q_index'] = 0

def change_question(delta):
    new_index = st.session_state['current_q_index'] + delta
    if new_index < 0:
        new_index = 0
        
    st.session_state['current_q_index'] = new_index
    
    prog_df = load_user_records("progress")
    if prog_df.empty or 'user_id' not in prog_df.columns:
        prog_df = pd.DataFrame(columns=['user_id', '科目', 'current_index'])
        
    mask = (prog_df['user_id'] == str(u_id)) & (prog_df['科目'] == subject)
    
    if mask.any():
        prog_df.loc[mask, 'current_index'] = str(new_index)
    else:
        new_prog = pd.DataFrame([[str(u_id), subject, str(new_index)]], columns=['user_id', '科目', 'current_index'])
        prog_df = pd.concat([prog_df, new_prog], ignore_index=True)
        
    st.session_state["db_progress"] = prog_df
    
    try:
        conn.update(worksheet="progress", data=prog_df)
        st.cache_data.clear()
    except Exception:
        pass 

# ==========================================
# ✍️ 測驗主畫面 
# ==========================================
total_q = len(df_view)

if total_q > 0:
    # 防呆修正：如果目前進度超過了總題數，強制回到第0題
    if st.session_state['current_q_index'] >= total_q:
        st.session_state['current_q_index'] = 0  
        
    row = df_view.iloc[st.session_state['current_q_index']]
    q_key = f"{subject}_{row['年度-期別']}_{row['題號']}"
    str_key = f"{row['年度-期別']}_{row['題號']}" # 給回合保護傘用的 Key
    
    st.progress((st.session_state['current_q_index'] + 1) / total_q, text=f"進度：{st.session_state['current_q_index'] + 1} / {total_q} 題")
    
    with st.container(border=True):
        col_q, col_mark = st.columns([8, 2])
        col_q.markdown(f"#### 第 {row['題號']} 題 ({row['年度-期別']})")
        
        marked_df = load_user_records("marks")
        is_m = False
        if not marked_df.empty and 'user_id' in marked_df.columns:
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

        st.divider()
        
        c1, c2, c3, c4 = st.columns([1.5, 1.5, 1, 1])
        
        if c1.button("送出答案", key=f"sub_{q_key}"):
            if user_choice == str(row['正確答案']):
                st.success("✅ 正確！")
                save_record("history", u_id, subject, row['年度-期別'], row['題號'], "add")
                
                # 🌟 V4.4 修復：將答對的題目加入保護傘，避免立刻跳題
                if str_key not in st.session_state['answered_this_round']:
                    st.session_state['answered_this_round'].append(str_key)
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

        # 🌟 V4.4 修復：加入專屬的 key (prev_{q_key} 和 next_{q_key})，徹底消滅幽靈連點
        is_first_q = (st.session_state['current_q_index'] == 0)
        if c3.button("⬅️ 上一題", key=f"prev_{q_key}", disabled=is_first_q):
            change_question(-1)
            st.rerun()

        if c4.button("➡️ 下一題", key=f"next_{q_key}", type="primary"):
            change_question(1)
            st.rerun()
else:
    st.success("🎉 目前已無題目！太棒了！")
