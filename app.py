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
.info-row { display:grid; grid-template-columns:110px 1fr; align-items:center; gap:0 8px; }
.info-row .badge-old, .info-row .badge-new, .info-row .badge-kogas { white-space:nowrap; }
</style>
""", unsafe_allow_html=True)
# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
NEW_GSHEET_ID  = "1gIhArPlLBJ9fwlaqXtZWxiKlSK9hbRuz6HcDw_Yf7Is"
NEW_GSHEET_URL = f"https://docs.google.com/spreadsheets/d/{NEW_GSHEET_ID}/export?format=csv&gid=0"
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
DATA_START_COL  = 3    # 상품별분배 데이터 시작 열 (D열=3, A~C=0~2)
# ── 테이블 제목 검색 키워드 ──
# 신규방식: "상품별 분배" (스프레드시트 D49~ZZ62)
SUPPLY_TABLE_TITLE_VARIANTS = ["상품별 분배", "상품별분배"]
# 이전방식: "(last ver) 마케팅팀 _ 상품별 분배" (스프레드시트 D94~ZZ107)
OLD_TABLE_TITLE_VARIANTS = ["last ver"]
# KOGAS 제출: "가스공사 제출용 판매량" (스프레드시트 D7~ZZ20)
KOGAS_TABLE_TITLE_VARIANTS = ["가스공사 제출용 판매량", "가스공사제출용판매량"]
N_HOUSING = len(HOUSING_PRODUCTS)   # 4
N_OTHER   = len(OTHER_PRODUCTS)     # 9
SUBTOTAL_LABEL = "소 계"
TOTAL_LABEL    = "합 계"
SUBTOTAL_STYLE = "background-color:#ddeaf8; font-weight:bold; color:#1a3c5e;"
MJ_TO_GJ = 1000.0  # MJ → GJ 변환 (÷1000)
# ──────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────
def _find_row_containing(raw, text_variants, search_cols=(0, 1, 2, 3)):
    """raw(DataFrame, header=None)에서 지정 텍스트가 포함된 첫 행의 0-index를 반환. 못 찾으면 None."""
    max_col = min(raw.shape[1], max(search_cols) + 1)
    for r in range(len(raw)):
        for c in range(max_col):
            val = raw.iat[r, c]
            if pd.isna(val):
                continue
            val_str = str(val)
            for t in text_variants:
                if t in val_str:
                    return r
    return None
def _extract_product_table(raw, title_variants, data_start_col=DATA_START_COL):
    """
    제목 텍스트를 시트에서 찾아 그 아래 표준 구조
    (제목행 → 헤더행(날짜) → 주택용 N_HOUSING행 → 소계 → 기타 N_OTHER행 → 소계 → 합계)
    를 상대 위치로 인식해 (dates_valid, df[상품 x 연월], error_msg, debug) 를 반환한다.
    """
    dbg = {}
    title_idx = _find_row_containing(raw, title_variants)
    dbg["title_idx_found"] = title_idx
    if title_idx is None:
        return None, None, f"'{title_variants[0]}' 표 제목을 시트에서 찾을 수 없습니다.", dbg
    header_idx = title_idx + 1
    housing_rows = [header_idx + i for i in range(1, N_HOUSING + 1)]
    subtotal1_row = header_idx + N_HOUSING + 1
    other_rows = [subtotal1_row + i for i in range(1, N_OTHER + 1)]
    data_rows = housing_rows + other_rows
    dbg["header_idx"] = header_idx
    dbg["data_rows"] = data_rows
    dates = pd.to_datetime(raw.iloc[header_idx, data_start_col:], errors="coerce")
    valid_cols = [i for i, d in enumerate(dates) if pd.notna(d)]
    dates_valid = dates.iloc[valid_cols]
    dbg["n_valid_date_cols"] = len(valid_cols)
    dbg["date_sample"] = [str(d) for d in dates_valid.iloc[:5]]
    if len(valid_cols) == 0:
        return None, None, (
            f"'{title_variants[0]}' 헤더 행(0-idx {header_idx})에서 날짜를 하나도 인식하지 못했습니다."
        ), dbg
    result = {}
    for idx, row_i in enumerate(data_rows):
        if row_i >= len(raw): continue
        product = PRODUCT_LIST[idx]
        vals = pd.to_numeric(
            raw.iloc[row_i, data_start_col:].iloc[valid_cols]
            .astype(str).str.replace(",", ""), errors="coerce").values
        result[product] = vals
    df = pd.DataFrame(result, index=dates_valid).T
    df.index.name = "상품"
    return dates_valid, df, None, dbg
@st.cache_data(ttl=1800)
def load_gsheet_data():
    """구글시트에서 신규방식, 이전방식, KOGAS 데이터를 모두 로드한다."""
    debug = {}
    try:
        resp = requests.get(NEW_GSHEET_URL, timeout=20)
        resp.raise_for_status()
        raw = pd.read_csv(StringIO(resp.text), header=None)
        debug["raw_shape"] = raw.shape
        # ── [1] 신규방식: "상품별 분배" 표 (D49:ZZ62, 재무팀 실측 상품별 공급량 GJ) ──
        dates_valid, supply_df, err, sdbg = _extract_product_table(raw, SUPPLY_TABLE_TITLE_VARIANTS)
        debug["supply_table"] = sdbg
        if err:
            return None, None, None, None, None, None, None, err, debug
        # 천연가스 공급량(GJ): 행4(0-indexed=3), C열(idx=2)부터 — BIO 제외 총량
        valid_cols = [i for i, d in enumerate(
            pd.to_datetime(raw.iloc[sdbg["header_idx"], DATA_START_COL:], errors="coerce")) if pd.notna(d)]
        natgas_raw = raw.iloc[NATGAS_ROW_IDX, TOTAL_START_COL:].reset_index(drop=True)
        natgas_vals = pd.to_numeric(
            natgas_raw.iloc[[v + 1 for v in valid_cols]]
            .astype(str).str.replace(",", ""), errors="coerce").values
        natgas_supply_df = pd.DataFrame({"연월": dates_valid.values, "천연가스공급량_GJ": natgas_vals})
        natgas_supply_df = natgas_supply_df[natgas_supply_df["천연가스공급량_GJ"] > 0].reset_index(drop=True)
        total_supply_df = natgas_supply_df.rename(columns={"천연가스공급량_GJ": "총공급량_GJ"})
        debug["supply_nonzero_cols"] = int((supply_df.sum(axis=0) > 0).sum())
        # 신규방식 구성비(%)
        col_sum = supply_df.sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio_df = supply_df.div(col_sum.replace(0, np.nan), axis=1) * 100
        ratio_df = ratio_df.fillna(0.0)
        debug["dates_min"] = str(dates_valid.min()) if len(dates_valid) else None
        debug["dates_max"] = str(dates_valid.max()) if len(dates_valid) else None
        # ── [2] 이전방식: "(last ver) 마케팅팀 상품별 분배" 표 (D94:ZZ107, GJ) ──
        old_dates, old_supply_df, oerr, odbg = _extract_product_table(raw, OLD_TABLE_TITLE_VARIANTS)
        debug["old_table"] = odbg
        if oerr or old_supply_df is None:
            debug["old_error"] = oerr
            old_supply_df = None
            old_ratio_df = None
        else:
            old_col_sum = old_supply_df.sum(axis=0)
            with np.errstate(divide="ignore", invalid="ignore"):
                old_ratio_df = old_supply_df.div(old_col_sum.replace(0, np.nan), axis=1) * 100
            old_ratio_df = old_ratio_df.fillna(0.0)
            debug["old_nonzero_cols"] = int((old_supply_df.sum(axis=0) > 0).sum())
        # ── [3] KOGAS 제출: "가스공사 제출용 판매량(MJ)" 표 (D7:ZZ20) ──
        kogas_dates, kogas_mj_df, kerr, kdbg = _extract_product_table(raw, KOGAS_TABLE_TITLE_VARIANTS)
        debug["kogas_table"] = kdbg
        if kerr or kogas_mj_df is None:
            debug["kogas_error"] = kerr
            kogas_gj_df = None
        else:
            kogas_gj_df = kogas_mj_df / MJ_TO_GJ  # MJ → GJ
            kogas_gj_df.columns = [c.strftime("%Y-%m") for c in kogas_gj_df.columns]
            debug["kogas_nonzero_cols"] = int((kogas_gj_df.sum(axis=0) > 0).sum())
        return total_supply_df, ratio_df, supply_df, dates_valid, old_supply_df, old_ratio_df, kogas_gj_df, None, debug
    except Exception as e:
        debug["exception"] = str(e)
        return None, None, None, None, None, None, None, str(e), debug
def build_new_result(supply_df, ratio_df, y_start, y_end, natgas_series=None):
    """
    상품별 공급량 계산 (이전/신규방식 공통).
    supply_df       : 상품별 공급량(실측, GJ) — 각 방식의 "상품별 분배" 표
    natgas_series    : 천연가스 공급량(행4, BIO 제외) Series (index=Timestamp).
                       상품별분배 합계를 천연가스공급량(행4)에 맞춰 비례 보정한다.
    """
    rows = []
    for col in supply_df.columns:
        if pd.isna(col) or not (y_start <= col.year <= y_end): continue
        if natgas_series is not None and col in natgas_series.index:
            ng_val = float(natgas_series[col])
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
                "공급량_GJ": raw_val * scale,
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
    # 각 열(월)별 합계 계산 — 비중 50% 초과 셀에만 그라데이션 적용
    col_totals = {}
    if gradient and not diff_mode:
        total_mask = [i for i, t in enumerate(row_types) if t == "total"]
        if total_mask:
            total_i = total_mask[0]
            for dc in date_cols:
                try: col_totals[dc] = float(df.at[total_i, dc])
                except: col_totals[dc] = 0.0
        else:
            data_mask2 = [i for i, t in enumerate(row_types) if t == "data"]
            for dc in date_cols:
                try: col_totals[dc] = float(df.loc[data_mask2, dc].astype(float).sum())
                except: col_totals[dc] = 0.0
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
                # diff_mode가 아닌 경우: 비중 50% 초과인 셀에만 그라데이션
                col_total = col_totals.get(dc, 0.0)
                pct_share = abs(fval) / col_total * 100 if col_total else 0.0
                apply_bg = diff_mode or pct_share > 50
                bg = _gradient_bg(fval, abs_max, diff_mode) if apply_bg else ""
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
    """소계 행에 배경색 적용 (인덱스 또는 '월' 컬럼 기준)."""
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    # 인덱스에 소계가 있는 경우
    if SUBTOTAL_LABEL in df.index:
        styles.loc[SUBTOTAL_LABEL] = SUBTOTAL_STYLE
    # '월' 컬럼에 소계가 있는 경우 (hide_index=True 테이블용)
    elif "월" in df.columns:
        mask = df["월"] == SUBTOTAL_LABEL
        for idx in df.index[mask]:
            styles.loc[idx] = SUBTOTAL_STYLE
    return styles
# ──────────────────────────────────────────────
# 사이드바
# ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ 설정")
    st.markdown("#### 📅 조회 기간")
    c1, c2 = st.columns(2)
    y_start = c1.number_input("시작", 2014, 2030, 2018)
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
    <div>천연가스 공급량(BIO제외) = 상품별 공급량 도출 (스프레드시트 D94:ZZ107)</div>
  </div>
  <div class="info-row">
    <div><span class="badge-new">신규방식</span></div>
    <div>천연가스 공급량(BIO제외) = 재무팀 상품별 공급량 비율 적용 (스프레드시트 D49:ZZ62)</div>
  </div>
  <div class="info-row">
    <div><span class="badge-kogas">KOGAS 제출</span></div>
    <div>수급량 비용 정산시 사용하는 물량 (스프레드시트 D7:ZZ20)</div>
  </div>
  <div style="margin-top:6px; color:#888; font-size:0.85rem;">
    ※ 세 방식 모두 목표 총량은 <b>천연가스 공급량(BIO 제외, 구글시트 행4)</b>으로 동일하며,
    상품별 배분 방법(비율 산출 기준)만 다릅니다.
  </div>
  <div style="margin-top:8px; font-size:0.85rem;">
    📎 <a href="https://docs.google.com/spreadsheets/d/1gIhArPlLBJ9fwlaqXtZWxiKlSK9hbRuz6HcDw_Yf7Is/edit?pli=1&gid=0#gid=0" target="_blank" style="color:#2c5f8a;">데이터 원본 스프레드시트 열기</a>
  </div>
</div>
""", unsafe_allow_html=True)
# ── 데이터 로드 (구글시트 1개에서 3개 테이블 모두 로드)
(total_supply_df, ratio_df, supply_df, dates,
 old_supply_df, old_ratio_df, kogas_gj_df,
 gs_err, gs_debug) = load_gsheet_data()
