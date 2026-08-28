import streamlit as st
import pandas as pd
import datetime
import requests
import os
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. 基本設定與參數
# ==========================================
ATTENDANCE_MODES = ["實體出席", "線上出席"]
VERSES_FILE = "verses.csv"
ADMIN_PASSWORD = "youngerbible"  # 輔導後台密碼
LINE_NOTIFY_TOKEN = ""   # 可在此填入您的 LINE Notify Token

SHEET_YOUTH_ATTENDANCE = "youth_attendance"
SHEET_YOUTH_MEMBERS = "youth_members"

# 設定開辦第一週（第 1 次）：2026 年第 34 週
START_WEEK_NUMBER = 34
START_YEAR = 2026

st.set_page_config(page_title="青少年靈修禱告小組簽到系統", page_icon="📖", layout="wide")

# ==========================================
# 2. Google Sheets 連線與資料存取
# ==========================================
def get_gspread_client():
    """建立 GCP Service Account 連線"""
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    if "gcp_service_account" not in st.secrets:
        raise KeyError("Secrets 中缺少 'gcp_service_account' 設定！")
        
    creds_dict = dict(st.secrets["gcp_service_account"])
    
    if "private_key" in creds_dict:
        pk = str(creds_dict["private_key"]).strip()
        if (pk.startswith('"') and pk.endswith('"')) or (pk.startswith("'") and pk.endswith("'")):
            pk = pk[1:-1]
        pk = pk.replace("\\n", "\n")
        creds_dict["private_key"] = pk.strip()
        
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

def load_data():
    """從 Google Sheets 讀取簽到紀錄"""
    try:
        client = get_gspread_client()
        sheet_name = st.secrets.get("spreadsheet_name", "Church_Attendance")
        sheet = client.open(sheet_name).worksheet(SHEET_YOUTH_ATTENDANCE)
        
        rows = sheet.get_all_values()
        if not rows or len(rows) <= 1:
            return pd.DataFrame(columns=["week_key", "group_name", "signer", "mode", "timestamp"])
            
        header = [str(h).strip().lower() for h in rows[0]]
        data = rows[1:]
        df = pd.DataFrame(data, columns=header)
        
        rename_map = {}
        for col in df.columns:
            if "week" in col: rename_map[col] = "week_key"
            elif "group" in col or "組別" in col: rename_map[col] = "group_name"
            elif "signer" in col or "簽到" in col or "代表" in col: rename_map[col] = "signer"
            elif "mode" in col or "方式" in col: rename_map[col] = "mode"
            elif "time" in col or "時間" in col: rename_map[col] = "timestamp"
            
        df = df.rename(columns=rename_map)
        
        for col in ["week_key", "group_name", "signer", "mode", "timestamp"]:
            if col not in df.columns:
                df[col] = "未知" if col == "signer" else ""
            else:
                df[col] = df[col].astype(str).str.strip()
        return df
    except Exception:
        return pd.DataFrame(columns=["week_key", "group_name", "signer", "mode", "timestamp"])

def save_or_update_record(week_key, group_name, signer, mode, timestamp):
    """新增或更新簽到紀錄至 Google Sheets"""
    try:
        client = get_gspread_client()
        sheet_name = st.secrets.get("spreadsheet_name", "Church_Attendance")
        sheet = client.open(sheet_name).worksheet(SHEET_YOUTH_ATTENDANCE)
        rows = sheet.get_all_values()
        
        match_row_idx = None
        if len(rows) > 1:
            for idx, row in enumerate(rows[1:], start=2):
                if len(row) >= 2 and str(row[0]).strip() == str(week_key).strip() and str(row[1]).strip() == str(group_name).strip():
                    match_row_idx = idx
                    break
                
        if match_row_idx:
            sheet.update(f"A{match_row_idx}:E{match_row_idx}", [[week_key, group_name, signer, mode, timestamp]])
        else:
            sheet.append_row([week_key, group_name, signer, mode, timestamp])
        return True
    except Exception as e:
        st.error(f"寫入 Google Sheet 失敗：{e}")
        return False

def load_youth_groups_and_members():
    """從 youth_members 頁籤載入組別與成員對照表"""
    try:
        client = get_gspread_client()
        sheet_name = st.secrets.get("spreadsheet_name", "Church_Attendance")
        sheet = client.open(sheet_name).worksheet(SHEET_YOUTH_MEMBERS)
        
        rows = sheet.get_all_values()
        if not rows or len(rows) <= 1:
            return {}, "頁籤內無資料內容"

        groups_dict = {}
        for row in rows[1:]:
            if len(row) >= 1:
                g_name = str(row[0]).strip()
                m_list = str(row[1]).strip() if len(row) >= 2 else ""
                if g_name:
                    groups_dict[g_name] = m_list
                    
        if groups_dict:
            return groups_dict, None
        else:
            return {}, "未找到有效組別名稱"
    except Exception as e:
        return {}, f"連線或讀取失敗 ({e})"

