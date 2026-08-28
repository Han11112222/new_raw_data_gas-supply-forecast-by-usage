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
.badge-kogas { display:inline-block; background:#0097b2; color:#fff;
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

GROUP_SPANS = [
    ("주택용", len(HOUSING_PRODUCTS) + 1),
    ("기타",   len(OTHER_PRODUCTS)   + 1),
]

TOTAL_ROW_IDX   = 1    # 행2(0-indexed=1): 총 공급량(GJ)
NATGAS_ROW_IDX  = 3    # 행4(0-indexed=3): 천연가스 공급량(GJ) = BIO 제외 총량
TOTAL_START_COL = 2    # 총공급량/천연가스 행은 C열(idx=2)부터 날짜 데이터
DATE_HEADER_IDX = 25   # 행26(0-indexed=25): 상품별분배 날짜 헤더
DATA_START_COL  = 3    # 구성비/분배 데이터 시작 열 (D열=3, A~C=0~2)
# 구성비: 행5는 "구성비" 라벨, 행6~23까지 구성비 데이터
# 이미지 기준(0-indexed): 구성비 헤더=행5, 데이터행=행6~19
# 상품별분배: 헤더=행25, 데이터행=행26~39
RATIO_DATA_ROWS  = [6, 7, 8, 9,   11, 12, 13, 14, 15, 16, 17, 18, 19]   # 구성비 데이터 행
SUPPLY_DATA_ROWS = [26, 27, 28, 29, 31, 32, 33, 34, 35, 36, 37, 38, 39] # 상품별분배 데이터 행

SUBTOTAL_LABEL = "소 계"
TOTAL_LABEL    = "합 계"
SUBTOTAL_STYLE = "background-color:#ddeaf8; font-weight:bold; color:#1a3c5e;"

# ──────────────────────────────────────────────
# KOGAS 제출 물량 — 판매량(MJ) 기준으로 구성비 재계산
# 출처: 한국가스공사 제출용 구성비 2025.01~12 / 판매량(MJ) 열 사용
# ──────────────────────────────────────────────
_KOGAS_SALES_MJ = {
    # 판매량(MJ) — 자가소모 제외한 순수 판매량
    "취사용":       [22508020,      22577641.8714,  20619854.7301,  20555869.5196,
                    19464912.8195,  19208315.8503,  18486609.9488,  18781399.7069,
                    18023947.6279,  19973230.6939,  20033611.0042,  21151638.5849],
    "개별난방용":   [4601772442,    4661302339.4723, 3160609816.0333, 1642867844.6371,
                    1057371508.7759, 634292658.3708, 483145021.0925, 425021509.6008,
                    480674701.0690, 1029298145.8647, 2461104910.2985, 4453646847.3386],
    "중앙난방용":   [108064211,     98122572.1497,  81515348.4942,  44989505.3968,
                    24135510.9806,  16827651.0218,  11960106.1481,  9572967.6972,
                    12346635.2679,  28037892.3927,  57492331.3318,  88198469.7410],
    "자가열전용":   [73321702,      68217256.5968,  41847586.5865,  18126708.0430,
                    9789260.3598,   7013854.5389,   3642302.4638,   3536621.0753,
                    4359081.8933,   11459312.1309,  31970956.4170,  60710880.2353],
    "일반용":       [380155058,     345892153.1467, 358364786.5859, 303131726.6613,
                    287013884.3114, 243920918.5071, 232490040.0485, 217981730.6294,
                    226816417.4180, 272478528.0234, 310414128.6169, 372453589.7506],
    "냉난방공조용": [163484146,     168032417.4858, 84622567.2968,  32106464.4654,
                    51663085.1967,  138471075.4124, 211499706.1630, 222730024.3879,
                    167565544.1565, 54068568.5656,  61819400.6836,  141045583.6353],
    "업무난방용":   [105831937,     137872849.5697, 87183302.6296,  44438606.8873,
                    20288170.9532,  21330580.2042,  17996786.4652,  17198446.9251,
                    18977535.4561,  18899535.3144,  69087649.5126,  120826118.7412],
    "산업용":       [876935403,     883940217.5498, 824439602.0200, 793061906.6426,
                    728629307.8986, 690310823.8775, 706786817.5483, 659943859.4157,
                    725048473.1511, 685046725.1428, 817465931.5638, 847848530.7028],
    "수송용":       [245230758,     236341015.6950, 251630783.5494, 251298300.9538,
                    262403158.8939, 259332171.3476, 282160534.9959, 277821651.0915,
                    266680584.4900, 249985920.3632, 250148113.8952, 264560653.6417],
    "열병합용":     [25962363,      24585055.9268,  25513126.0772,  22323074.6776,
                    17784555.5029,  10947906.8965,  17472109.5237,  17776482.5076,
                    13676270.1798,  13817935.6272,  19036035.7712,  27172582.9298],
    "연료전지용":   [19407276,      14839232.3865,  17590385.0715,  16706989.8312,
                    16844042.7317,  17064584.9057,  16593745.1583,  16777239.1856,
                    18032621.6369,  18415368.2804,  16902463.0004,  19498114.0156],
    "열전용설비용": [787200,        879787.5300,    606910.0640,    1199348.1290,
                    464678.8650,    537097.3200,    1060136.9850,   571528.0480,
                    540267.2600,    502299.8500,    18025286.3000,  13448176.6320],
    "주한미군":     [12186297,      10672541.8819,  6854857.0958,   2520799.6358,
                    2226799.2964,   1870822.2538,   1625846.1678,   1585241.3217,
                    1923349.8831,   2258927.1759,   5376100.8906,   9690043.6337],
}

_KOGAS_MONTHS = [f"2025-{m:02d}" for m in range(1, 13)]

# 판매량(MJ) → GJ 변환 DataFrame (index=상품, columns=YYYY-MM)
_KOGAS_SALES_DF = pd.DataFrame(
    {p: [v / 1000.0 for v in vals] for p, vals in _KOGAS_SALES_MJ.items()},
    index=_KOGAS_MONTHS
).T
_KOGAS_SALES_DF.index.name = "상품"

# 판매량 월별 합계(GJ) — 구성비 분모
_KOGAS_SALES_TOTAL_GJ = _KOGAS_SALES_DF.sum(axis=0)  # Series: index=YYYY-MM

# 판매량 기준 구성비(비율, 0~1) — index=상품, columns=YYYY-MM
_KOGAS_RATIO = _KOGAS_SALES_DF.div(_KOGAS_SALES_TOTAL_GJ)

# KOGAS_GJ는 스프레드시트 총 공급량 로드 후 계산
# = 판매량 구성비 × 스프레드시트 월별 총 공급량
# (아래 데이터 로드 완료 후 build_kogas_gj() 호출로 설정)
KOGAS_GJ = None  # placeholder

# ──────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────
@st.cache_data(ttl=1800)
def load_new_gsheet():
    try:
        resp = requests.get(NEW_GSHEET_URL, timeout=20)
        resp.raise_for_status()
        raw = pd.read_csv(StringIO(resp.text), header=None)
        # 상품별분배 날짜 헤더: 행26(0-indexed=25), D열(idx=3)부터
        dates = pd.to_datetime(raw.iloc[DATE_HEADER_IDX, DATA_START_COL:], errors="coerce")
        valid_cols = [i for i, d in enumerate(dates) if pd.notna(d)]
        dates_valid = dates.iloc[valid_cols]

        # 총 공급량(GJ): 행2(0-indexed=1), C열(idx=2)부터
        # 천연가스 공급량(GJ): 행4(0-indexed=3), C열(idx=2)부터 — BIO 제외 총량
        # 전체 코드에서 이 값을 총량 기준으로 통일 사용
        natgas_raw = raw.iloc[NATGAS_ROW_IDX, TOTAL_START_COL:].reset_index(drop=True)
        natgas_vals = pd.to_numeric(
            natgas_raw.iloc[[v + 1 for v in valid_cols]]
            .astype(str).str.replace(",", ""), errors="coerce").values
        natgas_supply_df = pd.DataFrame({"연월": dates_valid.values, "천연가스공급량_GJ": natgas_vals})
        natgas_supply_df = natgas_supply_df[natgas_supply_df["천연가스공급량_GJ"] > 0].reset_index(drop=True)

        # total_supply_df = 천연가스 공급량(행4) 기준으로 통일
        total_supply_df = natgas_supply_df.rename(columns={"천연가스공급량_GJ": "총공급량_GJ"})

        def extract_rows(row_indices):
            result = {}
            for idx, row_i in enumerate(row_indices):
                if row_i >= len(raw): continue
                product = PRODUCT_LIST[idx]
                vals = pd.to_numeric(
                    raw.iloc[row_i, DATA_START_COL:].iloc[valid_cols]
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
    "수송용":       ["수송용(CNG)"],   # BIO 제외
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

def build_new_result(supply_df, ratio_df, y_start, y_end, natgas_series=None):
    """
    신규방식 공급량 계산.
    natgas_series: 천연가스 공급량(행4, BIO 제외) Series (index=Timestamp).
                   제공 시 상품별분배값을 행4 기준으로 보정.
    """
    rows = []
    for col in supply_df.columns:
        if pd.isna(col) or not (y_start <= col.year <= y_end): continue
        # 행4(천연가스) 보정 비율 계산
        if natgas_series is not None and col in natgas_series.index:
            ng_val = float(natgas_series[col])
            col_str = col.strftime("%Y-%m") if hasattr(col, "strftime") else str(col)
            # 상품별분배 합계 = 행2 총공급량 → 행4로 스케일 조정
            sub_sum = sum(
                float(supply_df.loc[p, col]) for p in PRODUCT_LIST if p in supply_df.index
            )
            scale = ng_val / sub_sum if sub_sum > 0 else 1.0
        else:
            scale = 1.0
        for product in PRODUCT_LIST:
            if product not in supply_df.index: continue
            raw_val = float(supply_df.loc[product, col])
            rows.append({
                "연월": col, "상품": product,
                "그룹": GROUP_MAP.get(product, "기타"),
                "구성비(%)": float(ratio_df.loc[product, col]) if product in ratio_df.index else 0.0,
                "공급량_GJ": raw_val * scale,  # 행4 기준으로 보정
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["연도"] = df["연월"].dt.year
    return df

# ──────────────────────────────────────────────
# 피벗 빌더
# ──────────────────────────────────────────────
def build_pivot_flat(df_long: pd.DataFrame, value_col: str = "공급량_GJ"):
    pivot = (
        df_long.pivot_table(index="상품", columns="연월", values=value_col, aggfunc="sum")
        .fillna(0)
    )
    pivot = pivot[sorted(pivot.columns)]
    date_cols = [c.strftime("%Y-%m") for c in pivot.columns]
    pivot.columns = date_cols

    rows_data = []
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
    records = []
    for g_label, item, rtype, series in rows_data:
        rec = {"정산그룹": g_label, "정산항목": item}
        rec.update(series.to_dict())
        records.append(rec)

    display_df = pd.DataFrame(records)
    return display_df, row_types

# ──────────────────────────────────────────────
# HTML 테이블 렌더러
# ──────────────────────────────────────────────
_TABLE_CSS = """
<style>
.pivot-wrap {
    overflow-x: auto; overflow-y: auto; max-height: 620px;
    margin-bottom: 1rem; border-radius: 6px; border: 1px solid #c8d8e8;
}
.pivot-tbl {
    border-collapse: collapse; font-size: 0.78rem;
    font-family: 'Segoe UI', 'Noto Sans KR', sans-serif;
    white-space: nowrap; min-width: 100%;
}
.pivot-tbl thead th {
    background: #2c5f8a; color: #fff; padding: 6px 10px;
    text-align: center; position: sticky; top: 0; z-index: 3;
    border: 1px solid #1a3c5e; font-weight: 600;
}
.pivot-tbl th.th-grp  { min-width: 58px; }
.pivot-tbl th.th-item { min-width: 96px; text-align: left; padding-left:10px; }
.pivot-tbl th.th-date { min-width: 72px; }
.pivot-tbl td { padding: 4px 10px; text-align: right; border: 1px solid #dde3ea; }
.pivot-tbl td.td-group {
    text-align: center; font-weight: 700; color: #1a3c5e;
    background: #eaf1f8 !important; border-right: 2px solid #2c5f8a;
    vertical-align: middle; position: sticky; left: 0; z-index: 1;
}
.pivot-tbl td.td-item {
    text-align: left; padding-left: 14px; background: #fff;
    position: sticky; left: 62px; z-index: 1; border-right: 1px solid #c8d8e8;
}
.pivot-tbl tr.row-data:hover td { background: #f0f6ff !important; }
.pivot-tbl tr.row-sub  td { background: #ddeaf8 !important; font-weight:700; color:#1a3c5e; }
.pivot-tbl tr.row-sub  td.td-item { text-align:center; padding-left:0; }
.pivot-tbl tr.row-total td { background: #c5d8f0 !important; font-weight:700; color:#1a3c5e; }
.pivot-tbl tr.row-total td.td-item { text-align:center; padding-left:0; }
</style>
"""

def _gradient_bg(val, abs_max, diff_mode):
    if abs_max == 0 or np.isnan(val): return ""
    intensity = min(abs(val) / abs_max, 1.0)
    alpha = 0.06 + intensity * 0.55
    if diff_mode:
        if val > 0: return f"background-color:rgba(232,80,26,{alpha:.2f});"
        elif val < 0: return f"background-color:rgba(44,95,138,{alpha:.2f});"
        return ""
    else:
        r = int(44  + (1 - intensity) * 170)
        g = int(95  + (1 - intensity) * 120)
        b = int(138 + (1 - intensity) * 90)
        return f"background-color:rgba({r},{g},{b},{alpha:.2f});"

def _diff_text_color(val):
    try:
        if val > 0: return "color:#9b2a00;"
        if val < 0: return "color:#0a2a44;"
    except: pass
    return ""

def build_html_pivot(display_df, row_types, fmt_func=None, diff_mode=False, gradient=True):
    date_cols = [c for c in display_df.columns if c not in ("정산그룹", "정산항목")]
    df = display_df.reset_index(drop=True)

    abs_max = 1.0
    if gradient:
        data_mask = [i for i, t in enumerate(row_types) if t == "data"]
        try:
            data_vals = df.loc[data_mask, date_cols].values.astype(float)
            abs_max = float(np.nanmax(np.abs(data_vals))) if diff_mode else float(np.nanmax(data_vals))
            if abs_max == 0: abs_max = 1.0
        except: abs_max = 1.0

    group_cell = {}
    gi = 0
    for gname, gspan in GROUP_SPANS:
        group_cell[gi] = (gname, gspan)
        for k in range(1, gspan): group_cell[gi + k] = None
        gi += gspan
    group_cell[gi] = ("", 1)

    hdr = "<tr>"
    hdr += '<th class="th-grp">정산그룹</th>'
    hdr += '<th class="th-item">정산항목</th>'
    for dc in date_cols:
        hdr += f'<th class="th-date">{dc}</th>'
    hdr += "</tr>"

    body = ""
    for i, rtype in enumerate(row_types):
        row_cls = {"data":"row-data","subtotal":"row-sub","total":"row-total"}.get(rtype,"row-data")
        body += f'<tr class="{row_cls}">'
        gc = group_cell.get(i)
        if gc is not None:
            gname, gspan = gc
            body += f'<td class="td-group" rowspan="{gspan}">{gname}</td>'
        item = df.at[i, "정산항목"]
        body += f'<td class="td-item">{item}</td>'
        for dc in date_cols:
            raw_val = df.at[i, dc]
            try:
                fval = float(raw_val)
                is_nan = np.isnan(fval)
            except:
                fval, is_nan = 0.0, True
            disp = "-" if is_nan else (fmt_func(fval) if fmt_func else f"{fval:,.0f}")
            style_parts = []
            if not is_nan and gradient and rtype == "data":
                bg = _gradient_bg(fval, abs_max, diff_mode)
                if bg: style_parts.append(bg)
                if diff_mode:
                    tc = _diff_text_color(fval)
                    if tc: style_parts.append(tc)
            style_attr = f' style="{" ".join(style_parts)}"' if style_parts else ""
            body += f"<td{style_attr}>{disp}</td>"
        body += "</tr>"

    return f"""{_TABLE_CSS}
<div class="pivot-wrap">
  <table class="pivot-tbl">
    <thead>{hdr}</thead>
    <tbody>{body}</tbody>
  </table>
</div>
"""

# ──────────────────────────────────────────────
# 기타 헬퍼
# ──────────────────────────────────────────────
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
    st.markdown("---")
    st.markdown("#### 🔄 단위 변환")
    use_m3 = st.toggle("천m³ 단위로 변환", value=False)
    if use_m3:
        calorific = st.number_input(
            "열량 (MJ/m³)", min_value=1.0, max_value=100.0,
            value=42.563, step=0.001, format="%.3f",
            help="GJ → 천m³ 변환: GJ ÷ 열량(MJ/m³) × 1,000")
        st.caption(f"GJ ÷ {calorific:.3f} × 1,000 = 천m³")
    else:
        calorific = 42.563

# ──────────────────────────────────────────────
# 단위 변환 헬퍼
# ──────────────────────────────────────────────
def gj_to_unit(val):
    if use_m3: return val / calorific * 1_000
    return val

def unit_label():
    return "천m³" if use_m3 else "GJ"

def fmt_unit(val, decimals=0, sign=False):
    import math
    if math.isnan(val): return "-"
    v = gj_to_unit(val)
    fmt = f"{{:+,.{decimals}f}}" if sign else f"{{:,.{decimals}f}}"
    return fmt.format(v)

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

# 천연가스 공급량(행4) Series 생성 — 신규방식 보정용
_natgas_ts = total_supply_df.copy()
_natgas_ts["연월"] = pd.to_datetime(_natgas_ts["연월"])
_natgas_series_ts = _natgas_ts.set_index("연월")["총공급량_GJ"]

new_result = build_new_result(supply_df, ratio_df, y_start, y_end, natgas_series=_natgas_series_ts)
old_result = old_df[(old_df["연월"].dt.year >= y_start) &
                    (old_df["연월"].dt.year <= y_end)].copy()
if not old_result.empty:
    old_result["연도"] = old_result["연월"].dt.year

total_filtered = total_supply_df[
    (pd.to_datetime(total_supply_df["연월"]).dt.year >= y_start) &
    (pd.to_datetime(total_supply_df["연월"]).dt.year <= y_end)].copy()

if new_result.empty:
    st.warning("선택 기간에 신규방식 데이터가 없습니다."); st.stop()

# ── 천연가스 공급량(행4, BIO 제외) → 2025년 Series
# total_supply_df가 이미 행4(천연가스) 기준으로 통일됨
_ng_df = total_supply_df.copy()
_ng_df["연월_str"] = pd.to_datetime(_ng_df["연월"]).dt.strftime("%Y-%m")
_ng_series = _ng_df.set_index("연월_str")["총공급량_GJ"]

# 2025년 천연가스 공급량 (BIO 제외 총량)
_ss_natgas_2025 = _ng_series.reindex(_KOGAS_MONTHS, fill_value=0)

# KOGAS_GJ = 판매량 구성비(비율) × 천연가스 공급량(BIO 제외)
KOGAS_GJ = _KOGAS_RATIO.multiply(_ss_natgas_2025, axis=1)

# 전체 합계 카드: KOGAS 총량 = 천연가스 공급량(BIO 제외)
_KOGAS_MONTHLY_TOTAL_GJ = _ss_natgas_2025

# 신규방식 총량도 천연가스 공급량(행4) 사용 — 2025년 비교용
_SS_NEW_TOTAL_2025 = _ss_natgas_2025

common_products = [p for p in OLD_COL_MAP.keys() if p in new_result["상품"].unique()]

# ══════════════════════════════════════════════
# TAB
# ══════════════════════════════════════════════
tab0, tab1, tab2, tab3 = st.tabs([
    "📊 전체 비교 (매트릭스)",
    "🔍 이전방식 vs 신규방식 상세 비교",
    "📋 구성비 및 raw 데이터 확인",
    "🏛️ 비율적용 물량 vs KOGAS제출 물량",
])

# ══════════════════════════════════════════════
# TAB 0 : 전체 비교 매트릭스
# ══════════════════════════════════════════════
with tab0:
    old_pivot, old_rtypes = build_pivot_flat(old_result, "공급량_GJ")
    new_pivot, new_rtypes = build_pivot_flat(new_result, "공급량_GJ")

    date_cols_old = [c for c in old_pivot.columns if c not in ("정산그룹","정산항목")]
    date_cols_new = [c for c in new_pivot.columns if c not in ("정산그룹","정산항목")]
    common_date_cols = sorted(set(date_cols_old) & set(date_cols_new))

    diff_num = (new_pivot[common_date_cols].values.astype(float) -
                old_pivot[common_date_cols].values.astype(float))
    diff_pivot = old_pivot[["정산그룹","정산항목"]].copy()
    for j, col in enumerate(common_date_cols):
        diff_pivot[col] = diff_num[:, j]

    old_num = old_pivot[common_date_cols].values.astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        pct_num = np.where(old_num != 0, diff_num / old_num * 100, np.nan)
    pct_pivot = old_pivot[["정산그룹","정산항목"]].copy()
    for j, col in enumerate(common_date_cols):
        pct_pivot[col] = pct_num[:, j]

    _ul = unit_label()

    st.markdown(f'<div class="sub">📋 이전방식 — 상품별 월별 공급량 ({_ul})</div>', unsafe_allow_html=True)
    st.html(build_html_pivot(old_pivot, old_rtypes, fmt_func=lambda v: fmt_unit(v, decimals=0), diff_mode=False, gradient=True))

    st.markdown(f'<div class="sub">📋 신규방식 — 상품별 월별 공급량 ({_ul})</div>', unsafe_allow_html=True)
    st.html(build_html_pivot(new_pivot, new_rtypes, fmt_func=lambda v: fmt_unit(v, decimals=0), diff_mode=False, gradient=True))

    st.markdown(f'<div class="sub">📋 차이 (신규 − 이전, {_ul}) — 클수록 진한 색상</div>', unsafe_allow_html=True)
    st.html(build_html_pivot(diff_pivot, new_rtypes, fmt_func=lambda v: fmt_unit(v, decimals=0, sign=True), diff_mode=True, gradient=True))

    st.markdown('<div class="sub">📋 차이율 (%, 신규/이전 기준) — 클수록 진한 색상</div>', unsafe_allow_html=True)
    def fmt_pct(v):
        if np.isnan(v): return "-"
        return f"{v:+.2f}%"
    st.html(build_html_pivot(pct_pivot, new_rtypes, fmt_func=fmt_pct, diff_mode=True, gradient=True))

    buf_matrix = BytesIO()
    with pd.ExcelWriter(buf_matrix, engine="openpyxl") as w:
        old_pivot.to_excel(w, sheet_name="이전방식", index=False)
        new_pivot.to_excel(w, sheet_name="신규방식", index=False)
        diff_pivot.to_excel(w, sheet_name="차이_GJ", index=False)
        pct_pivot.to_excel(w, sheet_name="차이율_%", index=False)
    st.download_button("⬇️ 전체 매트릭스 엑셀 다운로드", data=buf_matrix.getvalue(),
        file_name=f"전체매트릭스_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_matrix")

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
        index=common_products.index("개별난방용") if "개별난방용" in common_products else 0)

    old_prod = old_result[old_result["상품"] == selected_product].set_index("연월")["공급량_GJ"]
    new_prod = new_result[new_result["상품"] == selected_product].set_index("연월")["공급량_GJ"]
    old_yr_p = old_prod.groupby(old_prod.index.year).sum()
    new_yr_p = new_prod.groupby(new_prod.index.year).sum()
    years_p  = sorted(set(old_yr_p.index) | set(new_yr_p.index))
    old_vals = [gj_to_unit(old_yr_p.get(y, 0)) for y in years_p]
    new_vals = [gj_to_unit(new_yr_p.get(y, 0)) for y in years_p]
    old_vals_gj = [old_yr_p.get(y, 0) for y in years_p]
    new_vals_gj = [new_yr_p.get(y, 0) for y in years_p]
    pct_list = [(n-o)/o*100 if o else 0.0 for o,n in zip(old_vals_gj, new_vals_gj)]
    _ul = unit_label()

    st.markdown(f'<div class="sub">📊 연도별 비교 — {selected_product} ({_ul})</div>', unsafe_allow_html=True)
    max_val = max(max(old_vals, default=1), max(new_vals, default=1))
    fig_cmp_yr = go.Figure()
    fig_cmp_yr.add_trace(go.Bar(x=[str(y) for y in years_p], y=old_vals, name="이전방식", marker_color="#2c5f8a",
        hovertemplate=f"이전방식<br>%{{x}}년<br>%{{y:,.1f}} {_ul}<extra></extra>"))
    fig_cmp_yr.add_trace(go.Bar(x=[str(y) for y in years_p], y=new_vals, name="신규방식", marker_color="#e8501a",
        hovertemplate=f"신규방식<br>%{{x}}년<br>%{{y:,.1f}} {_ul}<extra></extra>"))
    annotations = []
    for y, pct, nv in zip(years_p, pct_list, new_vals):
        sign  = "+" if pct >= 0 else ""
        color = "#e8501a" if pct >= 0 else "#2c5f8a"
        annotations.append(dict(x=str(y), y=nv + max_val * 0.02, text=f"<b>{sign}{pct:.1f}%</b>",
            showarrow=False, font=dict(size=13, color=color), xanchor="center", yanchor="bottom"))
    fig_cmp_yr.update_layout(barmode="group", height=460, xaxis_title="연도", yaxis_title=f"공급량 ({_ul})",
        yaxis=dict(range=[0, max_val*1.15], showgrid=True, gridcolor="#ebebeb"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="white", paper_bgcolor="white", margin=dict(l=70,r=20,t=70,b=40), annotations=annotations)
    st.plotly_chart(fig_cmp_yr, use_container_width=True)

    st.markdown(f'<div class="sub">📈 월별 추이 비교 — {selected_product} ({_ul})</div>', unsafe_allow_html=True)
    st.caption("💡 마우스 휠: 확대/축소 | 드래그: 이동")
    old_prod_disp = old_prod.apply(gj_to_unit)
    new_prod_disp = new_prod.apply(gj_to_unit)
    fig_cmp_mo = go.Figure()
    fig_cmp_mo.add_trace(go.Scatter(x=old_prod_disp.index, y=old_prod_disp.values, name="이전방식",
        mode="lines", line=dict(color="#2c5f8a", width=2),
        hovertemplate=f"이전방식<br>%{{x|%Y-%m}}<br>%{{y:,.1f}} {_ul}<extra></extra>"))
    fig_cmp_mo.add_trace(go.Scatter(x=new_prod_disp.index, y=new_prod_disp.values, name="신규방식",
        mode="lines", line=dict(color="#e8501a", width=2, dash="dot"),
        hovertemplate=f"신규방식<br>%{{x|%Y-%m}}<br>%{{y:,.1f}} {_ul}<extra></extra>"))
    fig_cmp_mo.update_layout(height=400, xaxis_title="연월", yaxis_title=f"공급량 ({_ul})",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="white", paper_bgcolor="white", margin=dict(l=70,r=20,t=50,b=40), dragmode="pan")
    fig_cmp_mo.update_yaxes(showgrid=True, gridcolor="#ebebeb", fixedrange=False)
    fig_cmp_mo.update_xaxes(fixedrange=False)
    st.plotly_chart(fig_cmp_mo, use_container_width=True,
        config={"scrollZoom":True,"displayModeBar":True,
                "modeBarButtonsToAdd":["pan2d"],"modeBarButtonsToRemove":["lasso2d","select2d"]})

    st.markdown("---")
    st.markdown(f'<div class="sub">📊 특정 연도 월별 비교 — {selected_product} ({_ul})</div>', unsafe_allow_html=True)
    avail_years = sorted(set(old_prod.index.year) & set(new_prod.index.year))
    if not avail_years:
        st.info("공통 연도 데이터가 없습니다.")
    else:
        sel_year = st.selectbox("연도 선택", options=avail_years, index=len(avail_years)-1, key="sel_year_monthly")
        old_yr_total_v    = old_yr_p.get(sel_year, 0)
        new_yr_total_v    = new_yr_p.get(sel_year, 0)
        old_yr_total_disp = gj_to_unit(old_yr_total_v)
        new_yr_total_disp = gj_to_unit(new_yr_total_v)
        yr_diff    = new_yr_total_v - old_yr_total_v
        yr_diff_d  = gj_to_unit(yr_diff)
        yr_pct     = yr_diff / old_yr_total_v * 100 if old_yr_total_v else 0
        sign_yr    = "+" if yr_pct >= 0 else ""
        pct_col    = "#e8501a" if yr_pct >= 0 else "#2c5f8a"
        st.markdown(f"""
        <div style="display:flex; gap:1rem; margin-bottom:1rem;">
            <div style="flex:1; background:#f4f8fc; border-left:4px solid #2c5f8a; padding:0.8rem 1.2rem; border-radius:4px;">
                <div style="font-size:0.8rem; color:#666;">이전방식 ({sel_year}년 합계)</div>
                <div style="font-size:1.3rem; font-weight:700; color:#2c5f8a;">{old_yr_total_disp:,.1f} {_ul}</div>
            </div>
            <div style="flex:1; background:#fff4f0; border-left:4px solid #e8501a; padding:0.8rem 1.2rem; border-radius:4px;">
                <div style="font-size:0.8rem; color:#666;">신규방식 ({sel_year}년 합계)</div>
                <div style="font-size:1.3rem; font-weight:700; color:#e8501a;">{new_yr_total_disp:,.1f} {_ul}</div>
            </div>
            <div style="flex:1; background:#f9f9f9; border-left:4px solid {pct_col}; padding:0.8rem 1.2rem; border-radius:4px;">
                <div style="font-size:0.8rem; color:#666;">{sel_year}년 전체 차이</div>
                <div style="font-size:1.5rem; font-weight:800; color:{pct_col};">{sign_yr}{yr_pct:.2f}%</div>
                <div style="font-size:0.8rem; color:#888;">{sign_yr}{yr_diff_d:,.1f} {_ul}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        MONTH_KR = ["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"]
        old_mo = old_prod[old_prod.index.year == sel_year].copy()
        new_mo = new_prod[new_prod.index.year == sel_year].copy()
        old_mo.index = old_mo.index.month
        new_mo.index = new_mo.index.month
        old_mo_gj   = [old_mo.get(m, 0) for m in range(1, 13)]
        new_mo_gj   = [new_mo.get(m, 0) for m in range(1, 13)]
        old_mo_vals = [gj_to_unit(v) for v in old_mo_gj]
        new_mo_vals = [gj_to_unit(v) for v in new_mo_gj]
        mo_pct = [(n-o)/o*100 if o else 0.0 for o,n in zip(old_mo_gj, new_mo_gj)]
        max_mo = max(max(old_mo_vals, default=1), max(new_mo_vals, default=1))

        fig_mo_yr = go.Figure()
        fig_mo_yr.add_trace(go.Bar(x=MONTH_KR, y=old_mo_vals, name="이전방식", marker_color="#2c5f8a",
            hovertemplate=f"이전방식<br>%{{x}}<br>%{{y:,.1f}} {_ul}<extra></extra>"))
        fig_mo_yr.add_trace(go.Bar(x=MONTH_KR, y=new_mo_vals, name="신규방식", marker_color="#e8501a",
            hovertemplate=f"신규방식<br>%{{x}}<br>%{{y:,.1f}} {_ul}<extra></extra>"))
        mo_ann = []
        for m, pct, nv in zip(MONTH_KR, mo_pct, new_mo_vals):
            sign  = "+" if pct >= 0 else ""
            color = "#e8501a" if pct >= 0 else "#2c5f8a"
            mo_ann.append(dict(x=m, y=nv + max_mo * 0.02, text=f"<b>{sign}{pct:.1f}%</b>",
                showarrow=False, font=dict(size=13, color=color), xanchor="center", yanchor="bottom"))
        fig_mo_yr.update_layout(barmode="group", height=420,
            title=dict(text=f"{sel_year}년 월별 비교 — {selected_product}", font=dict(size=15)),
            xaxis_title="월", yaxis_title=f"공급량 ({_ul})",
            yaxis=dict(range=[0, max_mo*1.18], showgrid=True, gridcolor="#ebebeb"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            plot_bgcolor="white", paper_bgcolor="white", margin=dict(l=70,r=20,t=80,b=40), annotations=mo_ann)
        st.plotly_chart(fig_mo_yr, use_container_width=True)

        col_name  = f"이전방식_{_ul}"
        col_name2 = f"신규방식_{_ul}"
        diff_vals = [n-o for o,n in zip(old_mo_vals, new_mo_vals)]
        tbl_mo_yr = pd.DataFrame({col_name: old_mo_vals, col_name2: new_mo_vals,
            f"차이_{_ul}": diff_vals, "차이(%)": mo_pct}, index=MONTH_KR)
        tbl_mo_yr.index.name = "월"
        subtotal_mo = pd.DataFrame([{col_name: sum(old_mo_vals), col_name2: sum(new_mo_vals),
            f"차이_{_ul}": sum(diff_vals),
            "차이(%)": (sum(new_mo_gj)-sum(old_mo_gj))/sum(old_mo_gj)*100 if sum(old_mo_gj) else 0.0,
        }], index=[SUBTOTAL_LABEL])
        subtotal_mo.index.name = "월"
        tbl_mo_full = pd.concat([tbl_mo_yr, subtotal_mo])
        fmt_dict = {col_name:"{:,.1f}", col_name2:"{:,.1f}", f"차이_{_ul}":"{:,.1f}", "차이(%)":"{:+.2f}%"}
        st.dataframe(tbl_mo_full.style.format(fmt_dict).apply(style_subtotal_any, axis=None)
            .map(color_pct, subset=["차이(%)"]), use_container_width=True)

    st.markdown(f'<div class="sub">📋 연도별 비교 테이블 — {selected_product}</div>', unsafe_allow_html=True)
    col_o = f"이전방식_{_ul}"
    col_n = f"신규방식_{_ul}"
    tbl_cmp = pd.DataFrame({col_o: old_yr_p.apply(gj_to_unit), col_n: new_yr_p.apply(gj_to_unit)}).fillna(0).round(1)
    tbl_cmp[f"차이_{_ul}"] = (tbl_cmp[col_n] - tbl_cmp[col_o]).round(1)
    tbl_cmp["차이(%)"] = ((new_yr_p - old_yr_p).fillna(0) / old_yr_p.replace(0, float("nan")) * 100).round(2)
    tbl_cmp.index.name = "연도"
    st.dataframe(tbl_cmp.style.format({col_o:"{:,.1f}", col_n:"{:,.1f}",
        f"차이_{_ul}":"{:,.1f}", "차이(%)":"{:+.2f}%"}).map(color_pct, subset=["차이(%)"]),
        use_container_width=True)
    buf_cmp = BytesIO()
    with pd.ExcelWriter(buf_cmp, engine="openpyxl") as w:
        tbl_cmp.to_excel(w, sheet_name=f"{selected_product}_비교")
    st.download_button(f"⬇️ {selected_product} 비교 엑셀 다운로드", data=buf_cmp.getvalue(),
        file_name=f"비교_{selected_product}_{y_start}_{y_end}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_cmp")

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
        disp_ratio = disp_ratio[[c for c in disp_ratio.columns if pd.notna(c) and y_start <= c.year <= y_end]]
        disp_ratio.columns = [c.strftime("%Y-%m") for c in disp_ratio.columns]
        subtotal_r = pd.DataFrame([disp_ratio.sum(numeric_only=True)], index=[SUBTOTAL_LABEL])
        subtotal_r.index.name = disp_ratio.index.name
        disp_ratio_full = pd.concat([disp_ratio, subtotal_r])
        st.dataframe(disp_ratio_full.style.format("{:.4f}").apply(style_subtotal_any, axis=None),
            use_container_width=True, height=460)
        buf_r = BytesIO()
        with pd.ExcelWriter(buf_r, engine="openpyxl") as w:
            disp_ratio_full.to_excel(w, sheet_name="구성비")
        st.download_button("⬇️ 구성비 엑셀 다운로드", data=buf_r.getvalue(),
            file_name=f"구성비_{y_start}_{y_end}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_ratio")

    with sub2:
        st.markdown('<div class="sub">상품별 월별 공급량 (GJ) — 구글시트 원본</div>', unsafe_allow_html=True)
        disp_sup = supply_df.copy()
        disp_sup = disp_sup[[c for c in disp_sup.columns if pd.notna(c) and y_start <= c.year <= y_end]]
        disp_sup.columns = [c.strftime("%Y-%m") for c in disp_sup.columns]
        subtotal_s = pd.DataFrame([disp_sup.sum(numeric_only=True)], index=[SUBTOTAL_LABEL])
        subtotal_s.index.name = disp_sup.index.name
        disp_sup_full = pd.concat([disp_sup, subtotal_s])
        st.dataframe(disp_sup_full.style.format("{:,.1f}").apply(style_subtotal_any, axis=None),
            use_container_width=True, height=460)
        buf_s = BytesIO()
        with pd.ExcelWriter(buf_s, engine="openpyxl") as w:
            disp_sup_full.to_excel(w, sheet_name="상품별공급량")
        st.download_button("⬇️ 상품별 공급량 엑셀 다운로드", data=buf_s.getvalue(),
            file_name=f"상품별공급량_{y_start}_{y_end}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_sup")

    with sub3:
        st.markdown('<div class="sub">월별 천연가스 공급량 (GJ) — 구글시트 행4 (BIO 제외)</div>', unsafe_allow_html=True)
        st.caption("구글시트 4행의 천연가스 공급량(GJ) — BIO가스 제외, 전체 코드 총량 기준")
        disp_total = total_filtered.copy()
        disp_total["연월"] = pd.to_datetime(disp_total["연월"]).dt.strftime("%Y-%m")
        disp_total["총공급량_GJ"] = disp_total["총공급량_GJ"].round(1)
        st.dataframe(disp_total.style.format({"총공급량_GJ": "{:,.1f}"}), use_container_width=True, height=400)
        buf_t = BytesIO()
        with pd.ExcelWriter(buf_t, engine="openpyxl") as w:
            disp_total.to_excel(w, sheet_name="월별총공급량", index=False)
        st.download_button("⬇️ 월별 총 공급량 엑셀 다운로드", data=buf_t.getvalue(),
            file_name=f"월별총공급량_{y_start}_{y_end}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_total")

# ══════════════════════════════════════════════
# TAB 3 : 비율적용 물량 vs KOGAS 제출 물량
# ══════════════════════════════════════════════
with tab3:
    st.markdown("""
    <span class="badge-old">이전방식</span> 수송용 CNG만 적용 &nbsp;|&nbsp; BIO값을 제외한 총량 기준<br>
    <span class="badge-new">신규방식</span> 가스공사 비용 정산 비율 반영 &nbsp;|&nbsp; BIO값을 제외한 총량 기준<br>
    <span class="badge-kogas">KOGAS 제출</span> 판매량 기준 구성비 × BIO값을 제외한 총량
    <br><span style="color:#888; font-size:0.85rem; line-height:2.5;">
    ※ 세 방식 모두 <b>BIO가스를 제외한 천연가스 공급량(스프레드시트 행4)</b>을 비교 기준 총량으로 사용합니다.
    &nbsp;|&nbsp; KOGAS 제출 물량은 2025년 1~12월 데이터만 제공됩니다.</span>
    <br>
    """, unsafe_allow_html=True)

    # ── 비교 방식 선택 (토글)
    compare_mode = st.radio(
        "비교 방식 선택",
        options=["이전방식 vs KOGAS 제출 물량", "신규방식 vs KOGAS 제출 물량"],
        index=0,
        horizontal=True,
        key="kogas_compare_mode",
    )
    use_old_mode = (compare_mode == "이전방식 vs KOGAS 제출 물량")

    _ul = unit_label()
    KOGAS_2025_MONTHS = _KOGAS_MONTHS

    # ── 비교 방식에 따른 레이블/색상 설정
    if use_old_mode:
        _badge_all  = "이전방식"
        _color_all  = "#1a3c6e"
        ratio_src_all = old_result[old_result["연월"].dt.year == 2025].copy()
    else:
        _badge_all  = "신규방식"
        _color_all  = "#1a3c6e"
        ratio_src_all = new_result[new_result["연월"].dt.year == 2025].copy()

    # ── 전체 합계 비교 (상품 선택 전, 상단에 표시)
    st.markdown('<div class="sub">📊 전체 합계량 비교 — 2025년 (모든 상품 합산)</div>', unsafe_allow_html=True)

    # 월별 전체 합계
    ratio_total_mo_gj = [
        ratio_src_all[ratio_src_all["연월"].dt.strftime("%Y-%m") == m]["공급량_GJ"].sum()
        for m in KOGAS_2025_MONTHS
    ]
    kogas_total_mo_gj = [float(_KOGAS_MONTHLY_TOTAL_GJ.get(m, 0)) for m in KOGAS_2025_MONTHS]

    # 신규방식: 천연가스 공급량(행4, BIO 제외) 합계를 비교 기준으로 사용
    if not use_old_mode:
        ratio_total_mo_gj = [float(_SS_NEW_TOTAL_2025.get(m, 0)) for m in KOGAS_2025_MONTHS]
    ratio_total_ann = sum(ratio_total_mo_gj)
    kogas_total_ann = sum(kogas_total_mo_gj)
    total_diff_gj   = ratio_total_ann - kogas_total_ann
    total_pct       = total_diff_gj / kogas_total_ann * 100 if kogas_total_ann else 0
    sign_t          = "+" if total_pct >= 0 else ""
    card_ct         = "#e8501a" if total_pct >= 0 else "#2c5f8a"

    # 연간 요약 카드 (전체 합계)
    ca, cb, cc = st.columns(3)
    ca.markdown(f"""<div style="background:#f4f8fc; border-left:4px solid {_color_all};
        padding:0.8rem 1.2rem; border-radius:4px;">
        <div style="font-size:0.8rem; color:#666;">{_badge_all} 2025년 전체 합계</div>
        <div style="font-size:1.3rem; font-weight:700; color:{_color_all};">{gj_to_unit(ratio_total_ann):,.1f} {_ul}</div>
    </div>""", unsafe_allow_html=True)
    cb.markdown(f"""<div style="background:#e8f7fa; border-left:4px solid #0097b2;
        padding:0.8rem 1.2rem; border-radius:4px;">
        <div style="font-size:0.8rem; color:#666;">KOGAS 제출 2025년 전체 합계</div>
        <div style="font-size:1.3rem; font-weight:700; color:#0097b2;">{gj_to_unit(kogas_total_ann):,.1f} {_ul}</div>
    </div>""", unsafe_allow_html=True)
    cc.markdown(f"""<div style="background:#f9f9f9; border-left:4px solid {card_ct};
        padding:0.8rem 1.2rem; border-radius:4px;">
        <div style="font-size:0.8rem; color:#666;">연간 차이 ({_badge_all} − KOGAS)</div>
        <div style="font-size:1.5rem; font-weight:800; color:{card_ct};">{sign_t}{total_pct:.2f}%</div>
        <div style="font-size:0.8rem; color:#888;">{sign_t}{gj_to_unit(total_diff_gj):,.1f} {_ul}</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── 상품별 상세 비교
    st.markdown('<div class="sub">🔍 상품별 상세 비교</div>', unsafe_allow_html=True)

    # ── 상품 선택
    k_selected = st.selectbox(
        "비교할 상품 선택", options=common_products,
        index=common_products.index("개별난방용") if "개별난방용" in common_products else 0,
        key="kogas_product_sel",
    )

    # ── 비교 대상 데이터 준비 (2025년만) — _ul, KOGAS_2025_MONTHS 는 위에서 선언됨
    # KOGAS 상품별 GJ (2025년)
    if k_selected in KOGAS_GJ.index:
        kogas_prod_gj = KOGAS_GJ.loc[k_selected]  # Series, index=YYYY-MM
    else:
        kogas_prod_gj = pd.Series(0.0, index=KOGAS_2025_MONTHS)

    # 비율적용 물량 (이전 or 신규) — badge_label, bar_color 설정
    badge_label = _badge_all
    bar_color   = "#1a3c6e"   # 이전/신규 동일 네이비
    if use_old_mode:
        ratio_src = old_result[old_result["상품"] == k_selected].copy()
    else:
        ratio_src = new_result[new_result["상품"] == k_selected].copy()

    ratio_src_2025 = ratio_src[ratio_src["연월"].dt.year == 2025].copy()
    ratio_src_2025["연월_str"] = ratio_src_2025["연월"].dt.strftime("%Y-%m")
    ratio_monthly = ratio_src_2025.set_index("연월_str")["공급량_GJ"].reindex(KOGAS_2025_MONTHS, fill_value=0)

    MONTH_KR = ["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"]

    ratio_vals_gj  = [ratio_monthly.get(m, 0) for m in KOGAS_2025_MONTHS]
    kogas_vals_gj  = [float(kogas_prod_gj.get(m, 0)) for m in KOGAS_2025_MONTHS]
    ratio_vals     = [gj_to_unit(v) for v in ratio_vals_gj]
    kogas_vals     = [gj_to_unit(v) for v in kogas_vals_gj]
    diff_vals_gj   = [r - k for r, k in zip(ratio_vals_gj, kogas_vals_gj)]
    diff_vals      = [gj_to_unit(v) for v in diff_vals_gj]
    mo_pct_k       = [(r - k) / k * 100 if k else 0.0 for r, k in zip(ratio_vals_gj, kogas_vals_gj)]

    # ── 연간 요약 카드
    ratio_annual   = sum(ratio_vals_gj)
    kogas_annual   = sum(kogas_vals_gj)
    annual_diff_gj = ratio_annual - kogas_annual
    annual_pct     = annual_diff_gj / kogas_annual * 100 if kogas_annual else 0
    sign_a         = "+" if annual_pct >= 0 else ""
    card_c         = "#e8501a" if annual_pct >= 0 else "#2c5f8a"

    c1, c2, c3 = st.columns(3)
    c1.markdown(f"""<div style="background:#f4f8fc; border-left:4px solid {bar_color};
        padding:0.8rem 1.2rem; border-radius:4px;">
        <div style="font-size:0.8rem; color:#666;">{badge_label} 2025년 합계</div>
        <div style="font-size:1.3rem; font-weight:700; color:{bar_color};">{gj_to_unit(ratio_annual):,.1f} {_ul}</div>
    </div>""", unsafe_allow_html=True)
    c2.markdown(f"""<div style="background:#e8f7fa; border-left:4px solid #0097b2;
        padding:0.8rem 1.2rem; border-radius:4px;">
        <div style="font-size:0.8rem; color:#666;">KOGAS 제출 2025년 합계</div>
        <div style="font-size:1.3rem; font-weight:700; color:#0097b2;">{gj_to_unit(kogas_annual):,.1f} {_ul}</div>
    </div>""", unsafe_allow_html=True)
    c3.markdown(f"""<div style="background:#f9f9f9; border-left:4px solid {card_c};
        padding:0.8rem 1.2rem; border-radius:4px;">
        <div style="font-size:0.8rem; color:#666;">연간 차이 ({badge_label} − KOGAS)</div>
        <div style="font-size:1.5rem; font-weight:800; color:{card_c};">{sign_a}{annual_pct:.2f}%</div>
        <div style="font-size:0.8rem; color:#888;">{sign_a}{gj_to_unit(annual_diff_gj):,.1f} {_ul}</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 월별 막대 비교 차트
    st.markdown(f'<div class="sub">📊 월별 비교 — {k_selected} ({_ul}) · 2025년</div>', unsafe_allow_html=True)
    max_k = max(max(ratio_vals, default=1), max(kogas_vals, default=1))
    fig_k = go.Figure()
    fig_k.add_trace(go.Bar(x=MONTH_KR, y=ratio_vals, name=badge_label, marker_color=bar_color,
        hovertemplate=f"{badge_label}<br>%{{x}}<br>%{{y:,.1f}} {_ul}<extra></extra>"))
    fig_k.add_trace(go.Bar(x=MONTH_KR, y=kogas_vals, name="KOGAS 제출", marker_color="#0097b2",
        hovertemplate=f"KOGAS 제출<br>%{{x}}<br>%{{y:,.1f}} {_ul}<extra></extra>"))
    k_ann = []
    for m, pct, rv in zip(MONTH_KR, mo_pct_k, ratio_vals):
        sign  = "+" if pct >= 0 else ""
        color = "#e8501a" if pct >= 0 else "#2c5f8a"
        k_ann.append(dict(x=m, y=rv + max_k * 0.02, text=f"<b>{sign}{pct:.1f}%</b>",
            showarrow=False, font=dict(size=12, color=color), xanchor="center", yanchor="bottom"))
    fig_k.update_layout(barmode="group", height=440,
        xaxis_title="월", yaxis_title=f"공급량 ({_ul})",
        yaxis=dict(range=[0, max_k*1.18], showgrid=True, gridcolor="#ebebeb"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=70,r=20,t=60,b=40), annotations=k_ann)
    st.plotly_chart(fig_k, use_container_width=True)

    # ── 월별 추이 라인 차트
    st.markdown(f'<div class="sub">📈 월별 추이 비교 — {k_selected} ({_ul})</div>', unsafe_allow_html=True)
    st.caption("💡 마우스 휠: 확대/축소 | 드래그: 이동")
    fig_k_line = go.Figure()
    fig_k_line.add_trace(go.Scatter(x=MONTH_KR, y=ratio_vals, name=badge_label,
        mode="lines+markers", line=dict(color=bar_color, width=2),
        hovertemplate=f"{badge_label}<br>%{{x}}<br>%{{y:,.1f}} {_ul}<extra></extra>"))
    fig_k_line.add_trace(go.Scatter(x=MONTH_KR, y=kogas_vals, name="KOGAS 제출",
        mode="lines+markers", line=dict(color="#0097b2", width=2, dash="dot"),
        hovertemplate=f"KOGAS 제출<br>%{{x}}<br>%{{y:,.1f}} {_ul}<extra></extra>"))
    fig_k_line.update_layout(height=380, xaxis_title="월", yaxis_title=f"공급량 ({_ul})",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=70,r=20,t=40,b=40), dragmode="pan")
    fig_k_line.update_yaxes(showgrid=True, gridcolor="#ebebeb", fixedrange=False)
    fig_k_line.update_xaxes(fixedrange=False)
    st.plotly_chart(fig_k_line, use_container_width=True,
        config={"scrollZoom":True,"displayModeBar":True,
                "modeBarButtonsToAdd":["pan2d"],"modeBarButtonsToRemove":["lasso2d","select2d"]})

    st.markdown("---")

    # ── 월별 비교 테이블 (소계 포함)
    st.markdown(f'<div class="sub">📋 월별 비교 테이블 — {k_selected} (2025년)</div>', unsafe_allow_html=True)
    col_r = f"{badge_label}_{_ul}"
    col_kg = f"KOGAS제출_{_ul}"
    tbl_k = pd.DataFrame({
        col_r:           ratio_vals,
        col_kg:          kogas_vals,
        f"차이_{_ul}":   diff_vals,
        "차이(%)":       mo_pct_k,
    }, index=MONTH_KR)
    tbl_k.index.name = "월"
    sub_k = pd.DataFrame([{
        col_r:          sum(ratio_vals),
        col_kg:         sum(kogas_vals),
        f"차이_{_ul}":  sum(diff_vals),
        "차이(%)":      (sum(ratio_vals_gj) - sum(kogas_vals_gj)) / sum(kogas_vals_gj) * 100
                        if sum(kogas_vals_gj) else 0.0,
    }], index=[SUBTOTAL_LABEL])
    sub_k.index.name = "월"
    tbl_k_full = pd.concat([tbl_k, sub_k])
    fmt_k = {col_r:"{:,.1f}", col_kg:"{:,.1f}", f"차이_{_ul}":"{:,.1f}", "차이(%)":"{:+.2f}%"}
    st.dataframe(tbl_k_full.style.format(fmt_k).apply(style_subtotal_any, axis=None)
        .map(color_pct, subset=["차이(%)"]), use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 전체 상품 연간 비교 테이블 (정산그룹 병합 구조 — HTML rowspan)
    st.markdown('<div class="sub">📋 전체 상품 연간 비교 — 2025년 합계</div>', unsafe_allow_html=True)

    # 상품별 데이터 수집
    product_data = {}
    for p in PRODUCT_LIST:
        if use_old_mode:
            p_src = old_result[old_result["상품"] == p]
        else:
            p_src = new_result[new_result["상품"] == p]
        p_2025 = p_src[p_src["연월"].dt.year == 2025]["공급량_GJ"].sum()
        k_2025 = float(KOGAS_GJ.loc[p, _KOGAS_MONTHS].sum()) if p in KOGAS_GJ.index else 0.0
        diff_v = p_2025 - k_2025
        pct_v  = diff_v / k_2025 * 100 if k_2025 else 0.0
        product_data[p] = {
            "r_gj": p_2025, "k_gj": k_2025,
            "diff_gj": diff_v, "pct": pct_v,
        }

    # 소계 계산
    def calc_sub(prods):
        sr = sum(product_data[p]["r_gj"] for p in prods if p in product_data)
        sk = sum(product_data[p]["k_gj"] for p in prods if p in product_data)
        sd = sr - sk
        sp = sd / sk * 100 if sk else 0.0
        return sr, sk, sd, sp

    h_r, h_k, h_d, h_p = calc_sub(HOUSING_PRODUCTS)
    o_r, o_k, o_d, o_p = calc_sub(OTHER_PRODUCTS)
    tot_r = h_r + o_r
    tot_k = h_k + o_k
    tot_d = tot_r - tot_k
    tot_p = tot_d / tot_k * 100 if tot_k else 0.0

    # ── HTML 테이블 생성 (rowspan 병합)
    def _pct_color(v):
        return "#c0390b" if v >= 0 else "#1a4f8a"

    def _fmt_num(v):
        return f"{gj_to_unit(v):,.1f}"

    def _fmt_pct(v):
        sign = "+" if v >= 0 else ""
        return f'<span style="color:{_pct_color(v)}; font-weight:600;">{sign}{v:.2f}%</span>'

    tbl_css = """
    <style>
    .ann-tbl { border-collapse:collapse; font-size:0.8rem;
               font-family:'Segoe UI','Noto Sans KR',sans-serif;
               width:100%; white-space:nowrap; }
    .ann-tbl thead th {
        background:#2c5f8a; color:#fff; padding:6px 12px;
        text-align:center; border:1px solid #1a3c5e; font-weight:600; }
    .ann-tbl th.th-grp  { min-width:70px; }
    .ann-tbl th.th-item { min-width:100px; text-align:left; padding-left:12px; }
    .ann-tbl th.th-num  { min-width:130px; }
    .ann-tbl td { padding:5px 12px; border:1px solid #dde3ea; text-align:right; }
    .ann-tbl td.td-grp  {
        text-align:center; font-weight:700; color:#1a3c5e;
        background:#eaf1f8 !important; border-right:2px solid #2c5f8a;
        vertical-align:middle; }
    .ann-tbl td.td-item { text-align:left; padding-left:16px; background:#fff; }
    .ann-tbl tr.tr-data:hover td { background:#f0f6ff !important; }
    .ann-tbl tr.tr-sub  td { background:#ddeaf8 !important; font-weight:700; color:#1a3c5e; }
    .ann-tbl tr.tr-sub  td.td-item { text-align:center; padding-left:0; }
    .ann-tbl tr.tr-total td { background:#c5d8f0 !important; font-weight:700; color:#1a3c5e; }
    .ann-tbl tr.tr-total td.td-item { text-align:center; padding-left:0; }
    </style>
    """

    col_h1 = badge_label + f" ({_ul})"
    col_h2 = f"KOGAS 제출 ({_ul})"
    col_h3 = f"차이 ({_ul})"
    col_h4 = "차이 (%)"

    hdr = f"""<tr>
      <th class="th-grp">정산그룹</th>
      <th class="th-item">정산항목</th>
      <th class="th-num">{col_h1}</th>
      <th class="th-num">{col_h2}</th>
      <th class="th-num">{col_h3}</th>
      <th class="th-num">{col_h4}</th>
    </tr>"""

    def product_rows(prods, grp_name, sub_r, sub_k, sub_d, sub_p):
        rows = ""
        n = len(prods)
        rowspan = n + 1  # 상품 수 + 소계 1행
        for i, p in enumerate(prods):
            d = product_data.get(p, {"r_gj":0,"k_gj":0,"diff_gj":0,"pct":0})
            grp_cell = f'<td class="td-grp" rowspan="{rowspan}">{grp_name}</td>' if i == 0 else ""
            rows += f"""<tr class="tr-data">
              {grp_cell}
              <td class="td-item">{p}</td>
              <td>{_fmt_num(d["r_gj"])}</td>
              <td>{_fmt_num(d["k_gj"])}</td>
              <td>{_fmt_num(d["diff_gj"])}</td>
              <td>{_fmt_pct(d["pct"])}</td>
            </tr>"""
        # 소계 행
        rows += f"""<tr class="tr-sub">
          <td class="td-item">소 계</td>
          <td>{_fmt_num(sub_r)}</td>
          <td>{_fmt_num(sub_k)}</td>
          <td>{_fmt_num(sub_d)}</td>
          <td>{_fmt_pct(sub_p)}</td>
        </tr>"""
        return rows

    body  = product_rows(HOUSING_PRODUCTS, "주택용", h_r, h_k, h_d, h_p)
    body += product_rows(OTHER_PRODUCTS,   "기타",   o_r, o_k, o_d, o_p)
    # 합계 행
    body += f"""<tr class="tr-total">
      <td class="td-grp"></td>
      <td class="td-item">합 계</td>
      <td>{_fmt_num(tot_r)}</td>
      <td>{_fmt_num(tot_k)}</td>
      <td>{_fmt_num(tot_d)}</td>
      <td>{_fmt_pct(tot_p)}</td>
    </tr>"""

    ann_html = f"""{tbl_css}
    <div style="overflow-x:auto; border:1px solid #c8d8e8; border-radius:6px; margin-bottom:1rem;">
      <table class="ann-tbl">
        <thead>{hdr}</thead>
        <tbody>{body}</tbody>
      </table>
    </div>"""

    st.html(ann_html)

    # 엑셀용 DataFrame 별도 생성
    excel_rows = []
    for grp_name, prods in [("주택용", HOUSING_PRODUCTS), ("기타", OTHER_PRODUCTS)]:
        for p in prods:
            d = product_data.get(p, {"r_gj":0,"k_gj":0,"diff_gj":0,"pct":0})
            excel_rows.append({"정산그룹": grp_name, "정산항목": p,
                col_r: gj_to_unit(d["r_gj"]), col_kg: gj_to_unit(d["k_gj"]),
                f"차이_{_ul}": gj_to_unit(d["diff_gj"]), "차이(%)": d["pct"]})
        sr, sk, sd, sp = calc_sub(prods)
        excel_rows.append({"정산그룹": "", "정산항목": "소 계",
            col_r: gj_to_unit(sr), col_kg: gj_to_unit(sk),
            f"차이_{_ul}": gj_to_unit(sd), "차이(%)": sp})
    excel_rows.append({"정산그룹": "", "정산항목": "합 계",
        col_r: gj_to_unit(tot_r), col_kg: gj_to_unit(tot_k),
        f"차이_{_ul}": gj_to_unit(tot_d), "차이(%)": tot_p})
    tbl_all_excel = pd.DataFrame(excel_rows)

    # 엑셀 다운로드
    buf_k = BytesIO()
    with pd.ExcelWriter(buf_k, engine="openpyxl") as w:
        tbl_k_full.to_excel(w, sheet_name=f"{k_selected}_월별비교")
        tbl_all_excel.to_excel(w, sheet_name="전체상품_연간비교", index=False)
    st.download_button(
        f"⬇️ KOGAS 비교 엑셀 다운로드", data=buf_k.getvalue(),
        file_name=f"KOGAS비교_{k_selected}_2025.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_kogas",
    )