with st.sidebar.expander("🔧 구글시트 로드 진단정보", expanded=bool(gs_err)):
    st.json(gs_debug)
if gs_err or ratio_df is None:
    st.error(f"구글시트 로드 실패: {gs_err}")
    st.info("구글시트를 **링크가 있는 모든 사용자 → 뷰어** 로 공유 설정해 주세요.")
    st.stop()
st.sidebar.success("✅ 구글시트(신규방식) 로드 완료")
if supply_df.sum(axis=0).sum() == 0:
    st.warning(
        "⚠️ '상품별 분배' 표 위치는 찾았지만 데이터 값이 모두 0으로 읽혔습니다. "
        "사이드바의 진단정보를 열어 header_idx / data_rows가 "
        "실제 시트 행 번호와 맞는지 확인해주세요."
    )
if old_supply_df is None:
    st.sidebar.warning(
        "⚠️ 이전방식 테이블 로드 실패: " + str(gs_debug.get("old_error", "")) +
        " — 시트에 '(last ver)' 표 제목이 있는지 확인해주세요."
    )
else:
    st.sidebar.success("✅ 구글시트(이전방식) 로드 완료")
if kogas_gj_df is None:
    st.sidebar.warning(
        "⚠️ 'KOGAS 제출' 로드 실패: " + str(gs_debug.get("kogas_error", "")) +
        " — 시트에 '가스공사 제출용 판매량(MJ)' 표 제목이 남아있는지 확인해주세요."
    )
