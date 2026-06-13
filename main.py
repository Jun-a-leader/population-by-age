import re
from functools import lru_cache

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(page_title="2026년 5월 기준 연령별 인구", layout="wide")

DATA_PATH = "202605_202605_연령별인구현황_월간.csv"


@st.cache_data(show_spinner=False)
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="cp949", low_memory=False)
    df.columns = [str(c).strip() for c in df.columns]

    # 숫자형 컬럼 변환
    for col in df.columns:
        if col == "행정구역":
            continue
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.strip()
            .replace({"nan": None, "None": None, "": None})
        )
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 지역명 파싱
    parsed = df["행정구역"].astype(str).str.extract(r"^(.*?)\s*\((\d+)\)$")
    df["지역명"] = parsed[0].fillna(df["행정구역"]).str.replace(r"\s+", " ", regex=True).str.strip()
    df["지역코드"] = parsed[1]

    def level_of(name: str) -> int:
        if not isinstance(name, str) or not name.strip():
            return 0
        return len(name.split(" "))

    df["레벨"] = df["지역명"].apply(level_of)
    df["시도"] = df["지역명"].apply(lambda x: x.split(" ")[0] if isinstance(x, str) and x else None)
    df["시군구"] = df["지역명"].apply(lambda x: x.split(" ")[1] if isinstance(x, str) and len(x.split(" ")) >= 2 else None)
    df["읍면동"] = df["지역명"].apply(lambda x: " ".join(x.split(" ")[2:]) if isinstance(x, str) and len(x.split(" ")) >= 3 else None)

    age_cols = []
    for age in range(100):
        candidates = [f"2026년05월_계_{age}세", f"2026년05월_계_{age}세 "]
        for c in candidates:
            if c in df.columns:
                age_cols.append(c)
                break
    df.attrs["age_cols"] = age_cols
    return df


def age_series_for_row(row: pd.Series, age_cols: list[str]) -> pd.Series:
    s = row[age_cols].copy()
    s.index = [int(re.search(r"_(\d+)세", c).group(1)) for c in age_cols]
    s = s.fillna(0).astype(float)
    return s.sort_index()


def choose_exact_region(df: pd.DataFrame, sido: str, sigungu: str | None, eup: str | None) -> pd.Series | None:
    region = sido
    if sigungu:
        region += f" {sigungu}"
    if eup:
        region += f" {eup}"

    exact = df[df["지역명"] == region]
    if not exact.empty:
        return exact.iloc[0]

    # 가장 구체적인 매칭
    candidates = df[df["지역명"].str.startswith(region, na=False)]
    if not candidates.empty:
        return candidates.sort_values("레벨", ascending=False).iloc[0]
    return None


df = load_data(DATA_PATH)
age_cols = df.attrs["age_cols"]

st.markdown(
    """
    <div style="padding: 0.5rem 0 1rem 0;">
        <h1 style="margin-bottom: 0.2rem;">2026년 5월 기준</h1>
        <p style="margin-top: 0; color: #666;">지역을 선택하면 0세~99세 연령별 인구를 인터랙티브 그래프로 확인할 수 있습니다.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.sidebar.header("지역 선택")
sido_options = sorted(df.loc[df["레벨"] == 1, "시도"].dropna().unique().tolist())
sido = st.sidebar.selectbox("##도/시", sido_options)

sigungu_df = df[(df["시도"] == sido) & (df["레벨"] >= 2)]
sigungu_options = sorted(sigungu_df["시군구"].dropna().unique().tolist())
sigungu = st.sidebar.selectbox("##시/군/구", sigungu_options)

eup_df = df[(df["시도"] == sido) & (df["시군구"] == sigungu) & (df["레벨"] >= 3)]
eup_options = sorted(eup_df["읍면동"].dropna().unique().tolist())
eup = st.sidebar.selectbox("##동/읍/면", eup_options)

selected = choose_exact_region(df, sido, sigungu, eup)

if selected is None:
    st.error("선택한 지역의 데이터를 찾지 못했습니다. 다른 지역을 선택해 주세요.")
    st.stop()

series = age_series_for_row(selected, age_cols)
total = int(series.sum())
peak_age = int(series.idxmax())
peak_val = int(series.max())
min_age = int(series.idxmin())
min_val = int(series.min())

col1, col2, col3, col4 = st.columns(4)
col1.metric("선택 지역", selected["지역명"])
col2.metric("총인구", f"{total:,}명")
col3.metric("가장 많은 연령", f"{peak_age}세")
col4.metric("가장 적은 연령", f"{min_age}세")

fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=series.index,
        y=series.values,
        mode="lines+markers",
        line=dict(width=3),
        marker=dict(size=7),
        hovertemplate="연령 %{x}세<br>인구 %{y:,.0f}명<extra></extra>",
        name="연령별 인구",
    )
)
fig.update_layout(
    title=f"{selected['지역명']} 연령별 인구 분포",
    xaxis_title="연령",
    yaxis_title="인구수",
    template="plotly_white",
    height=560,
    margin=dict(l=20, r=20, t=60, b=20),
)
st.plotly_chart(fig, use_container_width=True)

with st.expander("세부 정보 보기", expanded=False):
    detail_col1, detail_col2 = st.columns(2)
    detail_col1.write(f"**가장 많은 연령:** {peak_age}세 ({peak_val:,}명)")
    detail_col1.write(f"**가장 적은 연령:** {min_age}세 ({min_val:,}명)")
    detail_col2.write("**상위 10개 연령**")
    top10 = series.sort_values(ascending=False).head(10).reset_index()
    top10.columns = ["연령", "인구수"]
    st.dataframe(top10, use_container_width=True, hide_index=True)
    st.write("**0세~99세 전체 표**")
    all_df = pd.DataFrame({"연령": series.index, "인구수": series.values})
    st.dataframe(all_df, use_container_width=True, height=420, hide_index=True)
