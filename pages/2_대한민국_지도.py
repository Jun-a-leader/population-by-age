import math
import re

import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from folium.plugins import MarkerCluster
from geopy.geocoders import Nominatim
from streamlit_folium import st_folium


st.set_page_config(page_title="대한민국 지도와 지역 탐색", layout="wide")

DATA_PATH = "202605_202605_연령별인구현황_월간.csv"

KOREA_CENTER = [36.5, 127.8]

# 대략적인 중심 좌표(지오코딩 실패 시 fallback)
FALLBACK_CENTERS = {
    "서울특별시": [37.5665, 126.9780],
    "부산광역시": [35.1796, 129.0756],
    "대구광역시": [35.8714, 128.6014],
    "인천광역시": [37.4563, 126.7052],
    "광주광역시": [35.1595, 126.8526],
    "대전광역시": [36.3504, 127.3845],
    "울산광역시": [35.5384, 129.3114],
    "세종특별자치시": [36.4800, 127.2890],
    "경기도": [37.4138, 127.5183],
    "강원특별자치도": [37.8228, 128.1555],
    "충청북도": [36.8, 127.7],
    "충청남도": [36.5, 126.8],
    "전라북도": [35.8, 127.1],
    "전북특별자치도": [35.8, 127.1],
    "전라남도": [34.9, 126.9],
    "경상북도": [36.5, 128.7],
    "경상남도": [35.2, 128.2],
    "제주특별자치도": [33.38, 126.55],
}


@st.cache_data(show_spinner=False)
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="cp949", low_memory=False)
    df.columns = [str(c).strip() for c in df.columns]

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

    parsed = df["행정구역"].astype(str).str.extract(r"^(.*?)\s*\((\d+)\)$")
    df["지역명"] = parsed[0].fillna(df["행정구역"]).str.replace(r"\s+", " ", regex=True).str.strip()
    df["지역코드"] = parsed[1]
    df["레벨"] = df["지역명"].apply(lambda x: len(x.split(" ")) if isinstance(x, str) and x.strip() else 0)
    df["시도"] = df["지역명"].apply(lambda x: x.split(" ")[0] if isinstance(x, str) and x else None)
    df["시군구"] = df["지역명"].apply(lambda x: x.split(" ")[1] if isinstance(x, str) and len(x.split(" ")) >= 2 else None)
    df["읍면동"] = df["지역명"].apply(lambda x: " ".join(x.split(" ")[2:]) if isinstance(x, str) and len(x.split(" ")) >= 3 else None)

    age_cols = []
    for age in range(100):
        c = f"2026년05월_계_{age}세"
        if c in df.columns:
            age_cols.append(c)
    df.attrs["age_cols"] = age_cols
    return df


def series_for_row(row: pd.Series, age_cols: list[str]) -> pd.Series:
    s = row[age_cols].copy()
    s.index = [int(re.search(r"_(\d+)세", c).group(1)) for c in age_cols]
    return s.fillna(0).astype(float).sort_index()


@st.cache_data(show_spinner=False)
def geocode_region(name: str):
    geolocator = Nominatim(user_agent="streamlit-korea-age-app")
    try:
        loc = geolocator.geocode(name, language="ko", timeout=10)
        if loc:
            return [loc.latitude, loc.longitude]
    except Exception:
        pass

    # fallback: 시도명만 보고 대략 위치 부여
    sido = name.split(" ")[0]
    return FALLBACK_CENTERS.get(sido, KOREA_CENTER)


df = load_data(DATA_PATH)
age_cols = df.attrs["age_cols"]