else:
    st.sidebar.success("✅ 구글시트(KOGAS 제출) 로드 완료")
# 천연가스 공급량(행4, BIO 제외) Series 생성 — 이전/신규방식 공통 목표 총량
_natgas_ts = total_supply_df.copy()
_natgas_ts["연월"] = pd.to_datetime(_natgas_ts["연월"])
_natgas_series_ts = _natgas_ts.set_index("연월")["총공급량_GJ"]
# ── 신규방식 결과
new_result = build_new_result(supply_df, ratio_df, y_start, y_end, natgas_series=None)
# ── 이전방식 결과 (같은 구글시트, 다른 행 범위)
if old_supply_df is not None and old_ratio_df is not None:
    old_result = build_new_result(old_supply_df, old_ratio_df, y_start, y_end, natgas_series=None)
else:
    old_result = pd.DataFrame(columns=["연월", "상품", "그룹", "구성비(%)", "공급량_GJ", "연도"])
total_filtered = total_supply_df[
    (pd.to_datetime(total_supply_df["연월"]).dt.year >= y_start) &
    (pd.to_datetime(total_supply_df["연월"]).dt.year <= y_end)].copy()
if new_result.empty:
    st.warning("선택 기간에 신규방식 데이터가 없습니다."); st.stop()
# ── 천연가스 공급량(행4, BIO 제외) — YYYY-MM 문자열 인덱스 Series
_ng_df = total_supply_df.copy()
_ng_df["연월_str"] = pd.to_datetime(_ng_df["연월"]).dt.strftime("%Y-%m")
_ng_series = _ng_df.set_index("연월_str")["총공급량_GJ"]
# KOGAS 제출 데이터가 있는 2025년 월 목록
if kogas_gj_df is not None and len(kogas_gj_df.columns) > 0:
    _KOGAS_MONTHS = sorted([c for c in kogas_gj_df.columns if str(c).startswith("2025")])
