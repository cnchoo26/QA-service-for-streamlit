import os
import re
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ----------------------------------------------------------------------------
# 기본 설정
# ----------------------------------------------------------------------------

st.set_page_config(page_title="CAPA Tracker | QMove", page_icon="📋", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ISSUES_CSV = os.path.join(BASE_DIR, "issues.csv")
HISTORY_CSV = os.path.join(BASE_DIR, "issue_history.csv")

ISSUE_TYPES = ["원료불량", "포장불량", "표시오류", "공정이탈", "고객불만", "기타"]
STATUSES = ["received", "analysis", "action", "done"]
STATUS_LABELS = {"received": "접수", "analysis": "분석", "action": "조치", "done": "완료"}
TYPE_COLORS = {
    "원료불량": "#E67E22",
    "포장불량": "#E29056",
    "표시오류": "#E6A889",
    "공정이탈": "#AD4E1F",
    "고객불만": "#7E351B",
    "기타": "#6B7280",
}

DATE_FMT = "%Y-%m-%d"


# ----------------------------------------------------------------------------
# 데이터 로드 / 상태 초기화
# ----------------------------------------------------------------------------

@st.cache_data
def load_raw_data():
    issues = pd.read_csv(ISSUES_CSV, dtype=str).fillna("")
    history = pd.read_csv(HISTORY_CSV, dtype=str).fillna("")
    return issues, history


def init_state():
    if "issues_df" not in st.session_state:
        issues, history = load_raw_data()
        issues["id"] = issues["id"].astype(int)
        # 빈 문자열은 None으로 취급 (completedAt 등)
        for col in ["severity", "rootCause", "department", "productionLine", "lotNo", "claimSource", "completedAt"]:
            if col in issues.columns:
                issues[col] = issues[col].replace("", None)
        st.session_state.issues_df = issues
        st.session_state.history_df = history

    if "next_id" not in st.session_state:
        ids = st.session_state.issues_df["id"]
        st.session_state.next_id = int(ids.max()) + 1 if len(ids) else 1

    if "year_seq" not in st.session_state:
        year_seq = {}
        for capa in st.session_state.issues_df["capaNo"].dropna():
            m = re.match(r"^CAPA-(\d{4})-(\d+)$", str(capa))
            if m:
                year, seq = m.group(1), int(m.group(2))
                year_seq[year] = max(year_seq.get(year, 0), seq)
        st.session_state.year_seq = year_seq

    st.session_state.setdefault("type_filter", None)
    st.session_state.setdefault("detail_id", None)
    st.session_state.setdefault("show_new_modal", False)
    st.session_state.setdefault("selected_trend_date", None)
    st.session_state.setdefault("confirm_delete", False)


init_state()


# ----------------------------------------------------------------------------
# 헬퍼 함수 (원본 utils.js / data.js 로직 포팅)
# ----------------------------------------------------------------------------

def today_str():
    return date.today().strftime(DATE_FMT)


def parse_date(d):
    return datetime.strptime(d, DATE_FMT).date()


def days_until_due(due_date_str):
    return (parse_date(due_date_str) - date.today()).days


def deadline_state(due_date_str, status):
    if status == "done":
        return "done"
    d = days_until_due(due_date_str)
    if d < 0:
        return "overdue"
    if d <= 3:
        return "warning"
    return "normal"


def format_dday(due_date_str, status):
    if status == "done":
        return "완료"
    d = days_until_due(due_date_str)
    if d == 0:
        return "D-Day"
    if d > 0:
        return f"D-{d}"
    return f"D+{abs(d)}"


def format_date(due_date_str):
    return parse_date(due_date_str).strftime("%Y.%m.%d")


DEADLINE_COLORS = {
    "overdue": "#EF4444",
    "warning": "#E67E22",
    "done": "#6B7280",
    "normal": "#9AA0AC",
}


def next_capa_no():
    year = str(date.today().year)
    seq = st.session_state.year_seq.get(year, 0) + 1
    st.session_state.year_seq[year] = seq
    return f"CAPA-{year}-{seq:04d}"


def add_issue(product_name, issue_type, assignee, due_date):
    df = st.session_state.issues_df
    new_id = st.session_state.next_id
    st.session_state.next_id += 1
    new_row = {
        "id": new_id,
        "capaNo": next_capa_no(),
        "productName": product_name,
        "issueType": issue_type,
        "severity": None,
        "rootCause": None,
        "department": None,
        "productionLine": None,
        "lotNo": None,
        "claimSource": None,
        "assignee": assignee,
        "dueDate": due_date.strftime(DATE_FMT),
        "status": "received",
        "createdAt": today_str(),
        "completedAt": None,
    }
    st.session_state.issues_df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)


