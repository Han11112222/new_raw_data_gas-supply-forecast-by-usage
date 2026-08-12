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
# 사이드바
# ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ 설정")
    uploaded = st.file_uploader("📂 구성비 엑셀 업로드", type=["xlsx"])
    st.markdown("---")
    st.markdown("#### 📅 조회 기간")
    c1, c2 = st.columns(2)
    y_start = c1.number_input("시작", 2014, 2030, 2016)
    y_end   = c2.number_input("종료", 2014, 2030, 2026)

# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
st.title("🔥 도시가스 용도별 공급량 예측")
st.caption("대성에너지(주) 마케팅본부 | 공급량 실적 × 용도별 구성비 → 용도별 공급량 산출")

# ── 구성비 로드
if uploaded is None:
    st.warning("👈 사이드바에서 구성비 엑셀 파일을 업로드해 주세요.")
    st.stop()

try:
    ratio_df = load_ratio(uploaded)
except Exception as e:
    st.error(f"구성비 파일 파싱 오류: {e}")
    st.stop()

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
tab1, tab2, tab3 = st.tabs(["📊 용도별 공급량", "📋 구성비 확인", "🗃️ 원시 데이터"])

# ──────────────────────────────────────────────
# TAB 1 : 용도별 공급량
# ──────────────────────────────────────────────
with tab1:

    # ① 월별 피벗 테이블
    pivot = (
        result.pivot_table(index="연월", columns="용도", values="공급량_GJ", aggfunc="sum")
        .fillna(0)
        [[u for u in usage_order if u in result["용도"].unique()]]
    )

    # ② 연도별 피벗 테이블
    result["연도"] = result["연월"].dt.year
    pivot_year = (
        result.groupby(["연도","용도"])["공급량_GJ"]
        .sum().unstack("용도").fillna(0)
        [[u for u in usage_order if u in result["용도"].unique()]]
    )

    # ─ 연도별 누적 막대 차트
    st.markdown('<div class="sub">📊 연도별 용도별 공급량 (GJ)</div>', unsafe_allow_html=True)
    fig_yr = go.Figure()
    for usage in pivot_year.columns:
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
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=70,r=20,t=60,b=40),
    )
    fig_yr.update_yaxes(showgrid=True, gridcolor="#ebebeb")
    st.plotly_chart(fig_yr, use_container_width=True)

    # ─ 월별 누적 막대 차트
    st.markdown('<div class="sub">📊 월별 용도별 공급량 (GJ)</div>', unsafe_allow_html=True)
    fig_mo = go.Figure()
    for usage in pivot.columns:
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

    # ─ 연도별 테이블
    st.markdown('<div class="sub">📋 연도별 용도별 공급량 테이블 (GJ)</div>', unsafe_allow_html=True)
    tbl_yr = pivot_year.copy().round(1)
    tbl_yr.index = tbl_yr.index.astype(str)
    tbl_yr["합계"] = tbl_yr.sum(axis=1)
    st.dataframe(tbl_yr.style.format("{:,.1f}"), use_container_width=True)

    # ─ 월별 테이블
    st.markdown('<div class="sub">📋 월별 용도별 공급량 테이블 (GJ)</div>', unsafe_allow_html=True)
    tbl_mo = pivot.copy().round(1)
    tbl_mo.index = tbl_mo.index.strftime("%Y-%m")
    tbl_mo["합계"] = tbl_mo.sum(axis=1)
    st.dataframe(tbl_mo.style.format("{:,.1f}"), use_container_width=True, height=320)

    # ─ 엑셀 다운로드
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        tbl_yr.to_excel(w, sheet_name="연도별")
        tbl_mo.to_excel(w, sheet_name="월별")
    st.download_button(
        "⬇️ 엑셀 다운로드 (연도별 + 월별)",
        data=buf.getvalue(),
        file_name=f"용도별공급량_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# ──────────────────────────────────────────────
# TAB 2 : 구성비 확인
# ──────────────────────────────────────────────
with tab2:
    st.markdown('<div class="sub">📋 용도별 구성비 원본 (%)</div>', unsafe_allow_html=True)
    disp_ratio = ratio_df.copy()
    disp_ratio.columns = disp_ratio.columns.strftime("%Y-%m")
    # 기간 필터
    cols = [c for c in disp_ratio.columns if y_start <= int(c[:4]) <= y_end]
    if cols:
        disp_ratio = disp_ratio[cols]
    st.dataframe(
        disp_ratio.style.format("{:.2f}").background_gradient(cmap="Blues", axis=1),
        use_container_width=True, height=430,
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
