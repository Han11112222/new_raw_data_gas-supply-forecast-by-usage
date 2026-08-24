import streamlit as st
import pandas as pd
import plotly.graph_objects as go
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

# ── 구글시트 (구성비 + 상품별수급량) ──
NEW_GSHEET_ID  = "1gIhArPlLBJ9fwlaqXtZWxiKlSK9hbRuz6HcDw_Yf7Is"
NEW_GSHEET_URL = f"https://docs.google.com/spreadsheets/d/{NEW_GSHEET_ID}/export?format=csv&gid=0"

# ── 구글시트 (일별 공급량 - 기존) ──
SUPPLY_GSHEET_ID  = "13HrIz6OytYDykXeXzXJ02I6XbaKin1YaKBoO2kBd6Bs"
SUPPLY_GSHEET_URL = f"https://docs.google.com/spreadsheets/d/{SUPPLY_GSHEET_ID}/export?format=csv&gid=0"

# ── GitHub 구방식 실적 파일 ──
GITHUB_OLD_URL = "https://raw.githubusercontent.com/Han11112222/new_raw_data_gas-supply-forecast-by-usage/main/상품별공급량_MJ실적.xlsx"

# ── 용도 목록 (구글시트 구성비 섹션 순서 그대로) ──
# 구글시트 구조:
#   행3: 헤더 (정산그룹 | 정산항목 | 날짜1 | 날짜2 | ...)
#   행4~8: 주택용 (취사용, 개별난방용, 중앙난방용, 자가열전용) + 소계
#   행9(소계 skip)
#   행10~18: 기타 (일반용, 냉난방공조용, 업무난방용, 산업용, 수송용, 열병합용, 연료전지용, 열전용설비용, 주한미군)
#   행19: 소계, 행20: 합계 (skip)
#   행22~23: 빈행
#   행24: 상품별분배 헤더
#   행25~29: 주택용 + 소계
#   행30~40: 기타 + 소계/합계
#
# 0-indexed (0=행1):
#   구성비 데이터행: 4,5,6,7, 10,11,12,13,14,15,16,17,18  (소계/합계 제외)
#   수급량 데이터행: 24,25,26,27, 29,30,31,32,33,34,35,36,37 (소계/합계 제외)

USAGE_LIST = [
    "취사용", "개별난방용", "중앙난방용", "자가열전용",
    "일반용", "냉난방공조용", "업무난방용", "산업용",
    "수송용", "열병합용", "연료전지용", "열전용설비용", "주한미군",
]

# 0-indexed 행 번호
RATIO_DATA_ROWS  = [4, 5, 6, 7,   10, 11, 12, 13, 14, 15, 16, 17, 18]
SUPPLY_DATA_ROWS = [24, 25, 26, 27, 29, 30, 31, 32, 33, 34, 35, 36, 37]

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
# 구글시트(신규) 로드 → 구성비 + 상품별수급량
# ──────────────────────────────────────────────
@st.cache_data(ttl=1800)
def load_new_gsheet() -> tuple:
    """
    새 구글시트에서 구성비(%)와 상품별 수급량(GJ)을 동시에 로드.

    구글시트 레이아웃 (0-indexed):
      행0  : 빈행 or 제목
      행1  : 수급량(GJ) 합계 행 → B열이 '수급량(GJ)', C열~: 월별 합계값
      행2  : 빈행
      행3  : 헤더행 → B열='정산항목', C열~=날짜
      행4~8: 주택용 구성비 (소계 포함)
      행9  : 소계
      행10~18: 기타 구성비 (소계 포함)
      행19 : 소계, 행20: 합계

      행22~23: 빈/상품별분배 헤더
      행24~28: 주택용 수급량 (소계)
      행29   : 소계
      행30~37: 기타 수급량

    반환: (ratio_df, supply_df, dates, 에러)
      ratio_df  : DataFrame(index=용도, columns=Timestamp, 값=구성비%)
      supply_df : DataFrame(index=용도, columns=Timestamp, 값=수급량GJ)
      dates     : 날짜 리스트
    """
    try:
        resp = requests.get(NEW_GSHEET_URL, timeout=20)
        resp.raise_for_status()
        raw = pd.read_csv(StringIO(resp.text), header=None)

        # 날짜: 헤더행(row 3, 0-indexed) C열~  → raw.iloc[3, 2:]
        dates = pd.to_datetime(raw.iloc[3, 2:], errors="coerce")
        valid_date_cols = [i for i, d in enumerate(dates) if pd.notna(d)]
        dates = dates.iloc[valid_date_cols]

        def extract_rows(row_indices):
            result = {}
            for idx, row_i in enumerate(row_indices):
                usage = USAGE_LIST[idx]
                vals = pd.to_numeric(
                    raw.iloc[row_i, 2:].iloc[valid_date_cols]
                    .astype(str).str.replace(",", ""),
                    errors="coerce"
                ).values
                result[usage] = vals
            return pd.DataFrame(result, index=dates).T

        ratio_df  = extract_rows(RATIO_DATA_ROWS)
        supply_df = extract_rows(SUPPLY_DATA_ROWS)

        ratio_df.index.name  = "용도"
        supply_df.index.name = "용도"

        return ratio_df, supply_df, dates, None
    except Exception as e:
        return None, None, None, str(e)