def _apply_status_change(row_idx, new_status):
    df = st.session_state.issues_df
    old_status = df.at[row_idx, "status"]
    df.at[row_idx, "status"] = new_status
    if new_status == "done" and old_status != "done":
        df.at[row_idx, "completedAt"] = today_str()
    elif new_status != "done" and old_status == "done":
        df.at[row_idx, "completedAt"] = None


def update_status(issue_id, new_status):
    df = st.session_state.issues_df
    idx = df.index[df["id"] == issue_id]
    if len(idx):
        _apply_status_change(idx[0], new_status)


def update_issue(issue_id, product_name, issue_type, assignee, due_date, status):
    df = st.session_state.issues_df
    idx = df.index[df["id"] == issue_id]
    if not len(idx):
        return
    i = idx[0]
    df.at[i, "productName"] = product_name
    df.at[i, "issueType"] = issue_type
    df.at[i, "assignee"] = assignee
    df.at[i, "dueDate"] = due_date.strftime(DATE_FMT)
    _apply_status_change(i, status)


def delete_issue(issue_id):
    df = st.session_state.issues_df
    st.session_state.issues_df = df[df["id"] != issue_id].reset_index(drop=True)


def get_stats(df):
    total = len(df)
    done_df = df[df["status"] == "done"]
    overdue = len(df[(df["status"] != "done") & (df["dueDate"] < today_str())])
    on_time_done = len(done_df[done_df["completedAt"].notna() & (done_df["completedAt"] <= done_df["dueDate"])])
    compliance_rate = round((on_time_done / len(done_df)) * 100) if len(done_df) else 0
    throughput_rate = round((len(done_df) / total) * 100) if total else 0
    return {
        "total": total,
        "in_progress": total - len(done_df),
        "overdue": overdue,
        "done_count": len(done_df),
        "compliance_rate": compliance_rate,
        "throughput_rate": throughput_rate,
    }


def get_trend_series(df, days=14):
    today = date.today()
    series = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        d_str = d.strftime(DATE_FMT)
        series.append({"date": d_str, "count": int((df["createdAt"] == d_str).sum())})
    return series


# ----------------------------------------------------------------------------
# 스타일 (원본 다크 테마 근사)
# ----------------------------------------------------------------------------

