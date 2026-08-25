# ──────────────────────────────────────────────
# 피벗 빌더: 정산그룹 빈칸 처리 (눈속임 병합)
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
    row_types = []

    for group, products in [("주택용", HOUSING_PRODUCTS), ("기타", OTHER_PRODUCTS)]:
        for i, p in enumerate(products):
            row = pivot.loc[p].copy() if p in pivot.index else pd.Series(0.0, index=date_cols)
            # 첫 번째 행에만 그룹명 표시, 나머지는 공백 처리하여 병합된 것처럼 연출
            g_label = group if i == 0 else ""
            
            rec = {"정산그룹": g_label, "정산항목": p}
            rec.update(row.to_dict())
            rows_data.append(rec)
            row_types.append("data")

        sub_ps  = [p for p in products if p in pivot.index]
        sub_row = pivot.loc[sub_ps].sum() if sub_ps else pd.Series(0.0, index=date_cols)
        
        rec_sub = {"정산그룹": "", "정산항목": SUBTOTAL_LABEL}
        rec_sub.update(sub_row.to_dict())
        rows_data.append(rec_sub)
        row_types.append("subtotal")

    total_row = pivot.sum()
    rec_tot = {"정산그룹": "", "정산항목": TOTAL_LABEL}
    rec_tot.update(total_row.to_dict())
    rows_data.append(rec_tot)
    row_types.append("total")

    display_df = pd.DataFrame(rows_data)
    return display_df, row_types

# ──────────────────────────────────────────────
# 그라데이션 스타일러 (평면 DataFrame용)
# ──────────────────────────────────────────────
def style_pivot_flat(df: pd.DataFrame, row_types: list,
                     gradient: bool = False,
                     diff_mode: bool = False) -> "pd.io.formats.style.Styler":
    n_rows, n_cols = df.shape
    TEXT_COLS = 2 # 정산그룹, 정산항목 스킵

    bg  = [[""] * n_cols for _ in range(n_rows)]
    txt = [[""] * n_cols for _ in range(n_rows)]

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
    if abs_max == 0: abs_max = 1.0

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
            for j in range(TEXT_COLS, n_cols):
                try:
                    val = float(df.iloc[i, j])
                    if np.isnan(val): continue
                except Exception: continue

                if diff_mode:
                    intensity = min(abs(val) / abs_max, 1.0)
                    alpha = 0.07 + intensity * 0.58
                    if val > 0:
                        bg[i][j]  = f"background-color:rgba(232,80,26,{alpha:.2f});"
                        if intensity > 0.55: txt[i][j] = "color:#6b1500;"
                    elif val < 0:
                        bg[i][j]  = f"background-color:rgba(44,95,138,{alpha:.2f});"
                        if intensity > 0.55: txt[i][j] = "color:#0a1f30;"
                else:
                    intensity = min(val / abs_max, 1.0) if val > 0 else 0.0
                    alpha = 0.05 + intensity * 0.55
                    r = int(44  + (1 - intensity) * 170)
                    g = int(95  + (1 - intensity) * 120)
                    b = int(138 + (1 - intensity) * 90)
                    bg[i][j] = f"background-color:rgba({r},{g},{b},{alpha:.2f});"
                    if intensity > 0.6: txt[i][j] = "color:#fff;"

    def _apply_bg(df_): return pd.DataFrame(bg, index=df_.index, columns=df_.columns)
    def _apply_txt(df_): return pd.DataFrame(txt, index=df_.index, columns=df_.columns)

    # 문자열 열은 중앙 정렬 스타일 추가 (옵션)
    return df.style.apply(_apply_bg, axis=None).apply(_apply_txt, axis=None).set_properties(subset=['정산그룹', '정산항목'], **{'text-align': 'center'})