# ==========================================
# 3. 輔助工具函數
# ==========================================
def send_line_notify(message):
    if not LINE_NOTIFY_TOKEN:
        return
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": f"Bearer {LINE_NOTIFY_TOKEN}"}
    try:
        requests.post(url, headers=headers, data={"message": message}, timeout=5)
    except Exception as e:
        print(f"LINE 推播失敗: {e}")

def get_weekly_verse(week_num):
    fallback = {
        "verse": "「你的話是我腳前的燈，是我路上的光。」",
        "ref": "詩篇 119:105",
        "encouragement": "堅持每週靈修分享，讓上帝的話語成為彼此的亮光與祝福！"
    }
    if os.path.exists(VERSES_FILE):
        try:
            verses_df = pd.read_csv(VERSES_FILE)
            if not verses_df.empty:
                idx = (week_num - 1) % len(verses_df)
                row = verses_df.iloc[idx]
                return {
                    "verse": str(row["verse"]),
                    "ref": str(row["ref"]),
                    "encouragement": str(row["encouragement"])
                }
        except Exception as e:
            print(f"讀取經文庫失敗: {e}")
    return fallback

def get_session_info(week_key_str):
    """計算指定 week_key 是第幾次靈修小組"""
    try:
        parts = week_key_str.split("-W")
        w_num = int(parts[1])
        s_num = (w_num - START_WEEK_NUMBER) + 1
        return max(1, s_num)
    except Exception:
        return 1

def get_week_range_str_from_key(week_key_str):
    """從 2026-W35 這種 week_key 計算出當週【週日 ～ 週六】的日期字串"""
    try:
        year, w_str = week_key_str.split("-W")
        w_num = int(w_str)
        mon_date = datetime.date.fromisocalendar(int(year), w_num, 1)
        sun_date = mon_date - datetime.timedelta(days=1)
        sat_date = sun_date + datetime.timedelta(days=6)
        return f"{sun_date.strftime('%Y/%m/%d')} (日) ~ {sat_date.strftime('%Y/%m/%d')} (六)"
    except Exception:
        return "未知日期區間"

# ==========================================
# 4. 主介面邏輯
# ==========================================
st.title("📖 青少年靈修禱告小組簽到系統")

now = datetime.datetime.now()

# 計算目前這週【星期日 ～ 星期六】區間
idx_sun = (now.weekday() + 1) % 7
start_of_week = now - datetime.timedelta(days=idx_sun)
end_of_week = start_of_week + datetime.timedelta(days=6)
week_range_str = f"{start_of_week.strftime('%Y/%m/%d')} (日) ~ {end_of_week.strftime('%Y/%m/%d')} (六)"

week_number = now.isocalendar()[1]
current_week_key = f"{now.year}-W{week_number:02d}"
today_str = now.strftime("%Y年%m月%d日")

current_session_num = get_session_info(current_week_key)

groups_dict, sheet_err = load_youth_groups_and_members()

if not groups_dict:
    groups_dict = {"大衛": "預設組員", "亞伯拉罕": "預設組員"}
    if sheet_err:
        st.warning(f"⚠️ 讀取 youth_members 狀態：{sheet_err}")

GROUPS = list(groups_dict.keys())
df_records = load_data()
signed_groups_this_week = df_records[df_records["week_key"] == current_week_key]["group_name"].tolist() if not df_records.empty else []

tab1, tab2 = st.tabs(["✍️ 青少年簽到", "🔒 輔導快速管理後台"])