st.markdown(
    """
    <style>
    .stApp { background-color: #14161b; }
    .capa-card {
        background: #242830;
        border: 1px solid #2f3440;
        border-radius: 10px;
        padding: 10px 12px;
        margin-bottom: 10px;
    }
    .capa-card-overdue { border-left: 4px solid #EF4444; }
    .capa-card-warning { border-left: 4px solid #E67E22; }
    .capa-card-done { border-left: 4px solid #6B7280; opacity: 0.75; }
    .capa-card-normal { border-left: 4px solid #3a3f4b; }
    .capa-top { display: flex; justify-content: space-between; font-size: 0.75rem; color: #9AA0AC; }
    .capa-badge {
        display: inline-block; padding: 1px 8px; border-radius: 999px;
        font-size: 0.7rem; background: rgba(230,126,34,0.16); color: #E67E22; margin-top: 4px;
    }
    .capa-title { color: #edeef0; font-size: 0.95rem; font-weight: 600; margin: 4px 0 2px 0; }
    .capa-meta { color: #9AA0AC; font-size: 0.75rem; }
    .column-header {
        font-weight: 700; color: #edeef0; font-size: 1rem; padding-bottom: 6px;
        border-bottom: 2px solid #2f3440; margin-bottom: 10px; display:flex; justify-content:space-between;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------------
# 모달 (새 이슈 등록 / 상세 - 수정 - 삭제)
# ----------------------------------------------------------------------------

@st.dialog("새 이슈 등록")
def new_issue_dialog():
    with st.form("new_issue_form"):
        product_name = st.text_input("제품명", placeholder="예: 수분크림 A")
        issue_type = st.selectbox("이슈 유형", ISSUE_TYPES)
        assignee = st.text_input("담당자", placeholder="예: 김지현")
        due_date = st.date_input("마감일", value=date.today() + timedelta(days=7))
        col1, col2 = st.columns(2)
        submitted = col2.form_submit_button("등록", use_container_width=True, type="primary")
        cancelled = col1.form_submit_button("취소", use_container_width=True)

        if submitted:
            if not product_name.strip() or not assignee.strip():
                st.error("제품명과 담당자를 입력해주세요.")
            else:
                add_issue(product_name.strip(), issue_type, assignee.strip(), due_date)
                st.rerun()
        if cancelled:
            st.rerun()


@st.dialog("이슈 상세")
def detail_dialog(issue_id):
    df = st.session_state.issues_df
    row = df[df["id"] == issue_id]
    if row.empty:
        st.warning("이슈를 찾을 수 없습니다.")
        return
    issue = row.iloc[0]
    st.subheader(issue["capaNo"])

    if st.session_state.confirm_delete:
        st.warning("이 이슈를 삭제하시겠습니까?")
        c1, c2 = st.columns(2)
        if c1.button("취소", use_container_width=True, key="cancel_delete"):
            st.session_state.confirm_delete = False
            st.rerun()
        if c2.button("삭제", use_container_width=True, type="primary", key="confirm_delete_btn"):
            delete_issue(issue_id)
            st.session_state.detail_id = None
            st.session_state.confirm_delete = False
            st.rerun()
        return

    with st.form("detail_form"):
        product_name = st.text_input("제품명", value=issue["productName"])
        issue_type = st.selectbox("이슈 유형", ISSUE_TYPES, index=ISSUE_TYPES.index(issue["issueType"]))
        assignee = st.text_input("담당자", value=issue["assignee"])
        due_date = st.date_input("마감일", value=parse_date(issue["dueDate"]))
        status = st.selectbox(
            "상태", STATUSES, index=STATUSES.index(issue["status"]),
            format_func=lambda s: STATUS_LABELS[s],
        )
        col1, col2, col3 = st.columns(3)
        save = col3.form_submit_button("저장", use_container_width=True, type="primary")
        close = col2.form_submit_button("닫기", use_container_width=True)
        delete = col1.form_submit_button("삭제", use_container_width=True)

        if save:
            update_issue(issue_id, product_name.strip(), issue_type, assignee.strip(), due_date, status)
            st.session_state.detail_id = None
            st.session_state.confirm_delete = False
            st.rerun()
        if close:
            st.session_state.detail_id = None
            st.session_state.confirm_delete = False
            st.rerun()
        if delete:
            st.session_state.confirm_delete = True
            st.rerun()


# ----------------------------------------------------------------------------
# 헤더
# ----------------------------------------------------------------------------

h_left, h_right = st.columns([4, 1])
with h_left:
    st.markdown("## 📋 Claim Tracker <span style='color:#9AA0AC;font-size:1rem;'>클레임 이슈 추적 보드</span>", unsafe_allow_html=True)
with h_right:
    if st.button("+ 새 이슈 등록", type="primary", use_container_width=True):
        new_issue_dialog()

if st.session_state.detail_id is not None:
    detail_dialog(st.session_state.detail_id)

df_all = st.session_state.issues_df

st.divider()

# ----------------------------------------------------------------------------
# 인트로
# ----------------------------------------------------------------------------

intro1_img, intro1_text = st.columns([1, 4])
with intro1_img:
    st.image(os.path.join(BASE_DIR, "sources", "톱니바퀴.png"))
with intro1_text:
    st.markdown("#### 이슈 흐름을 관리하는 워크플로우")
    st.caption("접수부터 분석, 조치, 완료까지 — 클레임이 지금 어느 단계에 머물러 있는지, 어디서 지연되고 있는지 칸반 보드로 한눈에 파악합니다.")

intro2_text, intro2_img = st.columns([4, 1])
with intro2_text:
    st.markdown("#### 데이터로 남는 이슈 기록")
    st.caption("제품명, 유형, 담당자, 마감기한까지 — 모든 클레임 이력이 대시보드 통계와 추이로 정리되어 필요할 때 바로 확인할 수 있습니다.")
with intro2_img:
    st.image(os.path.join(BASE_DIR, "sources", "서류.png"))

st.divider()

# ----------------------------------------------------------------------------
# 대시보드
# ----------------------------------------------------------------------------

st.markdown("### 대시보드")
stats = get_stats(df_all)

m1, m2, m3, m4 = st.columns(4)
m1.metric("전체 이슈", stats["total"])
m2.metric("진행중", stats["in_progress"])
m3.metric("기한초과", stats["overdue"])
m4.metric("마감준수율", f"{stats['compliance_rate']}%")

c1, c2 = st.columns([1, 2])

with c1:
    st.markdown("**이슈 유형별 분포**")
    st.caption("범례를 클릭하면 해당 유형으로 필터링됩니다.")
    type_counts = df_all["issueType"].value_counts()
    dist = [{"type": t, "count": int(type_counts.get(t, 0))} for t in ISSUE_TYPES if type_counts.get(t, 0) > 0]
    if dist:
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=[d["type"] for d in dist],
                    values=[d["count"] for d in dist],
                    hole=0.6,
                    marker=dict(colors=[TYPE_COLORS.get(d["type"], "#C9CDD3") for d in dist]),
                    textinfo="label+value",
                )
            ]
        )
        fig.update_layout(
            showlegend=True, height=300, margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#edeef0"),
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("등록된 이슈가 없습니다.")

    type_options = ["(전체)"] + ISSUE_TYPES
    current = st.session_state.type_filter or "(전체)"
    picked = st.selectbox("유형 필터", type_options, index=type_options.index(current))
    st.session_state.type_filter = None if picked == "(전체)" else picked

with c2:
    st.markdown("**기간별 발생 추이 (최근 14일)**")
    trend = get_trend_series(df_all, 14)
    fig2 = go.Figure(
        data=[
            go.Scatter(
                x=[t["date"] for t in trend],
                y=[t["count"] for t in trend],
                mode="lines+markers",
                line=dict(color="#E67E22"),
                marker=dict(size=8),
            )
        ]
    )
    fig2.update_layout(
        height=260, margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#edeef0"), xaxis=dict(gridcolor="#2f3440"), yaxis=dict(gridcolor="#2f3440"),
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.progress(stats["compliance_rate"] / 100, text=f"마감기한 준수율 {stats['compliance_rate']}%")
    st.progress(stats["throughput_rate"] / 100, text=f"처리율 {stats['throughput_rate']}% ({stats['done_count']}건)")

st.divider()

# ----------------------------------------------------------------------------
# 칸반 보드
# ----------------------------------------------------------------------------

board_col, list_col = st.columns([5, 0])  # placeholder to keep layout simple
st.markdown("### 칸반 보드")

KANBAN_DISPLAY_LIMIT = 25
type_filter = st.session_state.type_filter

if type_filter:
    st.info(f"유형 필터: **{type_filter}**  (필터 해제는 위 '유형 필터'를 '(전체)'로 변경)")

cols = st.columns(4)
for col_widget, status in zip(cols, STATUSES):
    with col_widget:
        subset = df_all[df_all["status"] == status]
        if type_filter:
            subset = subset[subset["issueType"] == type_filter]
        subset = subset.sort_values("dueDate")
        total_in_col = len(subset)

        st.markdown(
            f"<div class='column-header'><span>{STATUS_LABELS[status]}</span><span>{total_in_col}</span></div>",
            unsafe_allow_html=True,
        )

        visible = subset.head(KANBAN_DISPLAY_LIMIT)
        if visible.empty:
            st.caption("이슈 없음")

        status_idx = STATUSES.index(status)
        for _, issue in visible.iterrows():
            dstate = deadline_state(issue["dueDate"], issue["status"])
            dday = format_dday(issue["dueDate"], issue["status"])
            color = DEADLINE_COLORS[dstate]

            st.markdown(
                f"""
                <div class="capa-card capa-card-{dstate}">
                    <div class="capa-top">
                        <span>{issue['capaNo']}</span>
                        <span style="color:{color}; font-weight:700;">{dday}</span>
                    </div>
                    <div class="capa-title">{issue['productName']}</div>
                    <span class="capa-badge">{issue['issueType']}</span>
                    <div class="capa-meta">담당자 {issue['assignee']} · 마감 {format_date(issue['dueDate'])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            b1, b2, b3 = st.columns([1, 1, 2])
            if b1.button("◀", key=f"prev-{issue['id']}", disabled=status_idx == 0, use_container_width=True):
                update_status(int(issue["id"]), STATUSES[status_idx - 1])
                st.rerun()
            if b2.button("▶", key=f"next-{issue['id']}", disabled=status_idx == len(STATUSES) - 1, use_container_width=True):
                update_status(int(issue["id"]), STATUSES[status_idx + 1])
                st.rerun()
            if b3.button("상세보기", key=f"detail-{issue['id']}", use_container_width=True):
                st.session_state.detail_id = int(issue["id"])
                st.session_state.confirm_delete = False
                st.rerun()

        if total_in_col > KANBAN_DISPLAY_LIMIT:
            st.caption(f"+{total_in_col - KANBAN_DISPLAY_LIMIT}건 더 있음 (아래 전체 목록에서 확인)")

st.divider()

# ----------------------------------------------------------------------------
# 전체 이슈 목록
# ----------------------------------------------------------------------------

with st.expander("📄 전체 이슈 목록 (검색 / 필터)", expanded=False):
    s1, s2, s3 = st.columns([2, 1, 1])
    search = s1.text_input("제품명, 담당자, CAPA No 검색", key="list_search")
    status_pick = s2.selectbox("상태", ["전체"] + STATUSES, format_func=lambda s: "전체" if s == "전체" else STATUS_LABELS[s])
    type_pick = s3.selectbox("유형", ["전체"] + ISSUE_TYPES, key="list_type_filter")

    filtered = df_all.copy()
    if status_pick != "전체":
        filtered = filtered[filtered["status"] == status_pick]
    if type_pick != "전체":
        filtered = filtered[filtered["issueType"] == type_pick]
    if search.strip():
        q = search.strip().lower()
        filtered = filtered[
            filtered["productName"].str.lower().str.contains(q)
            | filtered["assignee"].str.lower().str.contains(q)
            | filtered["capaNo"].str.lower().str.contains(q)
        ]
    filtered = filtered.sort_values("createdAt", ascending=False)

    display_df = filtered[["capaNo", "productName", "issueType", "assignee", "dueDate", "status"]].copy()
    display_df["dueDate"] = display_df["dueDate"].apply(format_date)
    display_df["status"] = display_df["status"].map(STATUS_LABELS)
    display_df.columns = ["CAPA No", "제품명", "유형", "담당자", "마감일", "상태"]

    st.caption(f"총 {len(filtered)}건")
    st.dataframe(display_df, use_container_width=True, height=400, hide_index=True)
