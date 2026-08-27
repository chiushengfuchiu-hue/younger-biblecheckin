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
ADMIN_PASSWORD = "bible"  # 輔導後台密碼
LINE_NOTIFY_TOKEN = ""   # 可在此填入您的 LINE Notify Token

# Google Sheets 頁籤名稱設定
SHEET_YOUTH_ATTENDANCE = "youth_attendance"
SHEET_YOUTH_MEMBERS = "youth_members"

st.set_page_config(page_title="青少年讀經小組簽到系統", page_icon="📖", layout="wide")

# ==========================================
# 2. Google Sheets 連線與資料存取
# ==========================================
def get_gspread_client():
    """建立 GCP Service Account 連線"""
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "private_key" in creds_dict:
        pk = creds_dict["private_key"].replace("\\n", "\n")
        if not pk.startswith("-----BEGIN PRIVATE KEY-----"):
            pk = "-----BEGIN PRIVATE KEY-----\n" + pk
        if not pk.endswith("-----END PRIVATE KEY-----"):
            pk = pk + "\n-----END PRIVATE KEY-----"
        creds_dict["private_key"] = pk.strip()
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

def load_data():
    """從 Google Sheets 讀取簽到紀錄"""
    try:
        client = get_gspread_client()
        sheet_name = st.secrets.get("spreadsheet_name", "Church_Attendance")
        sheet = client.open(sheet_name).worksheet(SHEET_YOUTH_ATTENDANCE)
        records = sheet.get_all_records()
        df = pd.DataFrame(records)
        
        if df.empty:
            return pd.DataFrame(columns=["week_key", "group_name", "signer", "mode", "timestamp"])
            
        # 補齊必要欄位避免舊格式問題
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
        records = sheet.get_all_records()
        
        # 檢查該週該組是否已經存在紀錄
        match_row_idx = None
        for idx, row in enumerate(records):
            if str(row.get("week_key")).strip() == str(week_key).strip() and str(row.get("group_name")).strip() == str(group_name).strip():
                match_row_idx = idx + 2  # 試算表第1列為標題列
                break
                
        if match_row_idx:
            # 更新已有列 (week_key, group_name, signer, mode, timestamp)
            sheet.update(f"A{match_row_idx}:E{match_row_idx}", [[week_key, group_name, f"{signer} (輔導更新)", mode, timestamp]])
        else:
            # 新增一列
            sheet.append_row([week_key, group_name, signer, mode, timestamp])
        return True
    except Exception as e:
        st.error(f"寫入 Google Sheet 失敗：{e}")
        return False

def load_youth_groups_and_members():
    """從 youth_members 頁籤載入組別與成員對照表"""
    default_groups = {
        "第一組": "小明、小華、小美",
        "第二組": "阿強、阿哲、小燕",
        "第三組": "組員G、組員H、組員I",
        "第四組": "組員J、組員K、組員L",
        "第五組": "組員M、組員N、組員O",
        "第六組": "組員P、組員Q、組員R"
    }
    try:
        client = get_gspread_client()
        sheet_name = st.secrets.get("spreadsheet_name", "Church_Attendance")
        sheet = client.open(sheet_name).worksheet(SHEET_YOUTH_MEMBERS)
        records = sheet.get_all_records()
        if records:
            groups_dict = {}
            for r in records:
                # 預期試算表欄位為 group_name 與 members
                g_name = str(r.get("group_name", r.get("組別", ""))).strip()
                m_list = str(r.get("members", r.get("組員名單", ""))).strip()
                if g_name:
                    groups_dict[g_name] = m_list
            if groups_dict:
                return groups_dict
    except Exception:
        pass
    return default_groups

# ==========================================
# 3. 輔助工具函數 (LINE / 經文)
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
        "encouragement": "堅持每週讀經，讓上帝的話語指引每一步！"
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

# ==========================================
# 4. 主介面邏輯
# ==========================================
st.title("📖 青少年讀經小組簽到系統")