# ──────────────────────────────────────────────
# 기존 일별 공급량 구글시트 로드 (총공급량)
# ──────────────────────────────────────────────
@st.cache_data(ttl=1800)
def load_total_supply() -> tuple:
    try:
        resp = requests.get(SUPPLY_GSHEET_URL, timeout=20)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        df.columns = df.columns.str.strip()
        date_col = df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])
        mj_col = df.columns[1]
        df[mj_col] = pd.to_numeric(df[mj_col].astype(str).str.replace(",",""), errors="coerce")
        df["공급량_GJ"] = df[mj_col] / 1_000
        df["연월"] = df[date_col].dt.to_period("M").dt.to_timestamp()
        monthly = (
            df.groupby("연월")["공급량_GJ"]
            .sum().reset_index()
            .rename(columns={"공급량_GJ":"총공급량_GJ"})
        )
        monthly = monthly[monthly["총공급량_GJ"] > 0].reset_index(drop=True)
        return monthly, None
    except Exception as e:
        return None, str(e)

# ──────────────────────────────────────────────
# 신방식: 구글시트 상품별수급량 → result 형태 변환
# ──────────────────────────────────────────────
def build_result_from_gsheet(supply_df: pd.DataFrame, ratio_df: pd.DataFrame) -> pd.DataFrame:
    """
    supply_df: index=용도, columns=Timestamp, 값=수급량GJ
    ratio_df : index=용도, columns=Timestamp, 값=구성비%
    반환: [연월, 용도, 그룹, 구성비(%), 공급량_GJ]
    """
    rows = []
    for col in supply_df.columns:
        if pd.isna(col):
            continue
        for usage in USAGE_LIST:
            if usage not in supply_df.index:
                continue
            gj_val  = float(supply_df.loc[usage, col]) if col in supply_df.columns else 0.0
            pct_val = float(ratio_df.loc[usage, col])  if (usage in ratio_df.index and col in ratio_df.columns) else 0.0
            rows.append({
                "연월":       col,
                "용도":       usage,
                "그룹":       GROUP_MAP.get(usage, "기타"),
                "구성비(%)":  pct_val,
                "공급량_GJ":  gj_val,
            })
    return pd.DataFrame(rows)

# ──────────────────────────────────────────────
# 구방식 GitHub 엑셀 로드
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
            # MJ → GJ
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

# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ 설정")
    st.markdown("#### 📂 구방식 비교 파일")
    uploaded_old = st.file_uploader(
        "상품별공급량_MJ실적.xlsx 업로드",
        type=["xlsx"],
        key="old_file",
        help="업로드하지 않으면 GitHub 파일을 자동으로 사용합니다."
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
st.caption("대성에너지(주) 마케팅본부 | 구글시트 수급량 × 용도별 구성비 → 용도별 공급량 산출")

# ── 신방식: 구글시트 로드
ratio_df, supply_df, dates, gs_err = load_new_gsheet()
if gs_err or ratio_df is None:
    st.error(f"구글시트 로드 실패: {gs_err}")
    st.info("구글시트를 **링크가 있는 모든 사용자 → 뷰어** 로 공유 설정해 주세요.")
    st.stop()

st.sidebar.success("✅ 구글시트 데이터 로드 완료")

# ── 기간 필터 (구글시트 날짜 기반)
def filter_by_year(df: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    """columns이 Timestamp인 DataFrame의 열을 연도로 필터"""
    cols = [c for c in df.columns if pd.notna(c) and start <= c.year <= end]
    return df[cols]

ratio_filtered  = filter_by_year(ratio_df,  y_start, y_end)
supply_filtered = filter_by_year(supply_df, y_start, y_end)

if supply_filtered.empty:
    st.warning("선택 기간에 데이터가 없습니다.")
    st.stop()

# ── result 빌드
result = build_result_from_gsheet(supply_filtered, ratio_filtered)
usage_order = USAGE_LIST

# ══════════════════════════════════════════════
# TAB 구성
# ══════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 용도별 공급량",
    "📋 구성비 확인",
    "🗃️ 원시 데이터",
    "🔍 구방식 vs 신방식 비교",
])