else:
    _KOGAS_MONTHS = []
# 2025년 천연가스 공급량 (BIO 제외 총량)
_ss_natgas_2025 = _ng_series.reindex(_KOGAS_MONTHS, fill_value=0)
# KOGAS 제출 실제 총량 (MJ→GJ 환산값 그대로)
if kogas_gj_df is not None and _KOGAS_MONTHS:
    _KOGAS_MONTHLY_TOTAL_GJ = kogas_gj_df.reindex(columns=_KOGAS_MONTHS, fill_value=0.0).sum(axis=0)
else:
    _KOGAS_MONTHLY_TOTAL_GJ = pd.Series(0.0, index=_KOGAS_MONTHS)
# KOGAS_GJ = 스프레드시트 MJ값 ÷ 1000 (원본 그대로, 스케일링 없음)
if kogas_gj_df is not None and _KOGAS_MONTHS:
    KOGAS_GJ = kogas_gj_df.reindex(columns=_KOGAS_MONTHS, fill_value=0.0)
else:
    KOGAS_GJ = pd.DataFrame(0.0, index=PRODUCT_LIST, columns=_KOGAS_MONTHS)
    KOGAS_GJ.index.name = "상품"
_SS_NEW_TOTAL_2025 = _ss_natgas_2025
common_products = [p for p in PRODUCT_LIST
                   if p in new_result["상품"].unique()
                   and (old_result.empty or p in old_result["상품"].unique())]