# ------------------------------------------
# TAB 1: 前台 - 青少年當週簽到
# ------------------------------------------
with tab1:
    verse_info = get_weekly_verse(week_number)
    
    st.write(f"📅 **今天是 {today_str}（【第 {current_session_num} 次】靈修禱告小組）**")
    
    # 1. 經文直接展開（不設滾輪，順暢閱讀）
    st.markdown(f"📖 **本週經文：{verse_info['ref']}**")
    formatted_verse = verse_info['verse'].replace('\\n', '\n\n')
    st.markdown(formatted_verse)
    
    st.write("") # 稍微留空
    
    # 2. 經文背景+默想：設定專屬對話框與內部滾輪，高度固定 180px 適合手機
    encouragement_text = verse_info['encouragement'].replace('\n', '<br>').replace('\\n', '<br>')
    st.markdown(f"""
        <div style="
            height: 180px; 
            overflow-y: auto; 
            border: 1px solid #b3d8f5; 
            border-left: 5px solid #2196F3;
            border-radius: 8px; 
            padding: 12px 15px; 
            background-color: #f0f7ff;
            color: #1e3a8a;
            line-height: 1.7;
            font-size: 14.5px;
            margin-bottom: 15px;
            -webkit-overflow-scrolling: touch;
        ">
            <strong style="font-size: 15px;">💡 經文背景默想與分享：</strong><br><br>
            {encouragement_text}
        </div>
    """, unsafe_allow_html=True)
    
    st.subheader(f"📅 本週組別簽到區間：{week_range_str}")
    selected_group = st.selectbox("請選擇您的組別：", GROUPS)
    
    members_text = groups_dict.get(selected_group, "尚無成員資料")
    st.markdown(f"👥 **{selected_group} 全組成員**：{members_text}")
    st.write("")
    
    if selected_group in signed_groups_this_week:
        record = df_records[(df_records["week_key"] == current_week_key) & (df_records["group_name"] == selected_group)].iloc[0]
        st.success(f"🎉 **{selected_group}** 本週（第 {current_session_num} 次）已完成簽到！")
        st.info(f"👤 **簽到代表**：{record.get('signer', '未知')}\n\n📌 **出席方式**：{record['mode']}\n\n⏰ **完成時間**：{record['timestamp']}")
        st.button("完成簽到（本週已登記）", disabled=True, use_container_width=True)
    else:
        raw_members_text = groups_dict.get(selected_group, "")
        clean_text = raw_members_text.replace("，", ",").replace("、", ",").replace("．", ",").replace(".", ",")
        member_list = [m.strip() for m in clean_text.split(",") if m.strip()]
        
        if not member_list:
            member_list = ["尚無成員資料"]

        col1, col2 = st.columns(2)
        with col1:
            signer_name = st.selectbox("請選擇『您』的姓名（代表簽到人）：", member_list)
        with col2:
            selected_mode = st.selectbox("請選擇聚會方式：", ATTENDANCE_MODES)
            
        if st.button("🚀 確認送出簽到", type="primary", use_container_width=True):
            if signer_name == "尚無成員資料":
                st.error("⚠️ 該組尚無成員資料，無法完成簽到！")
            else:
                timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if save_or_update_record(current_week_key, selected_group, signer_name, selected_mode, timestamp_str):
                    line_message = (
                        f"\n🎉【靈修小組簽到成功】\n"
                        f"📌 組別：{selected_group}（第 {current_session_num} 次）\n"
                        f"👤 簽到代表：{signer_name}\n"
                        f"💡 聚會方式：{selected_mode}\n"
                        f"⏰ 時間：{timestamp_str}\n"
                        f"📈 本週完成率：{len(signed_groups_this_week) + 1}/{len(GROUPS)} 組"
                    )
                    send_line_notify(line_message)
                    st.success(f"✅ {selected_group}（簽到代表：{signer_name}）簽到成功！")
                    st.rerun()

