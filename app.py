import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from io import BytesIO
import requests

# ─────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="도시가스 용도별 공급량 예측",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# CSS 스타일
# ─────────────────────────────────────────────
st.markdown("""
<style>
    .main-title {
        font-size: 1.6rem;
        font-weight: 700;
        color: #1a3c5e;
        border-bottom: 3px solid #e8501a;
        padding-bottom: 0.4rem;
        margin-bottom: 1.2rem;
    }
    .sub-title {
        font-size: 1.1rem;
        font-weight: 600;
        color: #2c5f8a;
        margin: 1rem 0 0.4rem 0;
    }
    .metric-card {
        background: #f4f8fc;
        border-left: 4px solid #2c5f8a;
        padding: 0.6rem 1rem;
        border-radius: 4px;
        margin-bottom: 0.5rem;
    }
    .info-box {
        background: #fff8e1;
        border: 1px solid #ffc107;
        border-radius: 6px;
        padding: 0.8rem 1rem;
        font-size: 0.88rem;
        margin-bottom: 1rem;
    }
    .stDownloadButton > button {
        background-color: #1a3c5e;
        color: white;
        border-radius: 6px;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 상수 설정
# ─────────────────────────────────────────────
# 구글시트 공개 CSV URL
GSHEET_ID = "13HrIz6OytYDykXeXzXJ02I6XbaKin1YaKBoO2kBd6Bs"
GSHEET_URL = f"https://docs.google.com/spreadsheets/d/{GSHEET_ID}/export?format=csv&gid=0"

# GitHub raw URL (구성비 엑셀)
GITHUB_RATIO_URL = "https://raw.githubusercontent.com/Han11112222/new_raw_data_gas-supply-forecast-by-usage/main/ratio_data.xlsx"

# 용도 순서 및 그룹 정의
USAGE_ORDER = [
    "취사용", "개별난방용", "중앙난방용", "자가열전용",   # 주택용
    "일반용", "냉난방공조용", "업무난방용", "산업용",       # 기타
    "수송용", "열병합용", "연료전지용", "열전용설비용", "주한미군"
]
GROUP_MAP = {
    "취사용": "주택용", "개별난방용": "주택용",
    "중앙난방용": "주택용", "자가열전용": "주택용",
    "일반용": "기타", "냉난방공조용": "기타",
    "업무난방용": "기타", "산업용": "기타",
    "수송용": "기타", "열병합용": "기타",
    "연료전지용": "기타", "열전용설비용": "기타", "주한미군": "기타",
}

COLOR_MAP = {
    "취사용": "#4e79a7", "개별난방용": "#f28e2b", "중앙난방용": "#e15759",
    "자가열전용": "#76b7b2", "일반용": "#59a14f", "냉난방공조용": "#edc948",
    "업무난방용": "#b07aa1", "산업용": "#ff9da7", "수송용": "#9c755f",
    "열병합용": "#bab0ac", "연료전지용": "#86bcb6", "열전용설비용": "#d3a0a0",
    "주한미군": "#aecbcf",
}

# ─────────────────────────────────────────────
# 데이터 로드 함수
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_ratio_data(uploaded_file=None):
    """구성비 데이터 로드 (업로드 파일 우선, 없으면 GitHub)"""
    try:
        if uploaded_file is not None:
            raw = pd.read_excel(uploaded_file, sheet_name="구성비", header=None)
        else:
            resp = requests.get(GITHUB_RATIO_URL, timeout=15)
            resp.raise_for_status()
            raw = pd.read_excel(BytesIO(resp.content), sheet_name="구성비", header=None)

        # 헤더 행: 0행=정산항목 이름, 1행~= 날짜
        dates = pd.to_datetime(raw.iloc[0, 2:], errors="coerce")
        items = raw.iloc[1:15, 1].tolist()   # 정산항목 (소계·합계 제외)
        data_rows = raw.iloc[1:15, 2:].values.astype(float)

        df = pd.DataFrame(data_rows, index=items, columns=dates)
        df.index.name = "용도"
        # 소계·합계 행 제거 (NaN 항목 or '소계' 포함)
        df = df[~df.index.isna()]
        df.columns = pd.to_datetime(df.columns)
        df = df.sort_index(axis=1)
        return df, None
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=1800)
def load_supply_data():
    """
    구글시트 '일별실적' 탭에서 일별 공급량 로드 후 월별 합산
    컬럼 구조: A=일자, B=공급량(MJ), C=공급량(M3), D=평균기온(℃), E=최저, F=최고
    """
    try:
        from io import StringIO
        resp = requests.get(GSHEET_URL, timeout=20)
        resp.raise_for_status()

        df = pd.read_csv(StringIO(resp.text))

        # ── 컬럼명 정규화 (실제 시트 헤더 기준)
        # 예상 헤더: 일자, 공급량(MJ), 공급량(M3), 평균기온(℃), 최저, 최고
        df.columns = df.columns.str.strip()

        # 날짜 컬럼: '일자'
        date_col = "일자"
        if date_col not in df.columns:
            # 헤더가 다를 경우 첫 번째 컬럼을 날짜로 간주
            date_col = df.columns[0]

        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])

        # ── 공급량(MJ) → GJ 변환 (÷ 1,000)
        mj_col = next((c for c in df.columns if "MJ" in str(c) or "공급량" in str(c)), None)
        m3_col = next((c for c in df.columns if "M3" in str(c) or "Nm" in str(c)), None)
        temp_col = next((c for c in df.columns if "평균" in str(c) or "기온" in str(c)), None)
        low_col  = next((c for c in df.columns if "최저" in str(c)), None)
        high_col = next((c for c in df.columns if "최고" in str(c)), None)

        if mj_col is None:
            return None, "공급량(MJ) 컬럼을 찾을 수 없습니다."

        df[mj_col] = pd.to_numeric(df[mj_col], errors="coerce")
        df["공급량_GJ"] = df[mj_col] / 1_000  # MJ → GJ

        if m3_col:
            df[m3_col] = pd.to_numeric(df[m3_col], errors="coerce")
        if temp_col:
            df[temp_col] = pd.to_numeric(df[temp_col], errors="coerce")
        if low_col:
            df[low_col] = pd.to_numeric(df[low_col], errors="coerce")
        if high_col:
            df[high_col] = pd.to_numeric(df[high_col], errors="coerce")

        # ── 월별 합산
        df["연월"] = df[date_col].dt.to_period("M").dt.to_timestamp()

        agg_dict = {"공급량_GJ": "sum"}
        if m3_col:
            agg_dict[m3_col] = "sum"
        if temp_col:
            agg_dict[temp_col] = "mean"
        if low_col:
            agg_dict[low_col] = "mean"
        if high_col:
            agg_dict[high_col] = "mean"

        monthly = df.groupby("연월").agg(agg_dict).reset_index()

        # 컬럼명 정리
        rename_map = {"공급량_GJ": "총공급량_GJ"}
        if m3_col:
            rename_map[m3_col] = "총공급량_M3"
        if temp_col:
            rename_map[temp_col] = "평균기온"
        if low_col:
            rename_map[low_col] = "평균최저기온"
        if high_col:
            rename_map[high_col] = "평균최고기온"
        monthly = monthly.rename(columns=rename_map)

        # 공급량 0 또는 NaN 행 제거 (데이터 없는 기간)
        monthly = monthly[monthly["총공급량_GJ"] > 0].reset_index(drop=True)

        return monthly, None

    except Exception as e:
        return None, str(e)


def build_usage_df(monthly_supply: pd.DataFrame, ratio_df: pd.DataFrame, calc_type: str) -> pd.DataFrame:
    """
    용도별 물량 계산
    calc_type: '총공급량' or '수급량'
    """
    result_list = []
    for _, row in monthly_supply.iterrows():
        ym = row["연월"]
        supply_val = row.get(calc_type, None)
        if supply_val is None or pd.isna(supply_val):
            continue

        # 가장 가까운 구성비 날짜 찾기
        if ym in ratio_df.columns:
            ratio_col = ym
        else:
            diff = abs(ratio_df.columns - ym)
            ratio_col = ratio_df.columns[diff.argmin()]

        for usage in USAGE_ORDER:
            if usage in ratio_df.index:
                ratio_val = ratio_df.loc[usage, ratio_col]
                try:
                    ratio_val = float(ratio_val) / 100.0
                except Exception:
                    ratio_val = 0.0
                amount = supply_val * ratio_val
                result_list.append({
                    "연월": ym,
                    "용도": usage,
                    "그룹": GROUP_MAP.get(usage, "기타"),
                    "비율(%)": ratio_df.loc[usage, ratio_col],
                    "공급량_GJ": amount,
                })

    if not result_list:
        # 빈 경우 컬럼만 있는 빈 DataFrame 반환
        return pd.DataFrame(columns=["연월", "용도", "그룹", "비율(%)", "공급량_GJ"])

    return pd.DataFrame(result_list)


def to_excel_download(df_pivot: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_pivot.to_excel(writer, sheet_name="용도별공급량")
    return buf.getvalue()


# ─────────────────────────────────────────────
# 사이드바
# ─────────────────────────────────────────────
with st.sidebar:
    st.image("https://raw.githubusercontent.com/Han11112222/your-repo/main/logo.png",
             use_column_width=True) if False else None  # 로고 있을 경우 활성화
    st.markdown("### ⚙️ 설정")

    uploaded_ratio = st.file_uploader(
        "📂 구성비 엑셀 업로드 (선택)",
        type=["xlsx"],
        help="업로드하지 않으면 GitHub에 저장된 파일을 사용합니다."
    )

    st.markdown("---")
    st.markdown("#### 📅 조회 기간")
    col_s, col_e = st.columns(2)
    with col_s:
        start_year = st.number_input("시작 연도", min_value=2016, max_value=2030, value=2016)
    with col_e:
        end_year = st.number_input("종료 연도", min_value=2016, max_value=2030, value=2026)

    st.markdown("---")
    st.markdown("#### 🔢 계산 기준")
    calc_mode = st.radio(
        "용도별 비율 적용 기준",
        ["총공급량", "수급량"],
        index=0,
        help="총공급량: 천연가스+바이오가스 공급량 합계\n수급량: 가스공사 수취량"
    )

    st.markdown("---")
    st.markdown("#### 📊 표시 단위")
    unit = st.radio("단위 선택", ["GJ", "Nm³"], index=0)
    GJ_TO_NM3 = 1 / 42.343   # MJ/Nm³ → GJ 변환 (열량 기준, 조정 가능)
    if unit == "Nm³":
        st.caption(f"* 변환계수: 1 Nm³ ≈ 42.343 MJ 적용")

    st.markdown("---")
    st.markdown("#### 🔍 용도 선택")
    selected_usages = st.multiselect(
        "표시할 용도 (미선택 시 전체)",
        options=USAGE_ORDER,
        default=[]
    )

# ─────────────────────────────────────────────
# 메인 헤더
# ─────────────────────────────────────────────
st.markdown('<div class="main-title">🔥 도시가스 용도별 공급량 예측</div>', unsafe_allow_html=True)
st.caption("대성에너지(주) 마케팅본부 | 공급량 실적(2014~) × 용도별 구성비 → 용도별 월별 예측값 산출")

# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────
tab_main, tab_ratio, tab_data, tab_guide = st.tabs([
    "📈 용도별 공급량 분석", "📋 용도별 구성비", "🗃️ 원시 데이터", "📖 사용 가이드"
])

with st.spinner("📡 데이터 로드 중..."):
    ratio_df, ratio_err = load_ratio_data(uploaded_ratio)
    supply_df, supply_err = load_supply_data()

# ─────────────────────────────────────────────
# TAB 1: 메인 분석
# ─────────────────────────────────────────────
with tab_main:
    if ratio_err:
        st.error(f"⚠️ 구성비 데이터 로드 실패: {ratio_err}")
        st.info("👈 사이드바에서 구성비 엑셀 파일을 직접 업로드해 주세요.")
    elif supply_err:
        st.warning(f"⚠️ 구글시트 공급량 데이터 로드 실패: {supply_err}")
        st.markdown("""
        <div class="info-box">
        📌 <b>수동 데이터 입력 모드</b><br>
        구글시트가 공개 설정(링크 공유)이 아닌 경우 아래 CSV를 직접 업로드하세요.<br>
        형식: <code>날짜, 총공급량_GJ, 수급량_GJ</code>
        </div>
        """, unsafe_allow_html=True)

        uploaded_supply = st.file_uploader("📂 공급량 CSV 업로드", type=["csv", "xlsx"])
        if uploaded_supply:
            try:
                if uploaded_supply.name.endswith(".csv"):
                    supply_df = pd.read_csv(uploaded_supply)
                else:
                    supply_df = pd.read_excel(uploaded_supply)

                # 날짜 컬럼 파싱
                for col in supply_df.columns:
                    try:
                        supply_df[col] = pd.to_datetime(supply_df[col])
                        supply_df = supply_df.rename(columns={col: "연월"})
                        break
                    except Exception:
                        continue
                supply_err = None
                st.success("✅ 공급량 데이터 업로드 완료!")
            except Exception as e:
                st.error(f"파일 파싱 오류: {e}")
    
    if ratio_df is not None and supply_df is not None and supply_err is None:
        # 기간 필터
        supply_df["연월"] = pd.to_datetime(supply_df["연월"])
        filtered = supply_df[
            (supply_df["연월"].dt.year >= start_year) &
            (supply_df["연월"].dt.year <= end_year)
        ].copy()

        # 수급량 컬럼이 없으면 총공급량으로 대체
        if calc_mode == "수급량" and "수급량_GJ" not in filtered.columns:
            st.warning("⚠️ 수급량 컬럼이 없어 총공급량으로 대체합니다.")
            filtered["수급량_GJ"] = filtered["총공급량_GJ"]

        if "총공급량_GJ" not in filtered.columns:
            st.error("데이터에 '총공급량_GJ' 컬럼이 없습니다. 데이터 형식을 확인해 주세요.")
        else:
            # 용도별 계산
            usage_df = build_usage_df(
                filtered.rename(columns={"총공급량_GJ": "총공급량", "수급량_GJ": "수급량"}),
                ratio_df,
                calc_mode
            )
            usage_df.rename(columns={"공급량_GJ": "공급량"}, inplace=True)

            # ── 디버그: 매칭 안 될 때 원인 표시
            if usage_df.empty or "용도" not in usage_df.columns or usage_df["용도"].nunique() == 0:
                st.error("⚠️ 용도별 데이터 계산 실패: 구성비 파일의 용도명과 매칭이 안 됩니다.")
                st.write("📋 구성비 파일의 용도 목록:", list(ratio_df.index))
                st.write("📋 기대하는 용도 목록:", USAGE_ORDER)
                st.stop()

            # 단위 변환
            if unit == "Nm³":
                usage_df["공급량"] = usage_df["공급량"] / 42.343 * 1000  # GJ→MJ→Nm³

            # 용도 필터
            display_usages = selected_usages if selected_usages else USAGE_ORDER
            usage_filtered = usage_df[usage_df["용도"].isin(display_usages)]

            # ── KPI 카드
            st.markdown('<div class="sub-title">📌 기간 합계 요약</div>', unsafe_allow_html=True)
            total_supply = filtered["총공급량_GJ"].sum()
            unit_label = unit
            kpi_cols = st.columns(4)
            with kpi_cols[0]:
                val = total_supply if unit == "GJ" else total_supply / 42.343 * 1000
                st.metric("총공급량 합계", f"{val:,.0f} {unit_label}")
            with kpi_cols[1]:
                months = filtered["연월"].nunique()
                st.metric("분석 기간", f"{months}개월")
            with kpi_cols[2]:
                top_usage = usage_filtered.groupby("용도")["공급량"].sum().idxmax()
                st.metric("최대 비중 용도", top_usage)
            with kpi_cols[3]:
                top_ratio = usage_filtered.groupby("용도")["비율(%)"].mean().max()
                st.metric("평균 최대 비율", f"{top_ratio:.1f}%")

            st.markdown("---")

            # ── 차트 1: 월별 누적 막대 (용도별)
            st.markdown('<div class="sub-title">📊 월별 용도별 공급량 (누적 막대)</div>', unsafe_allow_html=True)
            pivot = usage_filtered.pivot_table(
                index="연월", columns="용도", values="공급량", aggfunc="sum"
            ).fillna(0)
            pivot = pivot[[u for u in USAGE_ORDER if u in pivot.columns]]

            fig_bar = go.Figure()
            for usage in pivot.columns:
                fig_bar.add_trace(go.Bar(
                    x=pivot.index,
                    y=pivot[usage],
                    name=usage,
                    marker_color=COLOR_MAP.get(usage, "#aaa"),
                    hovertemplate=f"<b>{usage}</b><br>%{{x|%Y-%m}}<br>%{{y:,.0f}} {unit_label}<extra></extra>"
                ))
            fig_bar.update_layout(
                barmode="stack",
                xaxis_title="연월",
                yaxis_title=f"공급량 ({unit_label})",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                height=420,
                margin=dict(l=60, r=20, t=60, b=40),
                plot_bgcolor="white",
                paper_bgcolor="white",
            )
            fig_bar.update_xaxes(showgrid=False)
            fig_bar.update_yaxes(showgrid=True, gridcolor="#e8e8e8")
            st.plotly_chart(fig_bar, use_container_width=True)

            # ── 차트 2: 연도별 그룹 합계
            st.markdown('<div class="sub-title">📊 연도별 용도 그룹 합계</div>', unsafe_allow_html=True)
            usage_filtered["연도"] = usage_filtered["연월"].dt.year
            annual = usage_filtered.groupby(["연도", "그룹"])["공급량"].sum().reset_index()
            fig_ann = px.bar(
                annual, x="연도", y="공급량", color="그룹",
                color_discrete_map={"주택용": "#2c5f8a", "기타": "#e8501a"},
                labels={"공급량": f"공급량 ({unit_label})", "연도": "연도"},
                barmode="group", height=360,
            )
            fig_ann.update_layout(
                plot_bgcolor="white", paper_bgcolor="white",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=60, r=20, t=60, b=40),
            )
            st.plotly_chart(fig_ann, use_container_width=True)

            # ── 차트 3: 비율 라인 차트
            st.markdown('<div class="sub-title">📈 월별 용도별 구성비 추이</div>', unsafe_allow_html=True)
            pivot_ratio = usage_filtered.pivot_table(
                index="연월", columns="용도", values="비율(%)", aggfunc="mean"
            ).fillna(0)
            pivot_ratio = pivot_ratio[[u for u in USAGE_ORDER if u in pivot_ratio.columns]]

            fig_line = go.Figure()
            for usage in pivot_ratio.columns:
                fig_line.add_trace(go.Scatter(
                    x=pivot_ratio.index, y=pivot_ratio[usage],
                    name=usage,
                    mode="lines",
                    line=dict(color=COLOR_MAP.get(usage, "#aaa"), width=2),
                    hovertemplate=f"<b>{usage}</b><br>%{{x|%Y-%m}}<br>%{{y:.2f}}%<extra></extra>"
                ))
            fig_line.update_layout(
                xaxis_title="연월", yaxis_title="구성비 (%)",
                height=380,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                plot_bgcolor="white", paper_bgcolor="white",
                margin=dict(l=60, r=20, t=60, b=40),
            )
            fig_line.update_yaxes(showgrid=True, gridcolor="#e8e8e8")
            st.plotly_chart(fig_line, use_container_width=True)

            # ── 피벗 테이블 + 다운로드
            st.markdown('<div class="sub-title">📋 월별 용도별 공급량 테이블</div>', unsafe_allow_html=True)
            pivot_display = pivot.copy()
            pivot_display.index = pivot_display.index.strftime("%Y-%m")
            pivot_display = pivot_display.round(1)

            st.dataframe(
                pivot_display.style.format("{:,.1f}"),
                use_container_width=True, height=320
            )

            dl_data = to_excel_download(pivot_display)
            st.download_button(
                label="⬇️ 엑셀 다운로드",
                data=dl_data,
                file_name=f"용도별공급량_{start_year}_{end_year}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# ─────────────────────────────────────────────
# TAB 2: 구성비
# ─────────────────────────────────────────────
with tab_ratio:
    st.markdown('<div class="sub-title">📋 월별 용도별 구성비 원본</div>', unsafe_allow_html=True)
    if ratio_df is not None:
        display_ratio = ratio_df.copy()
        display_ratio.columns = pd.to_datetime(display_ratio.columns).strftime("%Y-%m")

        # 기간 필터 적용
        cols_in_range = [
            c for c in display_ratio.columns
            if start_year <= int(c[:4]) <= end_year
        ]
        if cols_in_range:
            display_ratio = display_ratio[cols_in_range]

        st.dataframe(
            display_ratio.style.format("{:.4f}").background_gradient(
                cmap="Blues", axis=1
            ),
            use_container_width=True, height=420
        )

        # 히트맵
        st.markdown('<div class="sub-title">🗺️ 구성비 히트맵</div>', unsafe_allow_html=True)
        fig_heat = px.imshow(
            display_ratio.astype(float),
            color_continuous_scale="Blues",
            labels=dict(x="연월", y="용도", color="비율(%)"),
            aspect="auto", height=380,
        )
        fig_heat.update_layout(
            margin=dict(l=100, r=20, t=40, b=80),
            xaxis=dict(tickangle=-45, tickfont=dict(size=9)),
        )
        st.plotly_chart(fig_heat, use_container_width=True)
    else:
        st.error(f"구성비 데이터 없음: {ratio_err}")

# ─────────────────────────────────────────────
# TAB 3: 원시 데이터
# ─────────────────────────────────────────────
with tab_data:
    st.markdown('<div class="sub-title">📅 월별 공급량 + 기온 현황 (구글시트 원본)</div>', unsafe_allow_html=True)
    if supply_df is not None and supply_err is None:
        # 기간 필터
        disp_supply = supply_df.copy()
        disp_supply["연월"] = pd.to_datetime(disp_supply["연월"])
        disp_supply = disp_supply[
            (disp_supply["연월"].dt.year >= start_year) &
            (disp_supply["연월"].dt.year <= end_year)
        ].copy()
        disp_supply["연월"] = disp_supply["연월"].dt.strftime("%Y-%m")

        # 포맷 설정
        fmt = {"총공급량_GJ": "{:,.1f}"}
        if "총공급량_M3" in disp_supply.columns:
            fmt["총공급량_M3"] = "{:,.0f}"
        if "평균기온" in disp_supply.columns:
            fmt["평균기온"] = "{:.1f}"
        if "평균최저기온" in disp_supply.columns:
            fmt["평균최저기온"] = "{:.1f}"
        if "평균최고기온" in disp_supply.columns:
            fmt["평균최고기온"] = "{:.1f}"

        st.dataframe(
            disp_supply.style.format(fmt),
            use_container_width=True, height=420
        )

        # 공급량 + 기온 이중축 차트
        if "평균기온" in disp_supply.columns:
            st.markdown('<div class="sub-title">📈 월별 공급량 & 평균기온 추이</div>', unsafe_allow_html=True)
            fig_dual = go.Figure()
            fig_dual.add_trace(go.Bar(
                x=disp_supply["연월"], y=disp_supply["총공급량_GJ"],
                name="총공급량 (GJ)", marker_color="#2c5f8a", opacity=0.8,
                yaxis="y1",
                hovertemplate="<b>%{x}</b><br>공급량: %{y:,.0f} GJ<extra></extra>"
            ))
            fig_dual.add_trace(go.Scatter(
                x=disp_supply["연월"], y=disp_supply["평균기온"],
                name="평균기온 (℃)", mode="lines+markers",
                line=dict(color="#e8501a", width=2),
                marker=dict(size=5),
                yaxis="y2",
                hovertemplate="<b>%{x}</b><br>기온: %{y:.1f}℃<extra></extra>"
            ))
            fig_dual.update_layout(
                yaxis=dict(title="총공급량 (GJ)", showgrid=True, gridcolor="#e8e8e8"),
                yaxis2=dict(title="평균기온 (℃)", overlaying="y", side="right",
                            showgrid=False, zeroline=False),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                plot_bgcolor="white", paper_bgcolor="white",
                height=380, margin=dict(l=70, r=70, t=60, b=60),
                xaxis=dict(tickangle=-45, tickfont=dict(size=9)),
            )
            st.plotly_chart(fig_dual, use_container_width=True)
    else:
        st.info("공급량 데이터를 불러오지 못했습니다. 사이드바 또는 메인 탭에서 파일을 업로드해 주세요.")

# ─────────────────────────────────────────────
# TAB 4: 사용 가이드
# ─────────────────────────────────────────────
with tab_guide:
    st.markdown("""
    ## 📖 사용 가이드

    ### 1️⃣ 데이터 구조
    | 항목 | 설명 |
    |------|------|
    | **총공급량** | 천연가스 공급량 + 바이오가스 공급량 (GJ) |
    | **수급량** | 가스공사로부터 수취한 가스량 (2026년 10월 사업계획부터 raw data) |
    | **구성비** | 용도별 공급 비율 (%) — 엑셀 파일 기준 |

    ### 2️⃣ 계산 방식
    ```
    용도별 공급량(GJ) = 총공급량 × 용도별 비율(%)
    용도별 수급량(GJ) = 수급량   × 용도별 비율(%)
    ```

    ### 3️⃣ 데이터 업데이트 방법
    - **구성비**: GitHub에 `자가소모_및_구성비_정리_260625.xlsx` 업로드 후 자동 반영
    - **공급량**: 구글시트를 **링크 공유(뷰어)** 로 설정하면 자동 연동

    ### 4️⃣ 구글시트 공개 설정 방법
    1. 구글시트 → 공유 → 링크가 있는 모든 사용자 → 뷰어
    2. GID 확인: URL의 `gid=0` 부분

    ### 5️⃣ GitHub 설정
    - `GITHUB_RATIO_URL` 상수를 실제 repo 경로로 수정하세요.

    ---
    > 📧 문의: 마케팅본부 마케팅팀
    """)