# ──────────────────────────────────────────────
# TAB 1 : 용도별 공급량
# ──────────────────────────────────────────────
with tab1:
    usage_total  = result.groupby("용도")["공급량_GJ"].sum()
    usage_sorted = usage_total.sort_values(ascending=False).index.tolist()
    usage_sorted = [u for u in usage_sorted if u in result["용도"].unique()]

    pivot = (
        result.pivot_table(index="연월", columns="용도", values="공급량_GJ", aggfunc="sum")
        .fillna(0)[usage_sorted]
    )

    result["연도"] = result["연월"].dt.year
    pivot_year = (
        result.groupby(["연도","용도"])["공급량_GJ"]
        .sum().unstack("용도").fillna(0)[usage_sorted]
    )

    # 연도별 누적 막대
    st.markdown('<div class="sub">📊 연도별 용도별 공급량 (GJ)</div>', unsafe_allow_html=True)
    fig_yr = go.Figure()
    for usage in usage_sorted:
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

    # 월별 누적 막대
    st.markdown('<div class="sub">📊 월별 용도별 공급량 (GJ)</div>', unsafe_allow_html=True)
    fig_mo = go.Figure()
    for usage in usage_sorted:
        fig_mo.add_trace(go.Bar(
            x=pivot.index, y=pivot[usage],
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

    # 연도별 테이블
    st.markdown('<div class="sub">📋 연도별 용도별 공급량 테이블 (GJ)</div>', unsafe_allow_html=True)
    tbl_yr = pivot_year[usage_sorted].copy().round(1)
    tbl_yr.index = tbl_yr.index.astype(str)
    tbl_yr["합계"] = tbl_yr.sum(axis=1)
    st.dataframe(tbl_yr.style.format("{:,.1f}"), use_container_width=True)

    buf_yr = BytesIO()
    with pd.ExcelWriter(buf_yr, engine="openpyxl") as w:
        tbl_yr.to_excel(w, sheet_name="연도별")
    st.download_button(
        "⬇️ 연도별 공급량 엑셀 다운로드", data=buf_yr.getvalue(),
        file_name=f"연도별_용도별공급량_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_yr",
    )

    st.markdown("---")

    # 월별 테이블
    st.markdown('<div class="sub">📋 월별 용도별 공급량 테이블 (GJ)</div>', unsafe_allow_html=True)
    tbl_mo = pivot[usage_sorted].copy().round(1)
    tbl_mo.index = tbl_mo.index.strftime("%Y-%m")
    tbl_mo["합계"] = tbl_mo.sum(axis=1)
    st.dataframe(tbl_mo.style.format("{:,.1f}"), use_container_width=True, height=340)

    buf_mo = BytesIO()
    with pd.ExcelWriter(buf_mo, engine="openpyxl") as w:
        tbl_mo.to_excel(w, sheet_name="월별")
    st.download_button(
        "⬇️ 월별 공급량 엑셀 다운로드", data=buf_mo.getvalue(),
        file_name=f"월별_용도별공급량_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_mo",
    )

# ──────────────────────────────────────────────
# TAB 2 : 구성비 확인
# ──────────────────────────────────────────────
with tab2:
    st.markdown('<div class="sub">📋 용도별 구성비 원본 (%) — 구글시트</div>', unsafe_allow_html=True)
    disp_ratio = ratio_filtered.copy()
    disp_ratio.columns = [c.strftime("%Y-%m") for c in disp_ratio.columns]
    st.dataframe(
        disp_ratio.style.format("{:.4f}"),
        use_container_width=True, height=430,
    )

    buf_ratio = BytesIO()
    with pd.ExcelWriter(buf_ratio, engine="openpyxl") as w:
        disp_ratio.to_excel(w, sheet_name="구성비")
    st.download_button(
        "⬇️ 구성비 엑셀 다운로드", data=buf_ratio.getvalue(),
        file_name=f"용도별구성비_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_ratio",
    )

# ──────────────────────────────────────────────
# TAB 3 : 원시 데이터 (구글시트 상품별수급량)
# ──────────────────────────────────────────────
with tab3:
    st.markdown('<div class="sub">📅 용도별 월별 수급량 (GJ) — 구글시트 원본</div>', unsafe_allow_html=True)
    disp_sup = supply_filtered.copy()
    disp_sup.columns = [c.strftime("%Y-%m") for c in disp_sup.columns]
    st.dataframe(
        disp_sup.style.format("{:,.1f}"),
        use_container_width=True, height=400,
    )

    buf_sup = BytesIO()
    with pd.ExcelWriter(buf_sup, engine="openpyxl") as w:
        disp_sup.to_excel(w, sheet_name="월별수급량")
    st.download_button(
        "⬇️ 월별 수급량 엑셀 다운로드", data=buf_sup.getvalue(),
        file_name=f"용도별수급량_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_sup",
    )

# ──────────────────────────────────────────────
# TAB 4 : 구방식 vs 신방식 비교
# ──────────────────────────────────────────────
def color_pct(val):
    if pd.isna(val): return ""
    return "color: #e8501a" if val >= 0 else "color: #2c5f8a"

with tab4:
    st.markdown('<div class="sub">🔍 구방식 vs 신방식 — 용도별 비교</div>', unsafe_allow_html=True)
    st.caption("구방식: GitHub 상품별공급량_MJ실적 (MJ→GJ 변환) | 신방식: 구글시트 수급량 (GJ)")

    # ── 구방식 데이터 로드
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

    # ── 비교 기간: 사이드바 조회 기간과 동일하게 적용
    CMP_START, CMP_END = y_start, y_end

    old_filtered_cmp = old_df[
        (old_df["연월"].dt.year >= CMP_START) &
        (old_df["연월"].dt.year <= CMP_END)
    ].copy()

    # 신방식: result에서 동일 기간
    new_filtered_cmp = result[
        (result["연월"].dt.year >= CMP_START) &
        (result["연월"].dt.year <= CMP_END)
    ].copy()

    common_usages = [u for u in OLD_COL_MAP.keys() if u in new_filtered_cmp["용도"].unique()]

    selected_usage = st.selectbox(
        "비교할 용도 선택",
        options=common_usages,
        index=common_usages.index("일반용") if "일반용" in common_usages else 0,
    )

    # 데이터 추출
    old_usage = old_filtered_cmp[old_filtered_cmp["용도"] == selected_usage].set_index("연월")["공급량_GJ"]
    new_usage = new_filtered_cmp[new_filtered_cmp["용도"] == selected_usage].set_index("연월")["공급량_GJ"]

    old_yr = old_usage.groupby(old_usage.index.year).sum()
    new_yr = new_usage.groupby(new_usage.index.year).sum()
    years  = sorted(set(old_yr.index) | set(new_yr.index))

    old_vals = [old_yr.get(y, 0) for y in years]
    new_vals = [new_yr.get(y, 0) for y in years]

    pct_list = []
    for o, n in zip(old_vals, new_vals):
        pct_list.append((n - o) / o * 100 if o else 0.0)

    # 연도별 비교 막대
    st.markdown(f'<div class="sub">📊 연도별 비교 — {selected_usage} (GJ)</div>', unsafe_allow_html=True)
    max_val = max(max(old_vals, default=1), max(new_vals, default=1))
    fig_cmp_yr = go.Figure()
    fig_cmp_yr.add_trace(go.Bar(
        x=[str(y) for y in years], y=old_vals,
        name="구방식 (상품별 실적)", marker_color="#2c5f8a",
        hovertemplate="구방식<br>%{x}년<br>%{y:,.0f} GJ<extra></extra>",
    ))
    fig_cmp_yr.add_trace(go.Bar(
        x=[str(y) for y in years], y=new_vals,
        name="신방식 (구글시트)", marker_color="#e8501a",
        hovertemplate="신방식<br>%{x}년<br>%{y:,.0f} GJ<extra></extra>",
    ))

    annotations = []
    for y, pct, nv in zip(years, pct_list, new_vals):
        sign  = "+" if pct >= 0 else ""
        color = "#e8501a" if pct >= 0 else "#2c5f8a"
        annotations.append(dict(
            x=str(y), y=nv + max_val * 0.02,
            text=f"<b>{sign}{pct:.1f}%</b>",
            showarrow=False,
            font=dict(size=13, color=color),
            xanchor="center", yanchor="bottom",
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

    # 월별 추이 라인
    st.markdown(f'<div class="sub">📈 월별 추이 비교 — {selected_usage} (GJ)</div>', unsafe_allow_html=True)
    st.caption("💡 마우스 휠: 확대/축소 | 마우스 드래그: 이동")
    fig_cmp_mo = go.Figure()
    fig_cmp_mo.add_trace(go.Scatter(
        x=old_usage.index, y=old_usage.values,
        name="구방식", mode="lines", line=dict(color="#2c5f8a", width=2),
        hovertemplate="구방식<br>%{x|%Y-%m}<br>%{y:,.0f} GJ<extra></extra>",
    ))
    fig_cmp_mo.add_trace(go.Scatter(
        x=new_usage.index, y=new_usage.values,
        name="신방식 (구글시트)", mode="lines", line=dict(color="#e8501a", width=2, dash="dot"),
        hovertemplate="신방식<br>%{x|%Y-%m}<br>%{y:,.0f} GJ<extra></extra>",
    ))
    fig_cmp_mo.update_layout(
        height=400, xaxis_title="연월", yaxis_title="공급량 (GJ)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=70, r=20, t=50, b=40),
        dragmode="pan",
    )
    fig_cmp_mo.update_yaxes(showgrid=True, gridcolor="#ebebeb", fixedrange=False)
    fig_cmp_mo.update_xaxes(fixedrange=False)
    st.plotly_chart(
        fig_cmp_mo, use_container_width=True,
        config={"scrollZoom": True, "displayModeBar": True,
                "modeBarButtonsToAdd": ["pan2d"],
                "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
    )

    st.markdown("---")

    # 특정 연도 월별 비교
    st.markdown(f'<div class="sub">📊 특정 연도 월별 비교 — {selected_usage} (GJ)</div>', unsafe_allow_html=True)

    avail_years = sorted(set(old_usage.index.year) & set(new_usage.index.year))
    if not avail_years:
        st.info("공통 연도 데이터가 없습니다.")
    else:
        sel_year = st.selectbox(
            "연도 선택", options=avail_years,
            index=len(avail_years) - 1, key="sel_year_monthly",
        )

        old_yr_total = old_yr.get(sel_year, 0)
        new_yr_total = new_yr.get(sel_year, 0)
        yr_diff      = new_yr_total - old_yr_total
        yr_pct       = yr_diff / old_yr_total * 100 if old_yr_total else 0
        sign_yr      = "+" if yr_pct >= 0 else ""
        pct_color    = "#e8501a" if yr_pct >= 0 else "#2c5f8a"

        st.markdown(f"""
        <div style="display:flex; gap:1rem; margin-bottom:1rem;">
            <div style="flex:1; background:#f4f8fc; border-left:4px solid #2c5f8a;
                        padding:0.8rem 1.2rem; border-radius:4px;">
                <div style="font-size:0.8rem; color:#666;">구방식 ({sel_year}년 합계)</div>
                <div style="font-size:1.3rem; font-weight:700; color:#2c5f8a;">{old_yr_total:,.0f} GJ</div>
            </div>
            <div style="flex:1; background:#fff4f0; border-left:4px solid #e8501a;
                        padding:0.8rem 1.2rem; border-radius:4px;">
                <div style="font-size:0.8rem; color:#666;">신방식 ({sel_year}년 합계)</div>
                <div style="font-size:1.3rem; font-weight:700; color:#e8501a;">{new_yr_total:,.0f} GJ</div>
            </div>
            <div style="flex:1; background:#f9f9f9; border-left:4px solid {pct_color};
                        padding:0.8rem 1.2rem; border-radius:4px;">
                <div style="font-size:0.8rem; color:#666;">{sel_year}년 전체 차이</div>
                <div style="font-size:1.5rem; font-weight:800; color:{pct_color};">
                    {sign_yr}{yr_pct:.2f}%
                </div>
                <div style="font-size:0.8rem; color:#888;">{sign_yr}{yr_diff:,.0f} GJ</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        MONTH_KR = ["1월","2월","3월","4월","5월","6월",
                     "7월","8월","9월","10월","11월","12월"]

        old_mo = old_usage[old_usage.index.year == sel_year].copy()
        new_mo = new_usage[new_usage.index.year == sel_year].copy()
        old_mo.index = old_mo.index.month
        new_mo.index = new_mo.index.month

        old_mo_vals = [old_mo.get(m, 0) for m in range(1, 13)]
        new_mo_vals = [new_mo.get(m, 0) for m in range(1, 13)]
        mo_pct = [(n - o) / o * 100 if o else 0.0 for o, n in zip(old_mo_vals, new_mo_vals)]

        max_mo = max(max(old_mo_vals, default=1), max(new_mo_vals, default=1))
        fig_mo_yr = go.Figure()
        fig_mo_yr.add_trace(go.Bar(
            x=MONTH_KR, y=old_mo_vals,
            name="구방식 (상품별 실적)", marker_color="#2c5f8a",
            hovertemplate="구방식<br>%{x}<br>%{y:,.0f} GJ<extra></extra>",
        ))
        fig_mo_yr.add_trace(go.Bar(
            x=MONTH_KR, y=new_mo_vals,
            name="신방식 (구글시트)", marker_color="#e8501a",
            hovertemplate="신방식<br>%{x}<br>%{y:,.0f} GJ<extra></extra>",
        ))

        mo_annotations = []
        for m, pct, nv in zip(MONTH_KR, mo_pct, new_mo_vals):
            sign  = "+" if pct >= 0 else ""
            color = "#e8501a" if pct >= 0 else "#2c5f8a"
            mo_annotations.append(dict(
                x=m, y=nv + max_mo * 0.02,
                text=f"<b>{sign}{pct:.1f}%</b>",
                showarrow=False,
                font=dict(size=13, color=color),
                xanchor="center", yanchor="bottom",
            ))

        fig_mo_yr.update_layout(
            barmode="group", height=420,
            title=dict(text=f"{sel_year}년 월별 비교 — {selected_usage}", font=dict(size=15)),
            xaxis_title="월", yaxis_title="공급량 (GJ)",
            yaxis=dict(range=[0, max_mo * 1.18], showgrid=True, gridcolor="#ebebeb"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            plot_bgcolor="white", paper_bgcolor="white",
            margin=dict(l=70, r=20, t=80, b=40),
            annotations=mo_annotations,
        )
        st.plotly_chart(fig_mo_yr, use_container_width=True)

        tbl_mo_yr = pd.DataFrame({
            "구방식_GJ": old_mo_vals,
            "신방식_GJ": new_mo_vals,
            "차이_GJ":   [n - o for o, n in zip(old_mo_vals, new_mo_vals)],
            "차이(%)":   mo_pct,
        }, index=MONTH_KR)
        tbl_mo_yr.index.name = "월"
        st.dataframe(
            tbl_mo_yr.style
                .format({"구방식_GJ": "{:,.1f}", "신방식_GJ": "{:,.1f}",
                         "차이_GJ": "{:,.1f}", "차이(%)": "{:+.2f}%"})
                .map(color_pct, subset=["차이(%)"]),
            use_container_width=True,
        )

    # 연도별 비교 테이블
    st.markdown(f'<div class="sub">📋 연도별 비교 테이블 — {selected_usage}</div>', unsafe_allow_html=True)
    tbl_cmp = pd.DataFrame({
        "구방식_GJ": old_yr,
        "신방식_GJ": new_yr,
    }).fillna(0).round(1)
    tbl_cmp["차이_GJ"]  = (tbl_cmp["신방식_GJ"] - tbl_cmp["구방식_GJ"]).round(1)
    tbl_cmp["차이(%)"]  = (tbl_cmp["차이_GJ"] / tbl_cmp["구방식_GJ"].replace(0, float("nan")) * 100).round(2)
    tbl_cmp.index.name  = "연도"

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
        f"⬇️ {selected_usage} 비교 엑셀 다운로드", data=buf_cmp.getvalue(),
        file_name=f"비교_{selected_usage}_{CMP_START}_{CMP_END}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_cmp",
    )