# ══════════════════════════════════════════════
# TAB (3개: 매트릭스, 상세비교, KOGAS비교)
# ══════════════════════════════════════════════
tab0, tab1, tab2 = st.tabs([
    "📊 전체 비교 (매트릭스)",
    "🔍 이전방식 vs 신규방식 상세 비교",
    "🏛️ 비율적용 물량 vs KOGAS제출 물량",
])
# ══════════════════════════════════════════════
# TAB 0 : 전체 비교 매트릭스
# ══════════════════════════════════════════════
with tab0:
    if old_result.empty:
        st.warning("이전방식 데이터가 로드되지 않아 매트릭스 비교를 표시할 수 없습니다.")
    else:
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
    if old_result.empty:
        st.warning("이전방식 데이터가 로드되지 않아 상세 비교를 표시할 수 없습니다.")
    else:
        # ── 전체 합계량 비교 카드 (모든 상품 합산, 2025년)
        _ul = unit_label()
        old_total_2025 = old_result[old_result["연월"].dt.year == 2025]["공급량_GJ"].sum() if not old_result.empty else 0
        new_total_2025 = new_result[new_result["연월"].dt.year == 2025]["공급량_GJ"].sum()
        total_diff_t1  = new_total_2025 - old_total_2025
        total_pct_t1   = total_diff_t1 / old_total_2025 * 100 if old_total_2025 else 0
        sign_t1        = "+" if total_pct_t1 >= 0 else ""
        card_ct1       = "#e8501a" if total_pct_t1 >= 0 else "#2c5f8a"
        st.markdown('<div class="sub">📊 전체 합계량 비교 — 2025년 (모든 상품 합산)</div>', unsafe_allow_html=True)
        ca1, cb1, cc1 = st.columns(3)
        ca1.markdown(f"""<div style="background:#f4f8fc; border-left:4px solid #2c5f8a;
            padding:0.8rem 1.2rem; border-radius:4px;">
            <div style="font-size:0.8rem; color:#666;">이전방식 2025년 전체 합계</div>
            <div style="font-size:1.3rem; font-weight:700; color:#2c5f8a;">{gj_to_unit(old_total_2025):,.1f} {_ul}</div>
        </div>""", unsafe_allow_html=True)
        cb1.markdown(f"""<div style="background:#fff4f0; border-left:4px solid #e8501a;
            padding:0.8rem 1.2rem; border-radius:4px;">
            <div style="font-size:0.8rem; color:#666;">신규방식 2025년 전체 합계</div>
            <div style="font-size:1.3rem; font-weight:700; color:#e8501a;">{gj_to_unit(new_total_2025):,.1f} {_ul}</div>
        </div>""", unsafe_allow_html=True)
        cc1.markdown(f"""<div style="background:#f9f9f9; border-left:4px solid {card_ct1};
            padding:0.8rem 1.2rem; border-radius:4px;">
            <div style="font-size:0.8rem; color:#666;">연간 차이 (신규 − 이전)</div>
            <div style="font-size:1.5rem; font-weight:800; color:{card_ct1};">{sign_t1}{total_pct_t1:.2f}%</div>
            <div style="font-size:0.8rem; color:#888;">{sign_t1}{gj_to_unit(total_diff_t1):,.1f} {_ul}</div>
        </div>""", unsafe_allow_html=True)
        st.markdown("---")
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
            tbl_mo_yr = pd.DataFrame({"월": MONTH_KR, col_name: old_mo_vals, col_name2: new_mo_vals,
                f"차이_{_ul}": diff_vals, "차이(%)": mo_pct})
            subtotal_mo = pd.DataFrame([{"월": SUBTOTAL_LABEL, col_name: sum(old_mo_vals), col_name2: sum(new_mo_vals),
                f"차이_{_ul}": sum(diff_vals),
                "차이(%)": (sum(new_mo_gj)-sum(old_mo_gj))/sum(old_mo_gj)*100 if sum(old_mo_gj) else 0.0,
            }])
            tbl_mo_full = pd.concat([tbl_mo_yr, subtotal_mo], ignore_index=True)
            fmt_dict = {col_name:"{:,.1f}", col_name2:"{:,.1f}", f"차이_{_ul}":"{:,.1f}", "차이(%)":"{:+.2f}%"}
            st.dataframe(tbl_mo_full.style.format(fmt_dict).apply(style_subtotal_any, axis=None)
                .map(color_pct, subset=["차이(%)"]), use_container_width=True, hide_index=True)
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
# TAB 2 : 비율적용 물량 vs KOGAS 제출 물량
# ══════════════════════════════════════════════
with tab2:
    st.markdown("""
    <span style="color:#888; font-size:0.85rem; line-height:2.5;">
    ※ 세 방식 모두 <b>BIO가스를 제외한 천연가스 공급량(스프레드시트 행4)</b>을 비교 기준 총량으로 사용합니다.
    &nbsp;|&nbsp; KOGAS 제출 물량은 2025년 1~12월 데이터만 제공됩니다.</span>
    <br>
    """, unsafe_allow_html=True)
    if not _KOGAS_MONTHS:
        st.warning(
            "⚠️ 구글시트에서 '가스공사 제출용 판매량(MJ)' 표를 찾지 못해 KOGAS 제출 물량 비교를 표시할 수 없습니다. "
            "시트에 해당 표가 있는지, 제목 텍스트가 남아있는지 확인해주세요."
        )
        st.stop()
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
        ratio_src_all = old_result[old_result["연월"].dt.year == 2025].copy() if not old_result.empty else pd.DataFrame()
    else:
        _badge_all  = "신규방식"
        _color_all  = "#1a3c6e"
        ratio_src_all = new_result[new_result["연월"].dt.year == 2025].copy()
    # ── 전체 합계 비교
    st.markdown('<div class="sub">📊 전체 합계량 비교 — 2025년 (모든 상품 합산)</div>', unsafe_allow_html=True)
    ratio_total_mo_gj = [
        ratio_src_all[ratio_src_all["연월"].dt.strftime("%Y-%m") == m]["공급량_GJ"].sum()
        if not ratio_src_all.empty else 0
        for m in KOGAS_2025_MONTHS
    ]
    kogas_total_mo_gj = [float(_KOGAS_MONTHLY_TOTAL_GJ.get(m, 0)) for m in KOGAS_2025_MONTHS]
    if not use_old_mode:
        ratio_total_mo_gj = [float(_SS_NEW_TOTAL_2025.get(m, 0)) for m in KOGAS_2025_MONTHS]
    ratio_total_ann = sum(ratio_total_mo_gj)
    kogas_total_ann = sum(kogas_total_mo_gj)
    total_diff_gj   = ratio_total_ann - kogas_total_ann
    total_pct       = total_diff_gj / kogas_total_ann * 100 if kogas_total_ann else 0
    sign_t          = "+" if total_pct >= 0 else ""
    card_ct         = "#e8501a" if total_pct >= 0 else "#2c5f8a"
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
    k_selected = st.selectbox(
        "비교할 상품 선택", options=common_products,
        index=common_products.index("개별난방용") if "개별난방용" in common_products else 0,
        key="kogas_product_sel",
    )
    if k_selected in KOGAS_GJ.index:
        kogas_prod_gj = KOGAS_GJ.loc[k_selected]
    else:
        kogas_prod_gj = pd.Series(0.0, index=KOGAS_2025_MONTHS)
    badge_label = _badge_all
    bar_color   = "#1a3c6e"
    if use_old_mode:
        ratio_src = old_result[old_result["상품"] == k_selected].copy() if not old_result.empty else pd.DataFrame()
    else:
        ratio_src = new_result[new_result["상품"] == k_selected].copy()
    ratio_src_2025 = ratio_src[ratio_src["연월"].dt.year == 2025].copy() if not ratio_src.empty else pd.DataFrame()
    if not ratio_src_2025.empty:
        ratio_src_2025["연월_str"] = ratio_src_2025["연월"].dt.strftime("%Y-%m")
        ratio_monthly = ratio_src_2025.set_index("연월_str")["공급량_GJ"].reindex(KOGAS_2025_MONTHS, fill_value=0)
    else:
        ratio_monthly = pd.Series(0.0, index=KOGAS_2025_MONTHS)
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
    # ── 월별 비교 테이블
    st.markdown(f'<div class="sub">📋 월별 비교 테이블 — {k_selected} (2025년)</div>', unsafe_allow_html=True)
    col_r = f"{badge_label}_{_ul}"
    col_kg = f"KOGAS제출_{_ul}"
    tbl_k = pd.DataFrame({
        col_r:           ratio_vals,
        col_kg:          kogas_vals,
        f"차이_{_ul}":   diff_vals,
        "차이(%)":       mo_pct_k,
    })
    tbl_k.insert(0, "월", MONTH_KR)
    sub_k = pd.DataFrame([{"월": SUBTOTAL_LABEL,
        col_r:          sum(ratio_vals),
        col_kg:         sum(kogas_vals),
        f"차이_{_ul}":  sum(diff_vals),
        "차이(%)":      (sum(ratio_vals_gj) - sum(kogas_vals_gj)) / sum(kogas_vals_gj) * 100
                        if sum(kogas_vals_gj) else 0.0,
    }])
    tbl_k_full = pd.concat([tbl_k, sub_k], ignore_index=True)
    fmt_k = {col_r:"{:,.1f}", col_kg:"{:,.1f}", f"차이_{_ul}":"{:,.1f}", "차이(%)":"{:+.2f}%"}
    st.dataframe(tbl_k_full.style.format(fmt_k).apply(style_subtotal_any, axis=None)
        .map(color_pct, subset=["차이(%)"]), use_container_width=True, hide_index=True)
    st.markdown("<br>", unsafe_allow_html=True)
    # ── 전체 상품 연간 비교 테이블 (정산그룹 병합 구조 — HTML rowspan)
    st.markdown('<div class="sub">📋 전체 상품 연간 비교 — 2025년 합계</div>', unsafe_allow_html=True)
    product_data = {}
    for p in PRODUCT_LIST:
        if use_old_mode:
            p_src = old_result[old_result["상품"] == p] if not old_result.empty else pd.DataFrame()
        else:
            p_src = new_result[new_result["상품"] == p]
        p_2025 = p_src[p_src["연월"].dt.year == 2025]["공급량_GJ"].sum() if not p_src.empty else 0.0
        k_2025 = float(KOGAS_GJ.loc[p, _KOGAS_MONTHS].sum()) if p in KOGAS_GJ.index else 0.0
        diff_v = p_2025 - k_2025
        pct_v  = diff_v / k_2025 * 100 if k_2025 else 0.0
        product_data[p] = {
            "r_gj": p_2025, "k_gj": k_2025,
            "diff_gj": diff_v, "pct": pct_v,
        }
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
        rowspan = n + 1
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
    # 엑셀 다운로드용 DataFrame
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