# ------------------------------------------
# TAB 2: 後台 - 輔導高效管理專區
# ------------------------------------------
with tab2:
    st.subheader("🔒 輔導管理與快速查詢後台")
    pwd = st.text_input("請輸入輔導管理密碼：", type="password")
    
    if pwd == ADMIN_PASSWORD:
        st.success("身份驗證成功！")
        sub_tab1, sub_tab2, sub_tab3, sub_tab4 = st.tabs(["⚡ 快速補簽工作台", "📊 歷程矩陣與檢視範圍", "🔍 單組深度查詢", "📜 52週經文庫預覽"])
        
        with sub_tab1:
            st.markdown("### ⚡ 指定次數/週別手動補簽")
            
            # 強制確保【第 1 次（START_WEEK_NUMBER）】一直到【當週】都會顯示在選單中
            generated_weeks = [f"{START_YEAR}-W{w:02d}" for w in range(START_WEEK_NUMBER, week_number + 1)]
            existing_weeks = df_records["week_key"].tolist() if not df_records.empty else []
            all_weeks = sorted(list(set(generated_weeks + existing_weeks)), reverse=True)
            
            week_options_map = {w: f"{w} （第 {get_session_info(w)} 次小組聚會）" for w in all_weeks}
            
            col_w, col_d = st.columns(2)
            with col_w:
                target_week = st.selectbox("1. 請選擇補簽次數/週別：", options=all_weeks, format_func=lambda x: week_options_map[x])
                target_session_num = get_session_info(target_week)
            with col_d:
                target_week_range = get_week_range_str_from_key(target_week)
                st.text_input("2. 該次聚會週區間（日~六）：", value=target_week_range, disabled=True)

            target_week_records = df_records[df_records["week_key"] == target_week] if not df_records.empty else pd.DataFrame()
            signed_in_week = target_week_records["group_name"].tolist() if not target_week_records.empty else []
            
            col_left, col_right = st.columns(2)
            with col_left:
                st.write(f"🟢 **【第 {target_session_num} 次】已完成簽到組別**")
                if not target_week_records.empty:
                    for _, row in target_week_records.iterrows():
                        st.text(f"• {row['group_name']} | 代表: {row.get('signer', '未知')} | {row['mode']} | {row['timestamp']}")
                else:
                    st.info("該週尚無任何簽到紀錄。")
                    
            with col_right:
                st.write(f"🔴 **【第 {target_session_num} 次】未簽到組別 (輔導補簽)**")
                missing_groups = [g for g in GROUPS if g not in signed_in_week]
                if missing_groups:
                    for g in missing_groups:
                        c_group, c_mode, c_btn = st.columns([2, 2, 2])
                        c_group.write(f"**{g}**")
                        mode_selected = c_mode.selectbox("方式", ATTENDANCE_MODES, key=f"mode_{target_week}_{g}")
                        if c_btn.button("一鍵補簽", key=f"btn_{target_week}_{g}"):
                            formatted_ts = f"輔導補簽 (區間: {target_week_range})"
                            save_or_update_record(target_week, g, "輔導補簽", mode_selected, formatted_ts)
                            st.toast(f"✅ 已成功為 {g} 完成『第 {target_session_num} 次』補簽！")
                            st.rerun()
                else:
                    st.success(f"🎉 第 {target_session_num} 次小組聚會所有組別皆已完成簽到！")

        with sub_tab2:
            st.markdown("### 📊 跨週出席矩陣表")
            if not df_records.empty:
                range_option = st.radio("選擇顯示範圍：", ["最近 4 次", "最近 8 次", "全歷史紀錄"], horizontal=True)
                
                pivot_df = df_records.pivot(index="group_name", columns="week_key", values="mode")
                pivot_df = pivot_df.reindex(GROUPS).fillna("❌ 未簽到")
                
                rename_cols = {col: f"第 {get_session_info(col)} 次 ({col})" for col in pivot_df.columns}
                pivot_df = pivot_df.rename(columns=rename_cols)
                
                cols = list(pivot_df.columns)
                if range_option == "最近 4 次":
                    cols = cols[-4:]
                elif range_option == "最近 8 次":
                    cols = cols[-8:]
                    
                display_df = pivot_df[cols].copy()
                
                total_displayed = len(cols)
                if total_displayed > 0:
                    att_counts = (display_df != "❌ 未簽到").sum(axis=1)
                    display_df["出席次數"] = att_counts
                    display_df["出席率"] = (att_counts / total_displayed * 100).round(1).astype(str) + "%"
                
                display_df.insert(0, "成員名單", [groups_dict.get(g, "") for g in display_df.index])
                st.dataframe(display_df, use_container_width=True)
                
                csv = df_records.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 匯出完整歷史數據 (.csv)", data=csv, file_name="youth_attendance_full.csv", mime="text/csv")
            else:
                st.info("目前無歷史紀錄。")

        with sub_tab3:
            st.markdown("### 🔍 單一組別歷史點名冊")
            search_group = st.selectbox("請選擇欲調閱資料的組別：", GROUPS)
            st.info(f"👥 **{search_group} 成員名單**：{groups_dict.get(search_group, '無')}")
            
            group_df = df_records[df_records["group_name"] == search_group].sort_values(by="week_key", ascending=False) if not df_records.empty else pd.DataFrame()
            if not group_df.empty:
                group_df["session_display"] = group_df["week_key"].apply(lambda x: f"第 {get_session_info(x)} 次 ({x})")
                st.write(f"**{search_group}** 的歷史簽到紀錄（共 {len(group_df)} 次）：")
                st.dataframe(group_df[["session_display", "signer", "mode", "timestamp"]].rename(columns={
                    "session_display": "聚會次數/週別", "signer": "簽到代表", "mode": "聚會方式", "timestamp": "簽到時間/補簽註記"
                }), hide_index=True, use_container_width=True)
            else:
                st.info(f"{search_group} 目前尚無任何簽到紀錄。")

        with sub_tab4:
            st.markdown("### 📜 52 週經文庫檢視")
            if os.path.exists(VERSES_FILE):
                v_df = pd.read_csv(VERSES_FILE)
                st.dataframe(v_df, use_container_width=True, hide_index=True)
            else:
                st.warning("目前找不到 `verses.csv` 檔案，系統正使用預設備用經文。")

    elif pwd != "":
        st.error("密碼錯誤，請重新輸入！")
