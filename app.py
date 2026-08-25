import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from io import BytesIO, StringIO
import requests
import numpy as np

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
             padding:2px 10px; border-radius:12px; font-size:0.82rem; margin-right:6px; }
.info-box {
    background:#f4f8fc; border-radius:8px; padding:0.9rem 1.4rem;
    margin-bottom:1rem; border-left:4px solid #2c5f8a;
    font-size:0.92rem; line-height:2.2;
}
.info-row { display:grid; grid-template-columns:90px 1fr; align-items:center; gap:0 8px; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
NEW_GSHEET_ID  = "1gIhArPlLBJ9fwlaqXtZWxiKlSK9hbRuz6HcDw_Yf7Is"
NEW_GSHEET_URL = f"https://docs.google.com/spreadsheets/d/{NEW_GSHEET_ID}/export?format=csv&gid=0"
GITHUB_OLD_URL = "https://raw.githubusercontent.com/Han11112222/new_raw_data_gas-supply-forecast-by-usage/main/상품별공급량_MJ실적.xlsx"

HOUSING_PRODUCTS = ["취사용", "개별난방용", "중앙난방용", "자가열전용"]
OTHER_PRODUCTS   = ["일반용", "냉난방공조용", "업무난방용", "산업용",
                    "수송용", "열병합용", "연료전지용", "열전용설비용", "주한미군"]
PRODUCT_LIST     = HOUSING_PRODUCTS + OTHER_PRODUCTS

GROUP_MAP = {p: "주택용" for p in HOUSING_PRODUCTS}
GROUP_MAP.update({p: "기타" for p in OTHER_PRODUCTS})

COLOR_MAP = {
    "취사용":"#4e79a7","개별난방용":"#f28e2b","중앙난방용":"#e15759","자가열전용":"#76b7b2",
    "일반용":"#59a14f","냉난방공조용":"#edc948","업무난방용":"#b07aa1","산업용":"#ff9da7",
    "수송용":"#9c755f","열병합용":"#bab0ac","연료전지용":"#86bcb6","열전용설비용":"#d3a0a0",
    "주한미군":"#aecbcf",
}

TOTAL_ROW_IDX   = 1
DATE_HEADER_IDX = 3
RATIO_DATA_ROWS  = [4, 5, 6, 7,   9, 10, 11, 12, 13, 14, 15, 16, 17]
SUPPLY_DATA_ROWS = [24, 25, 26, 27, 29, 30, 31, 32, 33, 34, 35, 36, 37]

SUBTOTAL_LABEL = "소 계"
TOTAL_LABEL    = "합 계"
SUBTOTAL_STYLE = "background-color:#ddeaf8; font-weight:bold; color:#1a3c5e;"
TOTAL_STYLE    = "background-color:#c5d8f0; font-weight:bold; color:#1a3c5e;"

# ──────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────
@st.cache_data(ttl=1800)
def load_new_gsheet():
    try:
        resp = requests.get(NEW_GSHEET_URL, timeout=20)
        resp.raise_for_status()
        raw = pd.read_csv(StringIO(resp.text), header=None)
        dates = pd.to_datetime(raw.iloc[DATE_HEADER_IDX, 2:], errors="coerce")
        valid_cols = [i for i, d in enumerate(dates) if pd.notna(d)]
        dates_valid = dates.iloc[valid_cols]

        total_vals = pd.to_numeric(
            raw.iloc[TOTAL_ROW_IDX, 2:].iloc[valid_cols]
            .astype(str).str.replace(",", ""), errors="coerce").values
        total_supply_df = pd.DataFrame({"연월": dates_valid.values, "총공급량_GJ": total_vals})
        total_supply_df = total_supply_df[total_supply_df["총공급량_GJ"] > 0].reset_index(drop=True)

        def extract_rows(row_indices):
            result = {}
            for idx, row_i in enumerate(row_indices):
                if row_i >= len(raw): continue
                product = PRODUCT_LIST[idx]
                vals = pd.to_numeric(
                    raw.iloc[row_i, 2:].iloc[valid_cols]
                    .astype(str).str.replace(",", ""), errors="coerce").values
                result[product] = vals
            df = pd.DataFrame(result, index=dates_valid).T
            df.index.name = "상품"
            return df

        ratio_df  = extract_rows(RATIO_DATA_ROWS)
        supply_df = extract_rows(SUPPLY_DATA_ROWS)
        return total_supply_df, ratio_df, supply_df, dates_valid, None
    except Exception as e:
        return None, None, None, None, str(e)

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

def load_old_supply(file):
    df = pd.read_excel(file, sheet_name="공급량_실적", header=0)
    df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")
    df = df.dropna(subset=["날짜"])
    df["연월"] = df["날짜"].dt.to_period("M").dt.to_timestamp()
    rows = []
    for _, r in df.iterrows():
        for product, old_cols in OLD_COL_MAP.items():
            val = sum(pd.to_numeric(str(r[c]).replace(",",""), errors="coerce") or 0
                      for c in old_cols if c in df.columns)
            rows.append({"연월": r["연월"], "상품": product, "공급량_GJ": val / 1_000})
    res = pd.DataFrame(rows)
    return res.groupby(["연월","상품"])["공급량_GJ"].sum().reset_index()

@st.cache_data(ttl=3600)
def load_old_from_github():
    try:
        resp = requests.get(GITHUB_OLD_URL, timeout=15)
        resp.raise_for_status()
        return load_old_supply(BytesIO(resp.content)), None
    except Exception as e:
        return None, str(e)

def build_new_result(supply_df, ratio_df, y_start, y_end):
    rows = []
    for col in supply_df.columns:
        if pd.isna(col) or not (y_start <= col.year <= y_end): continue
        for product in PRODUCT_LIST:
            if product not in supply_df.index: continue
            rows.append({
                "연월": col, "상품": product,
                "그룹": GROUP_MAP.get(product, "기타"),
                "구성비(%)": float(ratio_df.loc[product, col]) if product in ratio_df.index else 0.0,
                "공급량_GJ": float(supply_df.loc[product, col]),
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["연도"] = df["연월"].dt.year
    return df

# ──────────────────────────────────────────────
# 피벗 빌더: 정산그룹 병합 표시용 (단일 인덱스)
# 행 순서: 주택용×4 + 소계 + 기타×9 + 소계 + 합계
# 정산그룹 열: 주택용(첫 행만), 빈칸×3, 소계, 기타(첫 행만), 빈칸×8, 소계, (빈칸)합계
# ──────────────────────────────────────────────
def build_pivot_flat(df_long: pd.DataFrame, value_col: str = "공급량_GJ"):
    """
    반환:
      display_df : 표시용 DataFrame
                   인덱스=정수(0~), 열=[정산그룹, 정산항목, YYYY-MM, ...]
      row_types  : list[str] — 'data'/'subtotal'/'total'
    정산그룹은 일반 열로 유지 (MultiIndex 사용 안 함 → 스타일러 호환)
    """
    pivot = (
        df_long.pivot_table(index="상품", columns="연월", values=value_col, aggfunc="sum")
        .fillna(0)
    )
    pivot = pivot[sorted(pivot.columns)]
    date_cols = [c.strftime("%Y-%m") for c in pivot.columns]
    pivot.columns = date_cols

    rows_data = []   # (group_label, item_label, row_type, Series)

    for group, products in [("주택용", HOUSING_PRODUCTS), ("기타", OTHER_PRODUCTS)]:
        for i, p in enumerate(products):
            row = pivot.loc[p].copy() if p in pivot.index else pd.Series(0.0, index=date_cols)
            g_label = group if i == 0 else ""
            rows_data.append((g_label, p, "data", row))

        sub_ps  = [p for p in products if p in pivot.index]
        sub_row = pivot.loc[sub_ps].sum() if sub_ps else pd.Series(0.0, index=date_cols)
        rows_data.append(("", SUBTOTAL_LABEL, "subtotal", sub_row))

    total_row = pivot.sum()
    rows_data.append(("", TOTAL_LABEL, "total", total_row))

    row_types = [r[2] for r in rows_data]

    # 단일 정수 인덱스 DataFrame으로 조립
    records = []
    for g_label, item, rtype, series in rows_data:
        rec = {"정산그룹": g_label, "정산항목": item}
        rec.update(series.to_dict())
        records.append(rec)

    display_df = pd.DataFrame(records)   # 인덱스: 0,1,2,...
    return display_df, row_types

# ──────────────────────────────────────────────
# 그라데이션 스타일러
# ──────────────────────────────────────────────
def style_pivot_flat(df: pd.DataFrame, row_types: list,
                     gradient: bool = False,
                     diff_mode: bool = False) -> "pd.io.formats.style.Styler":
    """
    df 인덱스는 정수(0,1,2,...).
    앞 두 열(정산그룹, 정산항목)은 텍스트 열 → 그라데이션 스킵.
    diff_mode=False : 파랑 계열 그라데이션 (공급량)
    diff_mode=True  : 양수=오렌지, 음수=파랑 (차이/차이율)
    """
    n_rows, n_cols = df.shape

    # 숫자 열 시작 인덱스 (정산그룹, 정산항목 = 앞 2열 스킵)
    TEXT_COLS = 2

    bg  = [[""] * n_cols for _ in range(n_rows)]
    txt = [[""] * n_cols for _ in range(n_rows)]

    # 그라데이션 기준: data 행의 숫자 열만
    abs_max = 1.0
    if gradient:
        data_mask = [t == "data" for t in row_types]
        try:
            data_vals = df.iloc[data_mask, TEXT_COLS:].values.astype(float)
            if diff_mode:
                abs_max = float(np.nanmax(np.abs(data_vals))) if data_vals.size > 0 else 1.0
            else:
                abs_max = float(np.nanmax(data_vals)) if data_vals.size > 0 else 1.0
        except Exception:
            abs_max = 1.0
    if abs_max == 0:
        abs_max = 1.0

    for i, rtype in enumerate(row_types):
        if rtype == "subtotal":
            for j in range(n_cols):
                bg[i][j]  = "background-color:#ddeaf8;"
                txt[i][j] = "font-weight:bold; color:#1a3c5e;"
        elif rtype == "total":
            for j in range(n_cols):
                bg[i][j]  = "background-color:#c5d8f0;"
                txt[i][j] = "font-weight:bold; color:#1a3c5e;"
        elif gradient:
            for j in range(TEXT_COLS, n_cols):   # 숫자 열만
                try:
                    val = float(df.iloc[i, j])
                    if np.isnan(val):
                        continue
                except Exception:
                    continue

                if diff_mode:
                    intensity = min(abs(val) / abs_max, 1.0)
                    alpha = 0.07 + intensity * 0.58
                    if val > 0:
                        bg[i][j]  = f"background-color:rgba(232,80,26,{alpha:.2f});"
                        if intensity > 0.55:
                            txt[i][j] = "color:#6b1500;"
                    elif val < 0:
                        bg[i][j]  = f"background-color:rgba(44,95,138,{alpha:.2f});"
                        if intensity > 0.55:
                            txt[i][j] = "color:#0a1f30;"
                else:
                    intensity = min(val / abs_max, 1.0) if val > 0 else 0.0
                    alpha = 0.05 + intensity * 0.55
                    r = int(44  + (1 - intensity) * 170)
                    g = int(95  + (1 - intensity) * 120)
                    b = int(138 + (1 - intensity) * 90)
                    bg[i][j] = f"background-color:rgba({r},{g},{b},{alpha:.2f});"
                    if intensity > 0.6:
                        txt[i][j] = "color:#fff;"

    def _apply_bg(df_):
        return pd.DataFrame(bg, index=df_.index, columns=df_.columns)
    def _apply_txt(df_):
        return pd.DataFrame(txt, index=df_.index, columns=df_.columns)

    return df.style.apply(_apply_bg, axis=None).apply(_apply_txt, axis=None)

def color_pct(val):
    if pd.isna(val): return ""
    return "color:#e8501a;" if val >= 0 else "color:#2c5f8a;"

def style_subtotal_any(df):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    if SUBTOTAL_LABEL in df.index:
        styles.loc[SUBTOTAL_LABEL] = SUBTOTAL_STYLE
    return styles

# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ 설정")
    st.markdown("#### 📂 이전방식 비교 파일")
    uploaded_old = st.file_uploader(
        "상품별공급량_MJ실적.xlsx 업로드", type=["xlsx"], key="old_file",
        help="업로드하지 않으면 GitHub 파일을 자동으로 사용합니다.")
    st.markdown("---")
    st.markdown("#### 📅 조회 기간")
    c1, c2 = st.columns(2)
    y_start = c1.number_input("시작", 2014, 2030, 2017)
    y_end   = c2.number_input("종료", 2014, 2030, 2025)

# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
st.title("🔥 도시가스 상품별 공급량 분석")
st.caption("대성에너지(주) 마케팅본부")

st.markdown("""
<div class="info-box">
  <div class="info-row">
    <div><span class="badge-old">이전방식</span></div>
    <div>총 공급량 = 상품별 공급량의 합산 &nbsp;|&nbsp; 상품별 공급량 비율 적용</div>
  </div>
  <div class="info-row">
    <div><span class="badge-new">신규방식</span></div>
    <div>총 공급량 = 상품별 공급량의 합산 &nbsp;|&nbsp; 가스공사 비용 정산 비율 반영</div>
  </div>
  <div style="margin-top:6px; color:#888; font-size:0.85rem;">
    ※ 이전방식과 신규방식은 상품별 비율 산출 기준이 달라 상품별 공급량이 다를 수 있습니다.
  </div>
</div>
""", unsafe_allow_html=True)

# ── 데이터 로드
total_supply_df, ratio_df, supply_df, dates, gs_err = load_new_gsheet()
if gs_err or ratio_df is None:
    st.error(f"구글시트 로드 실패: {gs_err}")
    st.info("구글시트를 **링크가 있는 모든 사용자 → 뷰어** 로 공유 설정해 주세요.")
    st.stop()
st.sidebar.success("✅ 구글시트(신규방식) 로드 완료")

if uploaded_old is not None:
    try:
        old_df = load_old_supply(uploaded_old)
        st.sidebar.success("✅ 이전방식 파일: 업로드 사용")
    except Exception as e:
        st.error(f"파일 파싱 오류: {e}"); st.stop()
else:
    old_df, old_err = load_old_from_github()
    if old_df is None:
        st.error(f"이전방식 파일 GitHub 로드 실패: {old_err}"); st.stop()
    st.sidebar.info("📡 이전방식 파일: GitHub 자동 사용")

new_result = build_new_result(supply_df, ratio_df, y_start, y_end)
old_result = old_df[(old_df["연월"].dt.year >= y_start) &
                    (old_df["연월"].dt.year <= y_end)].copy()
if not old_result.empty:
    old_result["연도"] = old_result["연월"].dt.year

total_filtered = total_supply_df[
    (pd.to_datetime(total_supply_df["연월"]).dt.year >= y_start) &
    (pd.to_datetime(total_supply_df["연월"]).dt.year <= y_end)].copy()

if new_result.empty:
    st.warning("선택 기간에 신규방식 데이터가 없습니다."); st.stop()

common_products = [p for p in OLD_COL_MAP.keys() if p in new_result["상품"].unique()]

# ══════════════════════════════════════════════
# TAB
# ══════════════════════════════════════════════
tab0, tab1, tab2 = st.tabs([
    "📊 전체 비교 (매트릭스)",
    "🔍 이전방식 vs 신규방식 상세 비교",
    "📋 구성비 및 raw 데이터 확인",
])

# ══════════════════════════════════════════════
# TAB 0 : 전체 비교 매트릭스
# ══════════════════════════════════════════════
with tab0:

    # ── 이전방식 피벗
    st.markdown('<div class="sub">📋 이전방식 — 상품별 월별 공급량 (GJ)</div>', unsafe_allow_html=True)
    old_pivot, old_rtypes = build_pivot_flat(old_result, "공급량_GJ")
    _old_num_cols = [c for c in old_pivot.columns if c not in ("정산그룹", "정산항목")]
    st.dataframe(
        style_pivot_flat(old_pivot, old_rtypes, gradient=True, diff_mode=False)
        .format(subset=_old_num_cols, formatter="{:,.0f}"),
        use_container_width=True, height=590,
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 신규방식 피벗
    st.markdown('<div class="sub">📋 신규방식 — 상품별 월별 공급량 (GJ)</div>', unsafe_allow_html=True)
    new_pivot, new_rtypes = build_pivot_flat(new_result, "공급량_GJ")
    _new_num_cols = [c for c in new_pivot.columns if c not in ("정산그룹", "정산항목")]
    st.dataframe(
        style_pivot_flat(new_pivot, new_rtypes, gradient=True, diff_mode=False)
        .format(subset=_new_num_cols, formatter="{:,.0f}"),
        use_container_width=True, height=590,
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 차이(GJ) 피벗
    st.markdown('<div class="sub">📋 차이 (신규 − 이전, GJ) — 클수록 진한 색상</div>', unsafe_allow_html=True)

    # 숫자 열(날짜 열)만 추출해서 차이 계산
    date_cols_old = [c for c in old_pivot.columns if c not in ("정산그룹", "정산항목")]
    date_cols_new = [c for c in new_pivot.columns if c not in ("정산그룹", "정산항목")]
    common_date_cols = sorted(set(date_cols_old) & set(date_cols_new))

    diff_num = (
        new_pivot[common_date_cols].values.astype(float) -
        old_pivot[common_date_cols].values.astype(float)
    )
    diff_pivot = old_pivot[["정산그룹", "정산항목"]].copy()
    for j, col in enumerate(common_date_cols):
        diff_pivot[col] = diff_num[:, j]

    st.dataframe(
        style_pivot_flat(diff_pivot, new_rtypes, gradient=True, diff_mode=True)
        .format(subset=common_date_cols, formatter="{:+,.0f}"),
        use_container_width=True, height=590,
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 차이율(%) 피벗
    st.markdown('<div class="sub">📋 차이율 (%, 신규/이전 기준) — 클수록 진한 색상</div>', unsafe_allow_html=True)

    old_num = old_pivot[common_date_cols].values.astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        pct_num = np.where(old_num != 0, diff_num / old_num * 100, np.nan)

    pct_pivot = old_pivot[["정산그룹", "정산항목"]].copy()
    for j, col in enumerate(common_date_cols):
        pct_pivot[col] = pct_num[:, j]

    st.dataframe(
        style_pivot_flat(pct_pivot, new_rtypes, gradient=True, diff_mode=True)
        .format(subset=common_date_cols, formatter="{:+.2f}%", na_rep="-"),
        use_container_width=True, height=590,
    )

    # 다운로드
    buf_matrix = BytesIO()
    with pd.ExcelWriter(buf_matrix, engine="openpyxl") as w:
        old_pivot.to_excel(w, sheet_name="이전방식", index=False)
        new_pivot.to_excel(w, sheet_name="신규방식", index=False)
        diff_pivot.to_excel(w, sheet_name="차이_GJ", index=False)
        pct_pivot.to_excel(w, sheet_name="차이율_%", index=False)
    st.download_button(
        "⬇️ 전체 매트릭스 엑셀 다운로드", data=buf_matrix.getvalue(),
        file_name=f"전체매트릭스_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_matrix",
    )


# ══════════════════════════════════════════════
# TAB 1 : 상품별 상세 비교
# ══════════════════════════════════════════════
with tab1:
    st.markdown("""
    <span class="badge-old">이전방식</span> 상품별 공급량 비율 적용 &nbsp;
    <span class="badge-new">신규방식</span> 가스공사 비용 정산 비율 반영
    <br><span style="color:#888; font-size:0.85rem; line-height:2.5;">
    ※ 두 방식 모두 월별 총 공급량(구글시트 D2행)을 기준으로 상품별 배분합니다.</span>
    <br><br>
    """, unsafe_allow_html=True)

    selected_product = st.selectbox(
        "비교할 상품 선택", options=common_products,
        index=common_products.index("개별난방용") if "개별난방용" in common_products else 0,
    )

    old_prod = old_result[old_result["상품"] == selected_product].set_index("연월")["공급량_GJ"]
    new_prod = new_result[new_result["상품"] == selected_product].set_index("연월")["공급량_GJ"]
    old_yr_p = old_prod.groupby(old_prod.index.year).sum()
    new_yr_p = new_prod.groupby(new_prod.index.year).sum()
    years_p  = sorted(set(old_yr_p.index) | set(new_yr_p.index))
    old_vals = [old_yr_p.get(y, 0) for y in years_p]
    new_vals = [new_yr_p.get(y, 0) for y in years_p]
    pct_list = [(n-o)/o*100 if o else 0.0 for o,n in zip(old_vals, new_vals)]

    st.markdown(f'<div class="sub">📊 연도별 비교 — {selected_product} (GJ)</div>', unsafe_allow_html=True)
    max_val = max(max(old_vals, default=1), max(new_vals, default=1))
    fig_cmp_yr = go.Figure()
    fig_cmp_yr.add_trace(go.Bar(
        x=[str(y) for y in years_p], y=old_vals,
        name="이전방식", marker_color="#2c5f8a",
        hovertemplate="이전방식<br>%{x}년<br>%{y:,.0f} GJ<extra></extra>",
    ))
    fig_cmp_yr.add_trace(go.Bar(
        x=[str(y) for y in years_p], y=new_vals,
        name="신규방식", marker_color="#e8501a",
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
        yaxis=dict(range=[0, max_val*1.15], showgrid=True, gridcolor="#ebebeb"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=70,r=20,t=70,b=40), annotations=annotations,
    )
    st.plotly_chart(fig_cmp_yr, use_container_width=True)

    st.markdown(f'<div class="sub">📈 월별 추이 비교 — {selected_product} (GJ)</div>', unsafe_allow_html=True)
    st.caption("💡 마우스 휠: 확대/축소 | 드래그: 이동")
    fig_cmp_mo = go.Figure()
    fig_cmp_mo.add_trace(go.Scatter(
        x=old_prod.index, y=old_prod.values, name="이전방식",
        mode="lines", line=dict(color="#2c5f8a", width=2),
        hovertemplate="이전방식<br>%{x|%Y-%m}<br>%{y:,.0f} GJ<extra></extra>",
    ))
    fig_cmp_mo.add_trace(go.Scatter(
        x=new_prod.index, y=new_prod.values, name="신규방식",
        mode="lines", line=dict(color="#e8501a", width=2, dash="dot"),
        hovertemplate="신규방식<br>%{x|%Y-%m}<br>%{y:,.0f} GJ<extra></extra>",
    ))
    fig_cmp_mo.update_layout(
        height=400, xaxis_title="연월", yaxis_title="공급량 (GJ)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=70,r=20,t=50,b=40), dragmode="pan",
    )
    fig_cmp_mo.update_yaxes(showgrid=True, gridcolor="#ebebeb", fixedrange=False)
    fig_cmp_mo.update_xaxes(fixedrange=False)
    st.plotly_chart(fig_cmp_mo, use_container_width=True,
        config={"scrollZoom":True,"displayModeBar":True,
                "modeBarButtonsToAdd":["pan2d"],
                "modeBarButtonsToRemove":["lasso2d","select2d"]})

    st.markdown("---")

    st.markdown(f'<div class="sub">📊 특정 연도 월별 비교 — {selected_product} (GJ)</div>', unsafe_allow_html=True)
    avail_years = sorted(set(old_prod.index.year) & set(new_prod.index.year))
    if not avail_years:
        st.info("공통 연도 데이터가 없습니다.")
    else:
        sel_year = st.selectbox("연도 선택", options=avail_years,
            index=len(avail_years)-1, key="sel_year_monthly")

        old_yr_total_v = old_yr_p.get(sel_year, 0)
        new_yr_total_v = new_yr_p.get(sel_year, 0)
        yr_diff = new_yr_total_v - old_yr_total_v
        yr_pct  = yr_diff / old_yr_total_v * 100 if old_yr_total_v else 0
        sign_yr = "+" if yr_pct >= 0 else ""
        pct_col = "#e8501a" if yr_pct >= 0 else "#2c5f8a"

        st.markdown(f"""
        <div style="display:flex; gap:1rem; margin-bottom:1rem;">
            <div style="flex:1; background:#f4f8fc; border-left:4px solid #2c5f8a; padding:0.8rem 1.2rem; border-radius:4px;">
                <div style="font-size:0.8rem; color:#666;">이전방식 ({sel_year}년 합계)</div>
                <div style="font-size:1.3rem; font-weight:700; color:#2c5f8a;">{old_yr_total_v:,.0f} GJ</div>
            </div>
            <div style="flex:1; background:#fff4f0; border-left:4px solid #e8501a; padding:0.8rem 1.2rem; border-radius:4px;">
                <div style="font-size:0.8rem; color:#666;">신규방식 ({sel_year}년 합계)</div>
                <div style="font-size:1.3rem; font-weight:700; color:#e8501a;">{new_yr_total_v:,.0f} GJ</div>
            </div>
            <div style="flex:1; background:#f9f9f9; border-left:4px solid {pct_col}; padding:0.8rem 1.2rem; border-radius:4px;">
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
        mo_pct = [(n-o)/o*100 if o else 0.0 for o,n in zip(old_mo_vals, new_mo_vals)]
        max_mo = max(max(old_mo_vals, default=1), max(new_mo_vals, default=1))

        fig_mo_yr = go.Figure()
        fig_mo_yr.add_trace(go.Bar(
            x=MONTH_KR, y=old_mo_vals, name="이전방식", marker_color="#2c5f8a",
            hovertemplate="이전방식<br>%{x}<br>%{y:,.0f} GJ<extra></extra>",
        ))
        fig_mo_yr.add_trace(go.Bar(
            x=MONTH_KR, y=new_mo_vals, name="신규방식", marker_color="#e8501a",
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
            yaxis=dict(range=[0, max_mo*1.18], showgrid=True, gridcolor="#ebebeb"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            plot_bgcolor="white", paper_bgcolor="white",
            margin=dict(l=70,r=20,t=80,b=40), annotations=mo_ann,
        )
        st.plotly_chart(fig_mo_yr, use_container_width=True)

        tbl_mo_yr = pd.DataFrame({
            "이전방식_GJ": old_mo_vals, "신규방식_GJ": new_mo_vals,
            "차이_GJ": [n-o for o,n in zip(old_mo_vals, new_mo_vals)],
            "차이(%)": mo_pct,
        }, index=MONTH_KR)
        tbl_mo_yr.index.name = "월"
        subtotal_mo = pd.DataFrame([{
            "이전방식_GJ": sum(old_mo_vals), "신규방식_GJ": sum(new_mo_vals),
            "차이_GJ": sum(new_mo_vals)-sum(old_mo_vals),
            "차이(%)": (sum(new_mo_vals)-sum(old_mo_vals))/sum(old_mo_vals)*100 if sum(old_mo_vals) else 0.0,
        }], index=[SUBTOTAL_LABEL])
        subtotal_mo.index.name = "월"
        tbl_mo_full = pd.concat([tbl_mo_yr, subtotal_mo])
        st.dataframe(
            tbl_mo_full.style
                .format({"이전방식_GJ":"{:,.1f}","신규방식_GJ":"{:,.1f}",
                         "차이_GJ":"{:,.1f}","차이(%)":"{:+.2f}%"})
                .apply(style_subtotal_any, axis=None)
                .map(color_pct, subset=["차이(%)"]),
            use_container_width=True,
        )

    st.markdown(f'<div class="sub">📋 연도별 비교 테이블 — {selected_product}</div>', unsafe_allow_html=True)
    tbl_cmp = pd.DataFrame({
        "이전방식_GJ": old_yr_p, "신규방식_GJ": new_yr_p,
    }).fillna(0).round(1)
    tbl_cmp["차이_GJ"] = (tbl_cmp["신규방식_GJ"] - tbl_cmp["이전방식_GJ"]).round(1)
    tbl_cmp["차이(%)"] = (
        tbl_cmp["차이_GJ"] / tbl_cmp["이전방식_GJ"].replace(0, float("nan")) * 100
    ).round(2)
    tbl_cmp.index.name = "연도"
    st.dataframe(
        tbl_cmp.style
            .format({"이전방식_GJ":"{:,.1f}","신규방식_GJ":"{:,.1f}",
                     "차이_GJ":"{:,.1f}","차이(%)":"{:+.2f}%"})
            .map(color_pct, subset=["차이(%)"]),
        use_container_width=True,
    )
    buf_cmp = BytesIO()
    with pd.ExcelWriter(buf_cmp, engine="openpyxl") as w:
        tbl_cmp.to_excel(w, sheet_name=f"{selected_product}_비교")
    st.download_button(
        f"⬇️ {selected_product} 비교 엑셀 다운로드", data=buf_cmp.getvalue(),
        file_name=f"비교_{selected_product}_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_cmp",
    )


# ══════════════════════════════════════════════
# TAB 2 : 구성비 및 raw 데이터 확인
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
        disp_ratio = disp_ratio[[c for c in disp_ratio.columns
                                  if pd.notna(c) and y_start <= c.year <= y_end]]
        disp_ratio.columns = [c.strftime("%Y-%m") for c in disp_ratio.columns]
        subtotal_r = pd.DataFrame([disp_ratio.sum(numeric_only=True)], index=[SUBTOTAL_LABEL])
        subtotal_r.index.name = disp_ratio.index.name
        disp_ratio_full = pd.concat([disp_ratio, subtotal_r])
        st.dataframe(
            disp_ratio_full.style.format("{:.4f}").apply(style_subtotal_any, axis=None),
            use_container_width=True, height=460,
        )
        buf_r = BytesIO()
        with pd.ExcelWriter(buf_r, engine="openpyxl") as w:
            disp_ratio_full.to_excel(w, sheet_name="구성비")
        st.download_button("⬇️ 구성비 엑셀 다운로드", data=buf_r.getvalue(),
            file_name=f"구성비_{y_start}_{y_end}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_ratio")

    with sub2:
        st.markdown('<div class="sub">상품별 월별 공급량 (GJ) — 구글시트 원본</div>', unsafe_allow_html=True)
        disp_sup = supply_df.copy()
        disp_sup = disp_sup[[c for c in disp_sup.columns
                              if pd.notna(c) and y_start <= c.year <= y_end]]
        disp_sup.columns = [c.strftime("%Y-%m") for c in disp_sup.columns]
        subtotal_s = pd.DataFrame([disp_sup.sum(numeric_only=True)], index=[SUBTOTAL_LABEL])
        subtotal_s.index.name = disp_sup.index.name
        disp_sup_full = pd.concat([disp_sup, subtotal_s])
        st.dataframe(
            disp_sup_full.style.format("{:,.1f}").apply(style_subtotal_any, axis=None),
            use_container_width=True, height=460,
        )
        buf_s = BytesIO()
        with pd.ExcelWriter(buf_s, engine="openpyxl") as w:
            disp_sup_full.to_excel(w, sheet_name="상품별공급량")
        st.download_button("⬇️ 상품별 공급량 엑셀 다운로드", data=buf_s.getvalue(),
            file_name=f"상품별공급량_{y_start}_{y_end}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_sup")

    with sub3:
        st.markdown('<div class="sub">월별 총 공급량 (GJ) — 구글시트 D2행</div>', unsafe_allow_html=True)
        st.caption("구글시트 2행의 총 공급량(GJ) — 신규방식 산출 기준")
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