st.markdown(
    """
    <div style="padding: 0.5rem 0 1rem 0;">
        <h1 style="margin-bottom: 0.2rem;">대한민국 지도 기반 지역 탐색</h1>
        <p style="margin-top: 0; color: #666;">검색, 다중 선택, 지도 이동/확대/축소, 연령 최대·최소값 요약을 제공합니다.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

regions = df[df["레벨"] >= 3][["지역명", "시도", "시군구", "읍면동", "지역코드"]].drop_duplicates()
all_options = regions["지역명"].tolist()

search = st.text_input("지역 검색", placeholder="예: 종로구, 한솔동, 서귀포시 ...")
if search:
    filtered_options = [x for x in all_options if search in x]
else:
    filtered_options = all_options

st.caption(f"검색 결과: {len(filtered_options):,}개")

default_n = min(8, len(filtered_options))
selected_regions = st.multiselect("비교할 지역 선택", filtered_options, default=filtered_options[:default_n])

left, right = st.columns([1.2, 1])

with left:
    m = folium.Map(location=KOREA_CENTER, zoom_start=7, tiles="OpenStreetMap", control_scale=True)
    marker_cluster = MarkerCluster().add_to(m)

    for region_name in selected_regions:
        row = df[df["지역명"] == region_name]
        if row.empty:
            continue
        row = row.iloc[0]
        latlng = geocode_region(region_name)
        popup_text = f"{region_name}<br>총인구: {int(row[age_cols].fillna(0).sum()):,}명"
        folium.Marker(
            location=latlng,
            popup=folium.Popup(popup_text, max_width=300),
            tooltip=region_name,
        ).add_to(marker_cluster)

    st_folium(m, height=650, use_container_width=True)

with right:
    if not selected_regions:
        st.info("지도에 표시할 지역을 하나 이상 선택하세요.")
    else:
        stats_rows = []
        age_totals = None

        for region_name in selected_regions:
            row = df[df["지역명"] == region_name]
            if row.empty:
                continue
            row = row.iloc[0]
            series = series_for_row(row, age_cols)

            if age_totals is None:
                age_totals = series.copy()
            else:
                age_totals = age_totals.add(series, fill_value=0)

            stats_rows.append(
                {
                    "지역명": region_name,
                    "총인구": int(series.sum()),
                    "최다 연령": f"{int(series.idxmax())}세",
                    "최다 인구": int(series.max()),
                    "최소 연령": f"{int(series.idxmin())}세",
                    "최소 인구": int(series.min()),
                }
            )

        stats_df = pd.DataFrame(stats_rows).sort_values("총인구", ascending=False)
        total_selected = int(stats_df["총인구"].sum()) if not stats_df.empty else 0
        most_age = int(age_totals.idxmax()) if age_totals is not None else 0
        most_age_val = int(age_totals.max()) if age_totals is not None else 0
        least_age = int(age_totals.idxmin()) if age_totals is not None else 0
        least_age_val = int(age_totals.min()) if age_totals is not None else 0

        c1, c2 = st.columns(2)
        c1.metric("선택 지역 총인구 합계", f"{total_selected:,}명")
        c2.metric("선택 지역 수", f"{len(stats_df):,}개")

        c3, c4 = st.columns(2)
        c3.metric("선택 지역에서 가장 많은 연령", f"{most_age}세")
        c4.metric("선택 지역에서 가장 적은 연령", f"{least_age}세")

        st.write("### 선택 지역별 요약")
        st.dataframe(stats_df, use_container_width=True, hide_index=True)

        if age_totals is not None:
            fig = go.Figure(
                go.Bar(
                    x=age_totals.index,
                    y=age_totals.values,
                    hovertemplate="연령 %{x}세<br>합계 %{y:,.0f}명<extra></extra>",
                )
            )
            fig.update_layout(
                title="선택한 지역들의 연령 합계",
                xaxis_title="연령",
                yaxis_title="인구수",
                template="plotly_white",
                height=380,
                margin=dict(l=20, r=20, t=50, b=20),
            )
            st.plotly_chart(fig, use_container_width=True)

        with st.expander("검색 결과만 따로 보기", expanded=False):
            st.dataframe(
                regions[regions["지역명"].isin(filtered_options)][["지역명", "시도", "시군구", "읍면동"]],
                use_container_width=True,
                hide_index=True,
            )
