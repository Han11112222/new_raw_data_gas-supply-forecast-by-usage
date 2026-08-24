import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from io import BytesIO, StringIO
import requests

# ──────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="도시가스 상품별 공급량 분석",
    page_icon="🔥",
    layout="wide",
)

st.markdown("""
<style>
h1 { color: #1a3c5e; border-bottom: 3px solid #e8501a; padding-bottom: 0.3rem; }
.sub { font-size:1.05rem; font-weight:600; color:#2c5f8a; margin:1rem 0 0.3rem 0; }
.badge-old { display:inline-block; background:#2c5f8a; color:#fff;
             padding:2px 10px; border-radius:12px; font-size:0.82rem; margin-right:6px; }
.badge-new { display:inline-block; background:#e8501a; color:#fff;
             padding:2px 10px; border-radius:12px; font-size:0.82rem; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
NEW_GSHEET_ID  = "1gIhArPlLBJ9fwlaqXtZWxiKlSK9hbRuz6HcDw_Yf7Is"
NEW_GSHEET_URL = f"https://docs.google.com/spreadsheets/d/{NEW_GSHEET_ID}/export?format=csv&gid=0"

GITHUB_OLD_URL = "https://raw.githubusercontent.com/Han11112222/new_raw_data_gas-supply-forecast-by-usage/main/상품별공급량_MJ실적.xlsx"

PRODUCT_LIST = [
    "취사용", "개별난방용", "중앙난방용", "자가열전용",
    "일반용", "냉난방공조용", "업무난방용", "산업용",
    "수송용", "열병합용", "연료전지용", "열전용설비용", "주한미군",
]

# 구글시트 0-indexed 행 번호
# 행0=빈행, 행1=수급량(GJ), 행2=총공급량(GJ), 행3=구성비라벨, 행4=헤더
# 행5~8=주택용, 행9=소계, 행10~18=기타, 행19=소계, 행20=합계
# 행21=빈, 행22=빈, 행23=상품별분배라벨, 행24=헤더
# 행25~28=주택용, 행29=소계, 행30~37=기타

TOTAL_SUPPLY_ROW = 2        # 총 공급량(GJ) — D2 (0-indexed = 행1 아니라 행2이므로 인덱스 1)
# CSV로 읽으면 header=None이라 0-indexed 그대로:
#   실제 스프레드시트 행1 → raw.iloc[0]
#   실제 스프레드시트 행2 → raw.iloc[1]  ← 총 공급량
#   실제 스프레드시트 행4 → raw.iloc[3]  ← 날짜 헤더

TOTAL_ROW_IDX    = 1        # 총 공급량(GJ) row (0-indexed)
DATE_HEADER_IDX  = 3        # 날짜 헤더 row (0-indexed)
RATIO_DATA_ROWS  = [4, 5, 6, 7,   9, 10, 11, 12, 13, 14, 15, 16, 17]   # 구성비 (소계 제외)
SUPPLY_DATA_ROWS = [24, 25, 26, 27, 29, 30, 31, 32, 33, 34, 35, 36, 36] # 상품별 분배

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
# 구글시트 로드
# ──────────────────────────────────────────────
@st.cache_data(ttl=1800)
def load_new_gsheet() -> tuple:
    """
    구글시트에서:
      - 행2(0-indexed=1): 총 공급량(GJ) - 월별 합산값 → 신규방식 raw total
      - 행5~행18: 구성비(%) → 상품별 비율
      - 행25~행37: 상품별 분배(GJ) → 신규방식 상품별 공급량
    반환: (total_supply_df, ratio_df, supply_df, dates, 에러)
      total_supply_df: DataFrame [연월, 총공급량_GJ]
      ratio_df       : DataFrame (index=상품, columns=Timestamp, 값=구성비%)
      supply_df      : DataFrame (index=상품, columns=Timestamp, 값=공급량GJ)
    """
    try:
        resp = requests.get(NEW_GSHEET_URL, timeout=20)
        resp.raise_for_status()
        raw = pd.read_csv(StringIO(resp.text), header=None)

        # 날짜: 행4(0-indexed=3), C열~
        dates = pd.to_datetime(raw.iloc[DATE_HEADER_IDX, 2:], errors="coerce")
        valid_cols = [i for i, d in enumerate(dates) if pd.notna(d)]
        dates_valid = dates.iloc[valid_cols]

        # 총 공급량(GJ): 행2(0-indexed=1), C열~
        total_vals = pd.to_numeric(
            raw.iloc[TOTAL_ROW_IDX, 2:].iloc[valid_cols]
            .astype(str).str.replace(",", ""),
            errors="coerce"
        ).values

        total_supply_df = pd.DataFrame({
            "연월": dates_valid.values,
            "총공급량_GJ": total_vals,
        })
        total_supply_df = total_supply_df[total_supply_df["총공급량_GJ"] > 0].reset_index(drop=True)

        # 구성비 / 상품별분배 추출 함수
        def extract_rows(row_indices):
            result = {}
            for idx, row_i in enumerate(row_indices):
                if row_i >= len(raw):
                    continue
                product = PRODUCT_LIST[idx]
                vals = pd.to_numeric(
                    raw.iloc[row_i, 2:].iloc[valid_cols]
                    .astype(str).str.replace(",", ""),
                    errors="coerce"
                ).values
                result[product] = vals
            df = pd.DataFrame(result, index=dates_valid).T
            df.index.name = "상품"
            return df

        ratio_df  = extract_rows(RATIO_DATA_ROWS)
        supply_df = extract_rows(SUPPLY_DATA_ROWS)

        return total_supply_df, ratio_df, supply_df, dates_valid, None
    except Exception as e:
        return None, None, None, None, str(e)

# ──────────────────────────────────────────────
# 이전방식 GitHub 엑셀 로드
# ──────────────────────────────────────────────
OLD_COL_MAP = {
    "취사용":       ["취사용"],
    "개별난방용":   ["개별난방용"],
    "중앙난방용":   ["중앙난방용"],
    "자가열전용":   ["자가열전용"],
    "일반용":       ["영업용", "일반용(1)", "일반용(2)"],
    "냉난방공조용": ["냉난방용"],
    "업무난방용":   ["업무난방용"],
    "산업용":       ["산업용"],
    "수송용":       ["수송용(CNG)", "수송용(BIO)"],
    "열병합용":     ["열병합용"],
    "연료전지용":   ["연료전지용"],
    "열전용설비용": ["열전용설비용(주택외)"],
    "주한미군":     ["주한미군"],
}

def load_old_supply(file) -> pd.DataFrame:
    df = pd.read_excel(file, sheet_name="공급량_실적", header=0)
    df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")
    df = df.dropna(subset=["날짜"])
    df["연월"] = df["날짜"].dt.to_period("M").dt.to_timestamp()
    rows = []
    for _, r in df.iterrows():
        for product, old_cols in OLD_COL_MAP.items():
            val = sum(
                pd.to_numeric(str(r[c]).replace(",", ""), errors="coerce") or 0
                for c in old_cols if c in df.columns
            )
            rows.append({"연월": r["연월"], "상품": product, "공급량_GJ": val / 1_000})
    res = pd.DataFrame(rows)
    return res.groupby(["연월", "상품"])["공급량_GJ"].sum().reset_index()

@st.cache_data(ttl=3600)
def load_old_from_github() -> tuple:
    try:
        resp = requests.get(GITHUB_OLD_URL, timeout=15)
        resp.raise_for_status()
        return load_old_supply(BytesIO(resp.content)), None
    except Exception as e:
        return None, str(e)

# ──────────────────────────────────────────────
# 신규방식 result 빌드 (구글시트 상품별분배 사용)
# ──────────────────────────────────────────────
def build_new_result(supply_df: pd.DataFrame, ratio_df: pd.DataFrame,
                     y_start: int, y_end: int) -> pd.DataFrame:
    rows = []
    for col in supply_df.columns:
        if pd.isna(col) or not (y_start <= col.year <= y_end):
            continue
        for product in PRODUCT_LIST:
            if product not in supply_df.index:
                continue
            gj_val  = float(supply_df.loc[product, col])
            pct_val = float(ratio_df.loc[product, col]) if product in ratio_df.index else 0.0
            rows.append({
                "연월":      col,
                "상품":      product,
                "그룹":      GROUP_MAP.get(product, "기타"),
                "구성비(%)": pct_val,
                "공급량_GJ": gj_val,
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["연도"] = df["연월"].dt.year
    return df

def color_pct(val):
    if pd.isna(val): return ""
    return "color: #e8501a" if val >= 0 else "color: #2c5f8a"

# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ 설정")
    st.markdown("#### 📂 이전방식 비교 파일")
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
# 메인 타이틀
# ──────────────────────────────────────────────
st.title("🔥 도시가스 상품별 공급량 분석")
st.caption("대성에너지(주) 마케팅본부")

st.markdown("""
<div style="background:#f4f8fc; border-radius:8px; padding:0.9rem 1.2rem; margin-bottom:1rem;
            border-left:4px solid #2c5f8a; font-size:0.92rem; line-height:2.0;">
  <span class="badge-old">이전방식</span>
  총 공급량 = 상품별 공급량의 합산 &nbsp;|&nbsp; 상품별 공급량 비율 적용<br>
  <span class="badge-new">신규방식</span>
  총 공급량 = 상품별 공급량의 합산 &nbsp;|&nbsp; 가스공사 비용 정산 비율 반영<br>
  <span style="color:#888; font-size:0.85rem;">
    ※ 이전방식과 신규방식은 상품별 비율 산출 기준이 달라 상품별 공급량이 다를 수 있습니다.
  </span>
</div>
""", unsafe_allow_html=True)

# ── 데이터 로드: 구글시트(신규방식)
total_supply_df, ratio_df, supply_df, dates, gs_err = load_new_gsheet()
if gs_err or ratio_df is None:
    st.error(f"구글시트 로드 실패: {gs_err}")
    st.info("구글시트를 **링크가 있는 모든 사용자 → 뷰어** 로 공유 설정해 주세요.")
    st.stop()
st.sidebar.success("✅ 구글시트(신규방식) 로드 완료")

# ── 데이터 로드: 이전방식
if uploaded_old is not None:
    try:
        old_df = load_old_supply(uploaded_old)
        st.sidebar.success("✅ 이전방식 파일: 업로드 사용")
    except Exception as e:
        st.error(f"파일 파싱 오류: {e}")
        st.stop()
else:
    old_df, old_err = load_old_from_github()
    if old_df is None:
        st.error(f"이전방식 파일 GitHub 로드 실패: {old_err}")
        st.stop()
    st.sidebar.info("📡 이전방식 파일: GitHub 자동 사용")

# ── 신규방식 result
new_result = build_new_result(supply_df, ratio_df, y_start, y_end)

# ── 이전방식 기간 필터
old_result = old_df[
    (old_df["연월"].dt.year >= y_start) &
    (old_df["연월"].dt.year <= y_end)
].copy()
if not old_result.empty:
    old_result["연도"] = old_result["연월"].dt.year

# ── 총 공급량 기간 필터 (신규방식 raw)
total_filtered = total_supply_df[
    (pd.to_datetime(total_supply_df["연월"]).dt.year >= y_start) &
    (pd.to_datetime(total_supply_df["연월"]).dt.year <= y_end)
].copy()

if new_result.empty:
    st.warning("선택 기간에 신규방식 데이터가 없습니다.")
    st.stop()

# 상품 정렬 (신규방식 합계 기준)
product_total  = new_result.groupby("상품")["공급량_GJ"].sum()
product_sorted = product_total.sort_values(ascending=False).index.tolist()

# ══════════════════════════════════════════════
# TAB 구성 (2개)
# ══════════════════════════════════════════════
tab1, tab2 = st.tabs([
    "🔍 이전방식 vs 신규방식 비교",
    "📋 구성비 및 원시 데이터 확인",
])

# ══════════════════════════════════════════════
# TAB 1 : 이전방식 vs 신규방식 비교
# ══════════════════════════════════════════════
with tab1:
    st.markdown("""
    <span class="badge-old">이전방식</span> 상품별 공급량 비율 적용 &nbsp;
    <span class="badge-new">신규방식</span> 가스공사 비용 정산 비율 반영
    <br><span style="color:#888; font-size:0.85rem; line-height:2;">
    ※ 두 방식 모두 월별 총 공급량(구글시트 D2행)을 기준으로 상품별 배분합니다.</span>
    <br><br>
    """, unsafe_allow_html=True)

    common_products = [p for p in OLD_COL_MAP.keys() if p in new_result["상품"].unique()]
    selected_product = st.selectbox(
        "비교할 상품 선택",
        options=common_products,
        index=common_products.index("개별난방용") if "개별난방용" in common_products else 0,
    )

    old_prod = old_result[old_result["상품"] == selected_product].set_index("연월")["공급량_GJ"]
    new_prod = new_result[new_result["상품"] == selected_product].set_index("연월")["공급량_GJ"]

    old_yr_p = old_prod.groupby(old_prod.index.year).sum()
    new_yr_p = new_prod.groupby(new_prod.index.year).sum()
    years_p  = sorted(set(old_yr_p.index) | set(new_yr_p.index))
    old_vals = [old_yr_p.get(y, 0) for y in years_p]
    new_vals = [new_yr_p.get(y, 0) for y in years_p]
    pct_list = [(n - o) / o * 100 if o else 0.0 for o, n in zip(old_vals, new_vals)]

    # ── 연도별 비교 막대
    st.markdown(f'<div class="sub">📊 연도별 비교 — {selected_product} (GJ)</div>', unsafe_allow_html=True)
    max_val = max(max(old_vals, default=1), max(new_vals, default=1))
    fig_cmp_yr = go.Figure()
    fig_cmp_yr.add_trace(go.Bar(
        x=[str(y) for y in years_p], y=old_vals,
        name="이전방식 (총 공급량)", marker_color="#2c5f8a",
        hovertemplate="이전방식<br>%{x}년<br>%{y:,.0f} GJ<extra></extra>",
    ))
    fig_cmp_yr.add_trace(go.Bar(
        x=[str(y) for y in years_p], y=new_vals,
        name="신규방식 (총 공급량)", marker_color="#e8501a",
        hovertemplate="신규방식<br>%{x}년<br>%{y:,.0f} GJ<extra></extra>",
    ))
    annotations = []
    for y, pct, nv in zip(years_p, pct_list, new_vals):
        sign  = "+" if pct >= 0 else ""
        color = "#e8501a" if pct >= 0 else "#2c5f8a"
        annotations.append(dict(
            x=str(y), y=nv + max_val * 0.02,
            text=f"<b>{sign}{pct:.1f}%</b>",
            showarrow=False, font=dict(size=13, color=color),
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

    # ── 월별 추이 라인
    st.markdown(f'<div class="sub">📈 월별 추이 비교 — {selected_product} (GJ)</div>', unsafe_allow_html=True)
    st.caption("💡 마우스 휠: 확대/축소 | 드래그: 이동")
    fig_cmp_mo = go.Figure()
    fig_cmp_mo.add_trace(go.Scatter(
        x=old_prod.index, y=old_prod.values,
        name="이전방식", mode="lines", line=dict(color="#2c5f8a", width=2),
        hovertemplate="이전방식<br>%{x|%Y-%m}<br>%{y:,.0f} GJ<extra></extra>",
    ))
    fig_cmp_mo.add_trace(go.Scatter(
        x=new_prod.index, y=new_prod.values,
        name="신규방식", mode="lines", line=dict(color="#e8501a", width=2, dash="dot"),
        hovertemplate="신규방식<br>%{x|%Y-%m}<br>%{y:,.0f} GJ<extra></extra>",
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
    st.plotly_chart(fig_cmp_mo, use_container_width=True,
        config={"scrollZoom": True, "displayModeBar": True,
                "modeBarButtonsToAdd": ["pan2d"],
                "modeBarButtonsToRemove": ["lasso2d", "select2d"]})

    st.markdown("---")

    # ── 특정 연도 월별 비교
    st.markdown(f'<div class="sub">📊 특정 연도 월별 비교 — {selected_product} (GJ)</div>', unsafe_allow_html=True)
    avail_years = sorted(set(old_prod.index.year) & set(new_prod.index.year))
    if not avail_years:
        st.info("공통 연도 데이터가 없습니다.")
    else:
        sel_year = st.selectbox("연도 선택", options=avail_years,
            index=len(avail_years)-1, key="sel_year_monthly")

        old_yr_total_v = old_yr_p.get(sel_year, 0)
        new_yr_total_v = new_yr_p.get(sel_year, 0)
        yr_diff  = new_yr_total_v - old_yr_total_v
        yr_pct   = yr_diff / old_yr_total_v * 100 if old_yr_total_v else 0
        sign_yr  = "+" if yr_pct >= 0 else ""
        pct_col  = "#e8501a" if yr_pct >= 0 else "#2c5f8a"

        st.markdown(f"""
        <div style="display:flex; gap:1rem; margin-bottom:1rem;">
            <div style="flex:1; background:#f4f8fc; border-left:4px solid #2c5f8a;
                        padding:0.8rem 1.2rem; border-radius:4px;">
                <div style="font-size:0.8rem; color:#666;">이전방식 ({sel_year}년 합계)</div>
                <div style="font-size:1.3rem; font-weight:700; color:#2c5f8a;">{old_yr_total_v:,.0f} GJ</div>
            </div>
            <div style="flex:1; background:#fff4f0; border-left:4px solid #e8501a;
                        padding:0.8rem 1.2rem; border-radius:4px;">
                <div style="font-size:0.8rem; color:#666;">신규방식 ({sel_year}년 합계)</div>
                <div style="font-size:1.3rem; font-weight:700; color:#e8501a;">{new_yr_total_v:,.0f} GJ</div>
            </div>
            <div style="flex:1; background:#f9f9f9; border-left:4px solid {pct_col};
                        padding:0.8rem 1.2rem; border-radius:4px;">
                <div style="font-size:0.8rem; color:#666;">{sel_year}년 전체 차이</div>
                <div style="font-size:1.5rem; font-weight:800; color:{pct_col};">{sign_yr}{yr_pct:.2f}%</div>
                <div style="font-size:0.8rem; color:#888;">{sign_yr}{yr_diff:,.0f} GJ</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        MONTH_KR = ["1월","2월","3월","4월","5월","6월",
                     "7월","8월","9월","10월","11월","12월"]
        old_mo = old_prod[old_prod.index.year == sel_year].copy()
        new_mo = new_prod[new_prod.index.year == sel_year].copy()
        old_mo.index = old_mo.index.month
        new_mo.index = new_mo.index.month
        old_mo_vals = [old_mo.get(m, 0) for m in range(1, 13)]
        new_mo_vals = [new_mo.get(m, 0) for m in range(1, 13)]
        mo_pct = [(n - o) / o * 100 if o else 0.0 for o, n in zip(old_mo_vals, new_mo_vals)]
        max_mo = max(max(old_mo_vals, default=1), max(new_mo_vals, default=1))

        fig_mo_yr = go.Figure()
        fig_mo_yr.add_trace(go.Bar(
            x=MONTH_KR, y=old_mo_vals, name="이전방식 (총 공급량)", marker_color="#2c5f8a",
            hovertemplate="이전방식<br>%{x}<br>%{y:,.0f} GJ<extra></extra>",
        ))
        fig_mo_yr.add_trace(go.Bar(
            x=MONTH_KR, y=new_mo_vals, name="신규방식 (총 공급량)", marker_color="#e8501a",
            hovertemplate="신규방식<br>%{x}<br>%{y:,.0f} GJ<extra></extra>",
        ))
        mo_ann = []
        for m, pct, nv in zip(MONTH_KR, mo_pct, new_mo_vals):
            sign  = "+" if pct >= 0 else ""
            color = "#e8501a" if pct >= 0 else "#2c5f8a"
            mo_ann.append(dict(
                x=m, y=nv + max_mo * 0.02,
                text=f"<b>{sign}{pct:.1f}%</b>",
                showarrow=False, font=dict(size=13, color=color),
                xanchor="center", yanchor="bottom",
            ))
        fig_mo_yr.update_layout(
            barmode="group", height=420,
            title=dict(text=f"{sel_year}년 월별 비교 — {selected_product}", font=dict(size=15)),
            xaxis_title="월", yaxis_title="공급량 (GJ)",
            yaxis=dict(range=[0, max_mo * 1.18], showgrid=True, gridcolor="#ebebeb"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            plot_bgcolor="white", paper_bgcolor="white",
            margin=dict(l=70, r=20, t=80, b=40),
            annotations=mo_ann,
        )
        st.plotly_chart(fig_mo_yr, use_container_width=True)

        # 월별 비교 테이블 + 소계 행
        mo_data = {
            "이전방식_GJ": old_mo_vals,
            "신규방식_GJ": new_mo_vals,
            "차이_GJ":     [n - o for o, n in zip(old_mo_vals, new_mo_vals)],
            "차이(%)":     mo_pct,
        }
        tbl_mo_yr = pd.DataFrame(mo_data, index=MONTH_KR)
        tbl_mo_yr.index.name = "월"

        # 소계 행 추가
        subtotal = pd.DataFrame([{
            "이전방식_GJ": sum(old_mo_vals),
            "신규방식_GJ": sum(new_mo_vals),
            "차이_GJ":     sum(new_mo_vals) - sum(old_mo_vals),
            "차이(%)":     (sum(new_mo_vals) - sum(old_mo_vals)) / sum(old_mo_vals) * 100
                           if sum(old_mo_vals) else 0.0,
        }], index=["소 계"])
        subtotal.index.name = "월"
        tbl_mo_full = pd.concat([tbl_mo_yr, subtotal])

        # 스타일 함수 (소계 행 배경 강조)
        def style_table(df):
            styles = pd.DataFrame("", index=df.index, columns=df.columns)
            if "소 계" in df.index:
                styles.loc["소 계"] = "background-color: #e8f0fb; font-weight: bold; color: #1a3c5e;"
            return styles

        st.dataframe(
            tbl_mo_full.style
                .format({"이전방식_GJ": "{:,.1f}", "신규방식_GJ": "{:,.1f}",
                         "차이_GJ": "{:,.1f}", "차이(%)": "{:+.2f}%"})
                .apply(style_table, axis=None)
                .map(color_pct, subset=["차이(%)"]),
            use_container_width=True,
        )

    # ── 연도별 비교 테이블 + 소계
    st.markdown(f'<div class="sub">📋 연도별 비교 테이블 — {selected_product}</div>', unsafe_allow_html=True)
    tbl_cmp = pd.DataFrame({
        "이전방식_GJ": old_yr_p,
        "신규방식_GJ": new_yr_p,
    }).fillna(0).round(1)
    tbl_cmp["차이_GJ"] = (tbl_cmp["신규방식_GJ"] - tbl_cmp["이전방식_GJ"]).round(1)
    tbl_cmp["차이(%)"] = (
        tbl_cmp["차이_GJ"] / tbl_cmp["이전방식_GJ"].replace(0, float("nan")) * 100
    ).round(2)
    tbl_cmp.index.name = "연도"

    # 소계 행 추가
    yr_subtotal = pd.DataFrame([{
        "이전방식_GJ": tbl_cmp["이전방식_GJ"].sum(),
        "신규방식_GJ": tbl_cmp["신규방식_GJ"].sum(),
        "차이_GJ":     tbl_cmp["차이_GJ"].sum(),
        "차이(%)":     tbl_cmp["차이_GJ"].sum() / tbl_cmp["이전방식_GJ"].sum() * 100
                       if tbl_cmp["이전방식_GJ"].sum() else 0.0,
    }], index=["소 계"])
    yr_subtotal.index.name = "연도"
    tbl_cmp_full = pd.concat([tbl_cmp, yr_subtotal])

    st.dataframe(
        tbl_cmp_full.style
            .format({"이전방식_GJ": "{:,.1f}", "신규방식_GJ": "{:,.1f}",
                     "차이_GJ": "{:,.1f}", "차이(%)": "{:+.2f}%"})
            .apply(style_table, axis=None)
            .map(color_pct, subset=["차이(%)"]),
        use_container_width=True,
    )

    buf_cmp = BytesIO()
    with pd.ExcelWriter(buf_cmp, engine="openpyxl") as w:
        tbl_cmp_full.to_excel(w, sheet_name=f"{selected_product}_비교")
    st.download_button(
        f"⬇️ {selected_product} 비교 엑셀 다운로드", data=buf_cmp.getvalue(),
        file_name=f"비교_{selected_product}_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_cmp",
    )


# ══════════════════════════════════════════════
# TAB 2 : 구성비 및 원시 데이터 확인
# ══════════════════════════════════════════════
with tab2:
    sub1, sub2, sub3 = st.tabs([
        "📋 구성비 (신규방식)",
        "🗃️ 상품별 공급량 원본 (신규방식)",
        "📅 월별 총 공급량 (구글시트 D2)",
    ])

    with sub1:
        st.markdown('<div class="sub">구성비 (%) — 가스공사 비용 정산 비율</div>', unsafe_allow_html=True)
        disp_ratio = ratio_df.copy()
        # 기간 필터
        disp_ratio = disp_ratio[[c for c in disp_ratio.columns
                                  if pd.notna(c) and y_start <= c.year <= y_end]]
        disp_ratio.columns = [c.strftime("%Y-%m") for c in disp_ratio.columns]
        st.dataframe(disp_ratio.style.format("{:.4f}"), use_container_width=True, height=430)
        buf_r = BytesIO()
        with pd.ExcelWriter(buf_r, engine="openpyxl") as w:
            disp_ratio.to_excel(w, sheet_name="구성비")
        st.download_button("⬇️ 구성비 엑셀 다운로드", data=buf_r.getvalue(),
            file_name=f"구성비_{y_start}_{y_end}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_ratio")

    with sub2:
        st.markdown('<div class="sub">상품별 월별 공급량 (GJ) — 구글시트 원본</div>', unsafe_allow_html=True)
        disp_sup = supply_df.copy()
        disp_sup = disp_sup[[c for c in disp_sup.columns
                              if pd.notna(c) and y_start <= c.year <= y_end]]
        disp_sup.columns = [c.strftime("%Y-%m") for c in disp_sup.columns]
        st.dataframe(disp_sup.style.format("{:,.1f}"), use_container_width=True, height=400)
        buf_s = BytesIO()
        with pd.ExcelWriter(buf_s, engine="openpyxl") as w:
            disp_sup.to_excel(w, sheet_name="상품별공급량")
        st.download_button("⬇️ 상품별 공급량 엑셀 다운로드", data=buf_s.getvalue(),
            file_name=f"상품별공급량_{y_start}_{y_end}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_sup")

    with sub3:
        st.markdown('<div class="sub">월별 총 공급량 (GJ) — 구글시트 D2행</div>', unsafe_allow_html=True)
        st.caption("구글시트 2행의 총 공급량(GJ) 데이터 — 신규방식 산출 기준")
        disp_total = total_filtered.copy()
        disp_total["연월"] = pd.to_datetime(disp_total["연월"]).dt.strftime("%Y-%m")
        disp_total["총공급량_GJ"] = disp_total["총공급량_GJ"].round(1)
        st.dataframe(
            disp_total.style.format({"총공급량_GJ": "{:,.1f}"}),
            use_container_width=True, height=400,
        )
        buf_t = BytesIO()
        with pd.ExcelWriter(buf_t, engine="openpyxl") as w:
            disp_total.to_excel(w, sheet_name="월별총공급량", index=False)
        st.download_button("⬇️ 월별 총 공급량 엑셀 다운로드", data=buf_t.getvalue(),
            file_name=f"월별총공급량_{y_start}_{y_end}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_total")