now = datetime.datetime.now()
week_number = now.isocalendar()[1]
current_week_key = f"{now.year}-W{week_number:02d}"

# 載入動態組別名單與歷史數據
groups_dict = load_youth_groups_and_members()
GROUPS = list(groups_dict.keys())

df_records = load_data()
signed_groups_this_week = df_records[df_records["week_key"] == current_week_key]["group_name"].tolist()

tab1, tab2 = st.tabs(["✍️ 青少年簽到", "🔒 輔導快速管理後台"])

# ------------------------------------------
# TAB 1: 前台 - 青少年當週簽到
# ------------------------------------------
with tab1:
    # 週經文展示
    verse_info = get_weekly_verse(week_number)
    st.info(f"""
    📖 **本週亮光與勸勉（第 {week_number} 週 / `{current_week_key}`）**  
    *{verse_info['verse']}* —— **{verse_info['ref']}**  

    💡 **輔導小叮嚀**：{verse_info['encouragement']}
    """)
    
    st.subheader(f"📅 本週組別簽到")
    selected_group = st.selectbox("請選擇您的組別：", GROUPS)
    
    # 即時顯示選定組別的成員名單
    members_text = groups_dict.get(selected_group, "尚無成員資料")
    st.markdown(f"👥 **`{selected_group}` 組員名單**：`{members_text}`")
    st.write("")
    
    if selected_group in signed_groups_this_week:
        record = df_records[(df_records["week_key"] == current_week_key) & (df_records["group_name"] == selected_group)].iloc[0]
        st.success(f"🎉 **{selected_group}** 本週已完成簽到！")
        st.info(f"👤 **簽到代表**：{record.get('signer', '未知')}\n\n📌 **出席方式**：{record['mode']}\n\n⏰ **完成時間**：{record['timestamp']}")
        st.button("完成簽到（本週已登記）", disabled=True, use_container_width=True)
    else:
        col1, col2 = st.columns(2)
        with col1:
            signer_name = st.text_input("請輸入簽到人姓名 / 暱稱：", placeholder="例如：小明")
        with col2:
            selected_mode = st.selectbox("請選擇讀經方式：", ATTENDANCE_MODES)
            
        if st.button("🚀 確認送出簽到", type="primary", use_container_width=True):
            if not signer_name.strip():
                st.error("⚠️ 請輸入簽到人姓名後再送出！")
            else:
                timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if save_or_update_record(current_week_key, selected_group, signer_name.strip(), selected_mode, timestamp_str):
                    
                    line_message = (
                        f"\n🎉【讀經簽到成功】\n"
                        f"📌 組別：{selected_group}\n"
                        f"👤 簽到人：{signer_name.strip()}\n"
                        f"💡 方式：{selected_mode}\n"
                        f"⏰ 時間：{timestamp_str}\n"
                        f"📈 本週已完成：{len(signed_groups_this_week) + 1}/{len(GROUPS)} 組"
                    )
                    send_line_notify(line_message)
                    st.success(f"✅ {selected_group} 簽到成功！")
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
        
        # 1. 快速補簽工作台
        with sub_tab1:
            st.markdown("### ⚡ 指定週別一鍵補簽")
            all_weeks = sorted(list(set(df_records["week_key"].tolist() + [current_week_key])), reverse=True)
            target_week = st.selectbox("請選擇要處理/補簽的週別：", all_weeks)
            
            target_week_records = df_records[df_records["week_key"] == target_week]
            signed_in_week = target_week_records["group_name"].tolist()
            
            col_left, col_right = st.columns(2)
            
            with col_left:
                st.write(f"🟢 **`{target_week}` 已簽到組別明細**")
                if not target_week_records.empty:
                    for _, row in target_week_records.iterrows():
                        st.text(f"• {row['group_name']} | 代表: {row.get('signer', '未知')} | {row['mode']} | {row['timestamp']}")
                else:
                    st.info("該週尚無任何簽到紀錄。")
                    
            with col_right:
                st.write(f"🔴 **`{target_week}` 未簽到組別 (輔導手動補簽)**")
                missing_groups = [g for g in GROUPS if g not in signed_in_week]
                
                if missing_groups:
                    for g in missing_groups:
                        c_group, c_mode, c_btn = st.columns([2, 2, 2])
                        c_group.write(f"**{g}**")
                        mode_selected = c_mode.selectbox("方式", ATTENDANCE_MODES, key=f"mode_{target_week}_{g}")
                        if c_btn.button("一鍵補簽", key=f"btn_{target_week}_{g}"):
                            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            save_or_update_record(target_week, g, "輔導補簽", mode_selected, ts)
                            st.toast(f"✅ 已成功為 {g} 補簽！")
                            st.rerun()
                else:
                    st.success("🎉 該週所有組別皆已完成簽到！")

        # 2. 歷程矩陣
        with sub_tab2:
            st.markdown("### 📊 跨週出席矩陣表")
            if not df_records.empty:
                range_option = st.radio("選擇顯示範圍：", ["最近 4 週", "最近 8 週", "全歷史紀錄"], horizontal=True)
                
                # pivot 轉換，如果歷史紀錄欄位不足會自動補齊
                pivot_df = df_records.pivot(index="group_name", columns="week_key", values="mode")
                pivot_df = pivot_df.reindex(GROUPS).fillna("❌ 未簽到")
                
                cols = list(pivot_df.columns)
                if range_option == "最近 4 週":
                    cols = cols[-4:]
                elif range_option == "最近 8 週":
                    cols = cols[-8:]
                    
                display_df = pivot_df[cols].copy()
                
                total_displayed = len(cols)
                if total_displayed > 0:
                    att_counts = (display_df != "❌ 未簽到").sum(axis=1)
                    display_df["出席週數"] = att_counts
                    display_df["出席率"] = (att_counts / total_displayed * 100).round(1).astype(str) + "%"
                
                # 插入一欄成員名單作為輔助對照
                display_df.insert(0, "成員名單", [groups_dict.get(g, "") for g in display_df.index])
                
                st.dataframe(display_df, use_container_width=True)
                
                csv = df_records.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 匯出完整歷史數據 (.csv)", data=csv, file_name="youth_attendance_full.csv", mime="text/csv")
            else:
                st.info("目前無歷史紀錄。")

        # 3. 單組查詢
        with sub_tab3:
            st.markdown("### 🔍 單一組別歷史點名冊")
            search_group = st.selectbox("請選擇欲調閱資料的組別：", GROUPS)
            
            st.info(f"👥 **{search_group} 成員名單**：{groups_dict.get(search_group, '無')}")
            
            group_df = df_records[df_records["group_name"] == search_group].sort_values(by="week_key", ascending=False)
            
            if not group_df.empty:
                st.write(f"**{search_group}** 的歷史簽到紀錄（共 {len(group_df)} 次）：")
                st.dataframe(group_df[["week_key", "signer", "mode", "timestamp"]].rename(columns={
                    "week_key": "週別", "signer": "簽到代表", "mode": "簽到方式", "timestamp": "簽到時間"
                }), hide_index=True, use_container_width=True)
            else:
                st.info(f"{search_group} 目前尚無任何簽到紀錄。")

        # 4. 經文庫預覽
        with sub_tab4:
            st.markdown("### 📜 52 週經文庫檢視")
            if os.path.exists(VERSES_FILE):
                v_df = pd.read_csv(VERSES_FILE)
                st.dataframe(v_df, use_container_width=True, hide_index=True)
            else:
                st.warning("目前找不到 `verses.csv` 檔案，系統正使用預設備用經文。請建立 `verses.csv` 以啟用完整的 52 週輪播。")

    elif pwd != "":
        st.error("密碼錯誤，請重新輸入！")
