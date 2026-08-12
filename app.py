import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from io import BytesIO, StringIO
import requests

# ──────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="도시가스 용도별 공급량 예측",
    page_icon="🔥",
    layout="wide",
)

st.markdown("""
<style>
h1 { color: #1a3c5e; border-bottom: 3px solid #e8501a; padding-bottom: 0.3rem; }
.sub { font-size:1.05rem; font-weight:600; color:#2c5f8a; margin:1rem 0 0.3rem 0; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
GSHEET_ID  = "13HrIz6OytYDykXeXzXJ02I6XbaKin1YaKBoO2kBd6Bs"
GSHEET_URL = f"https://docs.google.com/spreadsheets/d/{GSHEET_ID}/export?format=csv&gid=0"

# 구성비 엑셀에서 유효한 용도 행 번호 (0-indexed, 소계·합계 제외)
RATIO_VALID_ROWS = [1,2,3,4, 6,7,8,9,10,11,12,13,14]

GROUP_MAP = {
    "취사용":"주택용","개별난방용":"주택용","중앙난방용":"주택용","자가열전용":"주택용",
    "일반용":"기타","냉난방공조용":"기타","업무난방용":"기타","산업용":"기타",
    "수송용":"기타","열병합용":"기타","연료전지용":"기타","열전용설비용":"기타","주한미군":"기타",
}
COLOR_MAP = {
    "취사용":"#4e79a7","개별난방용":"#f28e2b","중앙난방용":"#e15759","자가열전용":"#76b7b2",
    "일반용":"#59a14f","냉난방공조용":"#edc948","업무난방용":"#b07aa1","산업용":"#ff9da7",
    "수송용":"#9c755f","열병합용":"#bab0ac","연료전지용":"#86bcb6","열전용설비용":"#d3a0a0",
    "주한미군":"#aecbcf",
}

# ──────────────────────────────────────────────
# 1) 구성비 로드
# ──────────────────────────────────────────────
def load_ratio(file) -> pd.DataFrame:
    """
    반환: DataFrame (index=용도명, columns=월별 Timestamp, 값=구성비%)
    """
    raw = pd.read_excel(file, sheet_name="구성비", header=None)

    dates = pd.to_datetime(raw.iloc[0, 2:], errors="coerce")          # 1행: 날짜
    items = raw.iloc[RATIO_VALID_ROWS, 1].str.strip().tolist()         # 용도명
    data  = raw.iloc[RATIO_VALID_ROWS, 2:].values.astype(float)       # 구성비 값

    df = pd.DataFrame(data, index=items, columns=dates)
    df.index.name = "용도"
    return df

# ──────────────────────────────────────────────
# 2) 구글시트 월별 공급량 로드
# ──────────────────────────────────────────────
@st.cache_data(ttl=1800)
def load_supply() -> tuple:
    """
    반환: (DataFrame[연월, 총공급량_GJ], 에러메시지or None)
    구글시트 컬럼: A=일자, B=공급량(MJ), C=공급량(M3), D=평균기온, E=최저, F=최고
    """
    try:
        resp = requests.get(GSHEET_URL, timeout=20)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        df.columns = df.columns.str.strip()

        # 날짜 파싱 (A열 = '일자')
        date_col = df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])

        # 공급량(MJ) 파싱 (B열)
        mj_col = df.columns[1]
        df[mj_col] = pd.to_numeric(df[mj_col].astype(str).str.replace(",",""), errors="coerce")
        df["공급량_GJ"] = df[mj_col] / 1_000   # MJ → GJ

        # 월별 합산
        df["연월"] = df[date_col].dt.to_period("M").dt.to_timestamp()
        monthly = (
            df.groupby("연월")["공급량_GJ"]
            .sum()
            .reset_index()
            .rename(columns={"공급량_GJ":"총공급량_GJ"})
        )
        monthly = monthly[monthly["총공급량_GJ"] > 0].reset_index(drop=True)
        return monthly, None
    except Exception as e:
        return None, str(e)

# ──────────────────────────────────────────────
# 3) 용도별 공급량 계산
# ──────────────────────────────────────────────
def calc_by_usage(monthly: pd.DataFrame, ratio: pd.DataFrame) -> pd.DataFrame:
    """
    monthly: [연월, 총공급량_GJ]
    ratio:   index=용도, columns=Timestamp, 값=구성비%
    반환:    [연월, 용도, 그룹, 구성비(%), 공급량_GJ]
    """
    rows = []
    for _, r in monthly.iterrows():
        ym  = r["연월"]
        val = r["총공급량_GJ"]

        # 가장 가까운 구성비 날짜
        col = ratio.columns[abs(ratio.columns - ym).argmin()]

        for usage in ratio.index:
            pct = float(ratio.loc[usage, col])
            rows.append({
                "연월":       ym,
                "용도":       usage,
                "그룹":       GROUP_MAP.get(usage, "기타"),
                "구성비(%)":  pct,
                "공급량_GJ":  val * pct / 100,
            })
    return pd.DataFrame(rows)

# ──────────────────────────────────────────────
# GitHub 구성비 엑셀 자동 로드
# ──────────────────────────────────────────────
GITHUB_RATIO_URL = "https://raw.githubusercontent.com/Han11112222/new_raw_data_gas-supply-forecast-by-usage/main/자가소모 및 구성비 정리_260625.xlsx"

@st.cache_data(ttl=3600)
def load_ratio_from_github() -> tuple:
    try:
        resp = requests.get(GITHUB_RATIO_URL, timeout=15)
        resp.raise_for_status()
        return load_ratio(BytesIO(resp.content)), None
    except Exception as e:
        return None, str(e)

# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ 설정")
    st.markdown("#### 📂 구성비 파일")
    uploaded = st.file_uploader(
        "최신 파일로 교체할 경우만 업로드",
        type=["xlsx"],
        help="업로드하지 않으면 GitHub에 저장된 파일을 자동으로 사용합니다."
    )
    st.markdown("---")
    st.markdown("#### 📂 구방식 비교 파일")
    uploaded_old = st.file_uploader(
        "상품별공급량_MJ실적.xlsx 업로드",
        type=["xlsx"],
        key="old_file",
        help="이전 방식(상품별 실적) 파일을 업로드하면 비교 탭이 활성화됩니다."
    )
    st.markdown("---")
    st.markdown("#### 📅 조회 기간")
    c1, c2 = st.columns(2)
    y_start = c1.number_input("시작", 2014, 2030, 2017)
    y_end   = c2.number_input("종료", 2014, 2030, 2025)

# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
st.title("🔥 도시가스 용도별 공급량 예측")
st.caption("대성에너지(주) 마케팅본부 | 공급량 실적 × 용도별 구성비 → 용도별 공급량 산출")

# ── 구성비 로드 (업로드 파일 우선, 없으면 GitHub 자동)
if uploaded is not None:
    try:
        ratio_df = load_ratio(uploaded)
        st.sidebar.success("✅ 업로드 파일 사용 중")
    except Exception as e:
        st.error(f"업로드 파일 파싱 오류: {e}")
        st.stop()
else:
    ratio_df, ratio_err = load_ratio_from_github()
    if ratio_df is None:
        st.error(f"구성비 파일 로드 실패: {ratio_err}")
        st.info("👈 사이드바에서 구성비 엑셀 파일을 직접 업로드해 주세요.")
        st.stop()
    st.sidebar.info("📡 GitHub 파일 자동 사용 중")

# ── 공급량 로드
supply_df, supply_err = load_supply()
if supply_err or supply_df is None:
    st.error(f"구글시트 연결 실패: {supply_err}")
    st.info("구글시트를 **링크가 있는 모든 사용자 → 뷰어** 로 공유 설정해 주세요.")
    st.stop()

# ── 기간 필터
supply_filtered = supply_df[
    (supply_df["연월"].dt.year >= y_start) &
    (supply_df["연월"].dt.year <= y_end)
].copy()

if supply_filtered.empty:
    st.warning("선택 기간에 데이터가 없습니다.")
    st.stop()

# ── 용도별 계산
result = calc_by_usage(supply_filtered, ratio_df)
usage_order = list(ratio_df.index)   # 엑셀 순서 그대로

# ══════════════════════════════════════════════
# TAB 구성
# ══════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs(["📊 용도별 공급량", "📋 구성비 확인", "🗃️ 원시 데이터", "🔍 구방식 vs 신방식 비교"])

# ──────────────────────────────────────────────
# TAB 1 : 용도별 공급량
# ──────────────────────────────────────────────
with tab1:

    # ① 용도별 합계 내림차순 → 첫번째 add_trace가 하단이므로 많은 것 먼저
    usage_total = result.groupby("용도")["공급량_GJ"].sum()
    usage_sorted = usage_total.sort_values(ascending=False).index.tolist()
    usage_sorted = [u for u in usage_sorted if u in result["용도"].unique()]

    # ② 월별 피벗 (정렬 순서 적용)
    pivot = (
        result.pivot_table(index="연월", columns="용도", values="공급량_GJ", aggfunc="sum")
        .fillna(0)
        [usage_sorted]
    )

    # ③ 연도별 피벗 (정렬 순서 적용)
    result["연도"] = result["연월"].dt.year
    pivot_year = (
        result.groupby(["연도","용도"])["공급량_GJ"]
        .sum().unstack("용도").fillna(0)
        [usage_sorted]
    )

    # ─ 연도별 누적 막대 차트 (많은 것 먼저 add → 하단에 위치)
    st.markdown('<div class="sub">📊 연도별 용도별 공급량 (GJ)</div>', unsafe_allow_html=True)
    fig_yr = go.Figure()
    for usage in usage_sorted:   # 내림차순 그대로 → 많은 것 첫번째 add → 하단
        fig_yr.add_trace(go.Bar(
            x=pivot_year.index.astype(str),
            y=pivot_year[usage],
            name=usage,
            marker_color=COLOR_MAP.get(usage, "#aaa"),
            hovertemplate=f"<b>{usage}</b><br>%{{x}}년<br>%{{y:,.0f}} GJ<extra></extra>",
        ))
    fig_yr.update_layout(
        barmode="stack", height=430,
        xaxis_title="연도", yaxis_title="공급량 (GJ)",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0, traceorder="reversed"),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=70,r=20,t=70,b=40),
    )
    fig_yr.update_yaxes(showgrid=True, gridcolor="#ebebeb")
    st.plotly_chart(fig_yr, use_container_width=True)

    # ─ 월별 누적 막대 차트
    st.markdown('<div class="sub">📊 월별 용도별 공급량 (GJ)</div>', unsafe_allow_html=True)
    fig_mo = go.Figure()
    for usage in usage_sorted:   # 내림차순 그대로 → 많은 것 첫번째 add → 하단
        fig_mo.add_trace(go.Bar(
            x=pivot.index,
            y=pivot[usage],
            name=usage,
            marker_color=COLOR_MAP.get(usage, "#aaa"),
            hovertemplate=f"<b>{usage}</b><br>%{{x|%Y-%m}}<br>%{{y:,.0f}} GJ<extra></extra>",
            showlegend=False,
        ))
    fig_mo.update_layout(
        barmode="stack", height=380,
        xaxis_title="연월", yaxis_title="공급량 (GJ)",
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=70,r=20,t=30,b=40),
    )
    fig_mo.update_yaxes(showgrid=True, gridcolor="#ebebeb")
    st.plotly_chart(fig_mo, use_container_width=True)

    # ─ 연도별 테이블 + 다운로드
    st.markdown('<div class="sub">📋 연도별 용도별 공급량 테이블 (GJ)</div>', unsafe_allow_html=True)
    tbl_yr = pivot_year[usage_sorted].copy().round(1)
    tbl_yr.index = tbl_yr.index.astype(str)
    tbl_yr["합계"] = tbl_yr.sum(axis=1)
    st.dataframe(tbl_yr.style.format("{:,.1f}"), use_container_width=True)

    buf_yr = BytesIO()
    with pd.ExcelWriter(buf_yr, engine="openpyxl") as w:
        tbl_yr.to_excel(w, sheet_name="연도별")
    st.download_button(
        "⬇️ 연도별 공급량 엑셀 다운로드",
        data=buf_yr.getvalue(),
        file_name=f"연도별_용도별공급량_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_yr",
    )

    st.markdown("---")

    # ─ 월별 테이블 + 다운로드
    st.markdown('<div class="sub">📋 월별 용도별 공급량 테이블 (GJ)</div>', unsafe_allow_html=True)
    tbl_mo = pivot[usage_sorted].copy().round(1)
    tbl_mo.index = tbl_mo.index.strftime("%Y-%m")
    tbl_mo["합계"] = tbl_mo.sum(axis=1)
    st.dataframe(tbl_mo.style.format("{:,.1f}"), use_container_width=True, height=340)

    buf_mo = BytesIO()
    with pd.ExcelWriter(buf_mo, engine="openpyxl") as w:
        tbl_mo.to_excel(w, sheet_name="월별")
    st.download_button(
        "⬇️ 월별 공급량 엑셀 다운로드",
        data=buf_mo.getvalue(),
        file_name=f"월별_용도별공급량_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_mo",
    )

# ──────────────────────────────────────────────
# TAB 2 : 구성비 확인
# ──────────────────────────────────────────────
with tab2:
    st.markdown('<div class="sub">📋 용도별 구성비 원본 (%)</div>', unsafe_allow_html=True)
    disp_ratio = ratio_df.copy()
    disp_ratio.columns = disp_ratio.columns.strftime("%Y-%m")
    cols = [c for c in disp_ratio.columns if y_start <= int(c[:4]) <= y_end]
    if cols:
        disp_ratio = disp_ratio[cols]
    st.dataframe(
        disp_ratio.style.format("{:.2f}"),
        use_container_width=True, height=430,
    )

    buf_ratio = BytesIO()
    with pd.ExcelWriter(buf_ratio, engine="openpyxl") as w:
        disp_ratio.to_excel(w, sheet_name="구성비")
    st.download_button(
        "⬇️ 구성비 엑셀 다운로드",
        data=buf_ratio.getvalue(),
        file_name=f"용도별구성비_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_ratio",
    )

# ──────────────────────────────────────────────
# TAB 3 : 원시 데이터
# ──────────────────────────────────────────────
with tab3:
    st.markdown('<div class="sub">📅 월별 총공급량 (구글시트)</div>', unsafe_allow_html=True)
    disp_sup = supply_filtered.copy()
    disp_sup["연월"] = disp_sup["연월"].dt.strftime("%Y-%m")
    disp_sup["총공급량_GJ"] = disp_sup["총공급량_GJ"].round(1)
    st.dataframe(disp_sup.style.format({"총공급량_GJ":"{:,.1f}"}), use_container_width=True, height=400)

    buf_sup = BytesIO()
    with pd.ExcelWriter(buf_sup, engine="openpyxl") as w:
        disp_sup.to_excel(w, sheet_name="월별공급량", index=False)
    st.download_button(
        "⬇️ 월별 총공급량 엑셀 다운로드",
        data=buf_sup.getvalue(),
        file_name=f"월별총공급량_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_sup",
    )

# ──────────────────────────────────────────────
# TAB 4 : 구방식 vs 신방식 비교
# ──────────────────────────────────────────────

OLD_COL_MAP = {
    "취사용":        ["취사용"],
    "개별난방용":    ["개별난방용"],
    "중앙난방용":    ["중앙난방용"],
    "자가열전용":    ["자가열전용"],
    "일반용":        ["영업용", "일반용(1)", "일반용(2)"],
    "냉난방공조용":  ["냉난방용"],
    "업무난방용":    ["업무난방용"],
    "산업용":        ["산업용"],
    "수송용":        ["수송용(CNG)", "수송용(BIO)"],
    "열병합용":      ["열병합용"],
    "연료전지용":    ["연료전지용"],
    "열전용설비용":  ["열전용설비용(주택외)"],
    "주한미군":      ["주한미군"],
}

GITHUB_OLD_URL = "https://raw.githubusercontent.com/Han11112222/new_raw_data_gas-supply-forecast-by-usage/main/상품별공급량_MJ실적.xlsx"

def load_old_supply(file) -> pd.DataFrame:
    df = pd.read_excel(file, sheet_name="공급량_실적", header=0)
    df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")
    df = df.dropna(subset=["날짜"])
    df["연월"] = df["날짜"].dt.to_period("M").dt.to_timestamp()
    rows = []
    for _, r in df.iterrows():
        for new_usage, old_cols in OLD_COL_MAP.items():
            val = sum(
                pd.to_numeric(str(r[c]).replace(",", ""), errors="coerce") or 0
                for c in old_cols if c in df.columns
            )
            rows.append({"연월": r["연월"], "용도": new_usage, "공급량_GJ": val / 1_000})
    res = pd.DataFrame(rows)
    return res.groupby(["연월", "용도"])["공급량_GJ"].sum().reset_index()

@st.cache_data(ttl=3600)
def load_old_from_github() -> tuple:
    try:
        resp = requests.get(GITHUB_OLD_URL, timeout=15)
        resp.raise_for_status()
        return load_old_supply(BytesIO(resp.content)), None
    except Exception as e:
        return None, str(e)

with tab4:
    st.markdown('<div class="sub">🔍 구방식 vs 신방식 — 용도별 비교</div>', unsafe_allow_html=True)
    st.caption("구방식: 상품별공급량 실적 파일 | 신방식: 총공급량 × 구성비")

    # ── 구방식 데이터 로드 (업로드 우선, 없으면 GitHub)
    if uploaded_old is not None:
        try:
            old_df = load_old_supply(uploaded_old)
            st.sidebar.success("✅ 구방식 파일: 업로드 사용")
        except Exception as e:
            st.error(f"파일 파싱 오류: {e}")
            st.stop()
    else:
        old_df, old_err = load_old_from_github()
        if old_df is None:
            st.error(f"구방식 파일 GitHub 로드 실패: {old_err}")
            st.info("👈 사이드바에서 상품별공급량_MJ실적.xlsx 를 직접 업로드해 주세요.")
            st.stop()
        st.sidebar.info("📡 구방식 파일: GitHub 자동 사용")

    # ── 비교 기간 고정: 2017~2025
    CMP_START, CMP_END = 2017, 2025

    old_filtered = old_df[
        (old_df["연월"].dt.year >= CMP_START) &
        (old_df["연월"].dt.year <= CMP_END)
    ].copy()
    new_filtered = result[
        (result["연월"].dt.year >= CMP_START) &
        (result["연월"].dt.year <= CMP_END)
    ].copy()

    common_usages = [u for u in OLD_COL_MAP.keys() if u in new_filtered["용도"].unique()]

    selected_usage = st.selectbox(
        "비교할 용도 선택",
        options=common_usages,
        index=common_usages.index("일반용") if "일반용" in common_usages else 0,
    )

    # ── 데이터 추출
    old_usage = old_filtered[old_filtered["용도"] == selected_usage].set_index("연월")["공급량_GJ"]
    new_usage = new_filtered[new_filtered["용도"] == selected_usage].set_index("연월")["공급량_GJ"]

    old_yr = old_usage.groupby(old_usage.index.year).sum()
    new_yr = new_usage.groupby(new_usage.index.year).sum()
    years  = sorted(set(old_yr.index) | set(new_yr.index))

    old_vals = [old_yr.get(y, 0) for y in years]
    new_vals = [new_yr.get(y, 0) for y in years]

    # % 차이 계산
    pct_list = []
    for o, n in zip(old_vals, new_vals):
        if o and o != 0:
            pct_list.append((n - o) / o * 100)
        else:
            pct_list.append(0.0)

    # ─ 연도별 비교 막대 + % annotation
    st.markdown(f'<div class="sub">📊 연도별 비교 — {selected_usage} (GJ) · 막대 상단: 신방식 차이(%)</div>', unsafe_allow_html=True)

    max_val = max(max(old_vals), max(new_vals)) if old_vals and new_vals else 1
    fig_cmp_yr = go.Figure()

    fig_cmp_yr.add_trace(go.Bar(
        x=[str(y) for y in years], y=old_vals,
        name="구방식 (상품별 실적)", marker_color="#2c5f8a",
        hovertemplate="구방식<br>%{x}년<br>%{y:,.0f} GJ<extra></extra>",
    ))
    fig_cmp_yr.add_trace(go.Bar(
        x=[str(y) for y in years], y=new_vals,
        name="신방식 (구성비 적용)", marker_color="#e8501a",
        hovertemplate="신방식<br>%{x}년<br>%{y:,.0f} GJ<extra></extra>",
    ))

    # 신방식 막대 상단에 % 표기
    annotations = []
    for i, (y, pct, nv) in enumerate(zip(years, pct_list, new_vals)):
        sign  = "+" if pct >= 0 else ""
        color = "#e8501a" if pct >= 0 else "#2c5f8a"
        annotations.append(dict(
            x=str(y), y=nv + max_val * 0.02,
            text=f"<b>{sign}{pct:.1f}%</b>",
            showarrow=False,
            font=dict(size=11, color=color),
            xanchor="center", yanchor="bottom",
            # 신방식 막대(오른쪽)에 표시하기 위해 x축 오프셋
            xref="x", yref="y",
        ))

    fig_cmp_yr.update_layout(
        barmode="group", height=460,
        xaxis_title="연도", yaxis_title="공급량 (GJ)",
        yaxis=dict(range=[0, max_val * 1.15], showgrid=True, gridcolor="#ebebeb"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=70, r=20, t=70, b=40),
        annotations=annotations,
    )
    st.plotly_chart(fig_cmp_yr, use_container_width=True)

    # ─ 월별 추이 라인 차트
    st.markdown(f'<div class="sub">📈 월별 추이 비교 — {selected_usage} (GJ)</div>', unsafe_allow_html=True)
    fig_cmp_mo = go.Figure()
    fig_cmp_mo.add_trace(go.Scatter(
        x=old_usage.index, y=old_usage.values,
        name="구방식", mode="lines", line=dict(color="#2c5f8a", width=2),
        hovertemplate="구방식<br>%{x|%Y-%m}<br>%{y:,.0f} GJ<extra></extra>",
    ))
    fig_cmp_mo.add_trace(go.Scatter(
        x=new_usage.index, y=new_usage.values,
        name="신방식", mode="lines", line=dict(color="#e8501a", width=2, dash="dot"),
        hovertemplate="신방식<br>%{x|%Y-%m}<br>%{y:,.0f} GJ<extra></extra>",
    ))
    fig_cmp_mo.update_layout(
        height=360, xaxis_title="연월", yaxis_title="공급량 (GJ)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=70, r=20, t=50, b=40),
    )
    fig_cmp_mo.update_yaxes(showgrid=True, gridcolor="#ebebeb")
    st.plotly_chart(fig_cmp_mo, use_container_width=True)

    # ─ 연도별 비교 테이블
    st.markdown(f'<div class="sub">📋 연도별 비교 테이블 — {selected_usage}</div>', unsafe_allow_html=True)
    tbl_cmp = pd.DataFrame({
        "구방식_GJ": old_yr,
        "신방식_GJ": new_yr,
    }).fillna(0).round(1)
    tbl_cmp["차이_GJ"]  = (tbl_cmp["신방식_GJ"] - tbl_cmp["구방식_GJ"]).round(1)
    tbl_cmp["차이(%)"]  = (tbl_cmp["차이_GJ"] / tbl_cmp["구방식_GJ"].replace(0, float("nan")) * 100).round(2)
    tbl_cmp.index.name  = "연도"

    def color_pct(val):
        if pd.isna(val): return ""
        return "color: #e8501a" if val >= 0 else "color: #2c5f8a"

    st.dataframe(
        tbl_cmp.style
            .format({"구방식_GJ": "{:,.1f}", "신방식_GJ": "{:,.1f}",
                     "차이_GJ": "{:,.1f}", "차이(%)": "{:+.2f}%"})
            .map(color_pct, subset=["차이(%)"]),
        use_container_width=True,
    )

    buf_cmp = BytesIO()
    with pd.ExcelWriter(buf_cmp, engine="openpyxl") as w:
        tbl_cmp.to_excel(w, sheet_name=f"{selected_usage}_비교")
    st.download_button(
        f"⬇️ {selected_usage} 비교 엑셀 다운로드",
        data=buf_cmp.getvalue(),
        file_name=f"비교_{selected_usage}_2017_2025.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_cmp",
    )
