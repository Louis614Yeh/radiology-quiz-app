import streamlit as st
import pandas as pd
import os
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection # 🌟 新增這行

# ==========================================
# ⚙️ 初始設定與 AI 配置 (保留你原本的設定，建議模型可改為 gemini-3.1-pro)
# ==========================================

# ==========================================
# ⚙️ 初始設定與 AI 配置
# ==========================================
st.set_page_config(page_title="放射師國考刷題神器 V3.7", layout="wide")

try:
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"].strip())
        model = genai.GenerativeModel('gemini-3.1-flash') 
    else:
        st.warning("⚠️ 未偵測到 API Key，請至 Streamlit Secrets 設定。")
        model = None
except Exception as e:
    st.error(f"AI 配置出錯：{e}")
    model = None
    
# ==========================================
# 📂 建立 Google Sheets 連線
# ==========================================
# 建立連線物件
conn = st.connection("gsheets", type=GSheetsConnection)

def load_user_records(data_type):
    """從 Google Sheets 讀取特定分頁的資料"""
    try:
        # data_type 會是 "history", "wrong", "marks", "progress" 其中之一
        df = conn.read(worksheet=data_type, usecols=list(range(4))) 
        return df.dropna(how="all").astype(str)
    except Exception as e:
        st.error(f"讀取 {data_type} 失敗：{e}")
        return pd.DataFrame()

def save_record(data_type, user_id, subject, year, q_num, action="add"):
    """寫入資料到 Google Sheets"""
    df = load_user_records(data_type)
    u, s, y, q = str(user_id), str(subject), str(year), str(q_num)
    mask = (df['user_id'] == u) & (df['科目'] == s) & (df['年度-期別'] == y) & (df['題號'] == q)
    
    if action == "add" and not df[mask].any().any():
        new_row = pd.DataFrame([[u, s, y, q]], columns=df.columns)
        df = pd.concat([df, new_row], ignore_index=True)
    elif action == "remove":
        df = df[~mask]
        
    # 覆寫回 Google Sheets
    conn.update(worksheet=data_type, data=df)

# ==========================================
# 🧠 閃卡進度記憶邏輯 (取代原本的分頁器)
# ==========================================
# 讀取當前使用者的進度
progress_df = load_user_records("progress")
current_prog_mask = (progress_df['user_id'] == str(u_id)) & (progress_df['科目'] == subject)

# 初始化 st.session_state 裡的題號索引
if 'current_q_index' not in st.session_state:
    if current_prog_mask.any():
        # 如果雲端有進度，抓取雲端進度
        st.session_state['current_q_index'] = int(progress_df[current_prog_mask]['current_index'].values[0])
    else:
        # 如果是第一次練這個科目，從第 0 題開始
        st.session_state['current_q_index'] = 0

def next_question():
    """切換到下一題，並將進度存回 Google Sheets"""
    st.session_state['current_q_index'] += 1
    
    # 更新進度表
    prog_df = load_user_records("progress")
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
# 確保索引不會超出題庫總數
total_q = len(df_view)

if total_q > 0:
    # 防止索引越界
    if st.session_state['current_q_index'] >= total_q:
        st.success("🎉 太神啦！本科目目前篩選的題目你已經全部刷完了！")
        if st.button("🔄 重新開始"):
            st.session_state['current_q_index'] = 0
            st.rerun()
    else:
        # 🟢 只抓取當前這 "1" 題的資料
        row = df_view.iloc[st.session_state['current_q_index']]
        q_key = f"{subject}_{row['年度-期別']}_{row['題號']}"
        
        st.progress((st.session_state['current_q_index'] + 1) / total_q, text=f"進度：{st.session_state['current_q_index'] + 1} / {total_q} 題")
        
        with st.container(border=True):
            col_q, col_mark = st.columns([8, 2])
            col_q.markdown(f"#### 第 {row['題號']} 題 ({row['年度-期別']})")
            
            # 標記按鈕邏輯
            marked_df = load_user_records("marks")
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

            # AI 詳解維持原樣...
            
            # 🌟 新增：下一題按鈕 (綁定進度儲存功能)
            if c3.button("➡️ 下一題", type="primary"):
                next_question()
                st.rerun()
else:
    st.success("🎉 目前已無題目！太棒了！")
