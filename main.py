
import json
import re
import zipfile
from io import BytesIO

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# --------------------------------------------------
# 페이지 설정 및 데이터 주소
# --------------------------------------------------
st.set_page_config(
    page_title="전국 고령화 단계구분도",
    page_icon="🗺️",
    layout="wide",
)

POPULATION_URL = (
    "https://raw.githubusercontent.com/yujun0528/borad/"
    "/main/population_ts_yearly_gender.zip"
)
GEOJSON_URL = (
    "https://raw.githubusercontent.com/first2022-cyber/contents/"
    "/main/sigungu_kr.geojson"
)

TARGET_YEAR = 2026
TIMEOUT = 60


# --------------------------------------------------
# 데이터 다운로드 및 전처리
# --------------------------------------------------
@st.cache_data(show_spinner="인구 데이터를 불러오는 중...")
def load_population():
    """압축 CSV에서 2026년 6월 인구 데이터를 읽는다."""
    response = requests.get(POPULATION_URL, timeout=TIMEOUT)
    response.raise_for_status()

    # ZIP 압축 CSV를 pandas로 직접 읽는다.
    df = pd.read_csv(
        BytesIO(response.content),
        compression="zip",
        dtype={"코드": "string"},
        low_memory=False,
    )

    # 연도는 숫자 또는 문자열일 수 있으므로 정규화한다.
    year = pd.to_numeric(df["연도"], errors="coerce")
    df = df.loc[year == TARGET_YEAR].copy()

    if df.empty:
        raise ValueError(f"{TARGET_YEAR}년 인구 데이터가 없습니다.")

    # 코드가 숫자로 읽히더라도 문자열로 유지한다.
    df["코드"] = df["코드"].astype("string").str.strip()

    # 시군구 코드: 읍·면·동 코드의 앞 5자리
    df["시군구코드"] = df["코드"].str[:5]

    # 전체 인구 및 65세 이상 인구에 해당하는 계_ 열만 선택한다.
    total_cols = [
        col for col in df.columns
        if col.startswith("계_")
    ]

    elderly_cols = [
        col for col in total_cols
        if re.fullmatch(r"계_(?:[6-9]\d|100)세(?: 이상)?", col)
    ]

    # 65~99세 및 100세 이상을 포함한다.
    # 원본 열 이름이 '계_100세 이상'인 경우도 처리한다.
    elderly_cols = [
        col for col in total_cols
        if (
            re.fullmatch(r"계_(?:6[5-9]|[7-9]\d)세", col)
            or col == "계_100세 이상"
            or col == "계_100세"
        )
    ]

    if not total_cols:
        raise ValueError("'계_'로 시작하는 인구 열을 찾을 수 없습니다.")

    if not elderly_cols:
        raise ValueError("65세 이상 인구 열을 찾을 수 없습니다.")

    # 숫자형으로 변환해 합산한다. 남_·여_ 열은 집계하지 않는다.
    for col in set(total_cols):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["전체인구"] = df[total_cols].sum(axis=1)
    df["65세이상인구"] = df[elderly_cols].sum(axis=1)

    # 잘못된 코드와 전체 인구가 0인 행은 제외한다.
    df = df.loc[
        df["시군구코드"].str.fullmatch(r"\d{5}", na=False)
        & (df["전체인구"] > 0)
    ].copy()

    # 동별 비율을 평균하지 않고 인구를 먼저 합산한 뒤 비율을 계산한다.
    result = (
        df.groupby("시군구코드", as_index=False)
        .agg(
            전체인구=("전체인구", "sum"),
            65세이상인구=("65세이상인구", "sum"),
        )
    )

    result["고령화율"] = (
        result["65세이상인구"] / result["전체인구"] * 100
    )

    return result


@st.cache_data(show_spinner="시군구 경계 지도를 불러오는 중...")
def load_geojson():
    """시군구 경계 GeoJSON을 내려받아 코드 속성을 정규화한다."""
    response = requests.get(GEOJSON_URL, timeout=TIMEOUT)
    response.raise_for_status()

    geojson = response.json()

    if "features" not in geojson:
        raise ValueError("GeoJSON에 features가 없습니다.")

    for feature in geojson["features"]:
        properties = feature.get("properties", {})
        code = properties.get("코드")

        if code is None:
            properties["코드"] = None
        else:
            # 숫자로 읽힌 코드도 문자열로 통일한다.
            code = str(code).strip()
            if code.endswith(".0"):
                code = code[:-2]
            properties["코드"] = code.zfill(5)

        feature["properties"] = properties

    return geojson


# --------------------------------------------------
# 앱 본문
# --------------------------------------------------
st.title("전국 고령화 단계구분도")
st.caption(
    "2026년 6월 기준 · 시군구별 65세 이상 인구 비율 · 단위: %"
)

try:
    population = load_population()
    geojson = load_geojson()

    # 경계 코드와 인구 데이터 코드를 문자열로 결합한다.
    map_df = population.rename(
        columns={"시군구코드": "코드"}
    ).copy()
    map_df["코드"] = map_df["코드"].astype(str).str.zfill(5)

    # GeoJSON 코드에 실제 존재하는 지역만 지도에 표시한다.
    boundary_codes = {
        feature["properties"].get("코드")
        for feature in geojson["features"]
    }
    boundary_codes.discard(None)

    map_df = map_df[map_df["코드"].isin(boundary_codes)].copy()

    # 지도에 결합할 시군구 이름은 경계 파일의 속성을 사용한다.
    name_by_code = {
        feature["properties"]["코드"]: feature["properties"].get("시군구", "")
        for feature in geojson["features"]
    }
    map_df["시군구명"] = map_df["코드"].map(name_by_code)

    # 고령화율이 없는 경계는 지도에 넣지 않는다.
    map_df = map_df.dropna(subset=["고령화율"])

    if map_df.empty:
        st.error(
            "인구 데이터와 경계 GeoJSON의 시군구 코드가 일치하지 않습니다. "
            "두 파일의 코드 형식을 확인해 주세요."
        )
        st.stop()

    # GeoJSON의 feature id를 코드로 지정하여 코드 기반 결합을 명시한다.
    for feature in geojson["features"]:
        feature["id"] = feature["properties"].get("코드")

    # 지도와 지표
    col1, col2, col3 = st.columns(3)

    total_population = int(map_df["전체인구"].sum())
    elderly_population = int(map_df["65세이상인구"].sum())
    overall_rate = (
        elderly_population / total_population * 100
        if total_population > 0 else 0
    )

    col1.metric("지도 표시 시군구", f"{len(map_df):,}곳")
    col2.metric("65세 이상 인구", f"{elderly_population:,}명")
    col3.metric("전체 고령화율", f"{overall_rate:.2f}%")

    # 배경 타일 없는 Plotly 단계구분도
    fig = px.choropleth(
        map_df,
        geojson=geojson,
        locations="코드",
        featureidkey="properties.코드",
        color="고령화율",
        hover_name="시군구명",
        hover_data={
            "코드": False,
            "고령화율": ":.2f",
            "전체인구": ":,",
            "65세이상인구": ":,",
        },
        color_continuous_scale="YlOrRd",
        labels={
            "고령화율": "고령화율 (%)",
            "전체인구": "전체 인구",
            "65세이상인구": "65세 이상 인구",
        },
        title="시군구별 65세 이상 인구 비율",
    )

    fig.update_traces(
        marker_line_color="white",
        marker_line_width=0.35,
        hovertemplate=(
            "<b>%{hovertext}</b><br>"
            "고령화율: %{z:.2f}%<br>"
            "<extra></extra>"
        ),
    )

    # 타일 지도를 추가하지 않고 GeoJSON 경계만 표시한다.
    fig.update_geos(
        fitbounds="locations",
        visible=False,
        showcountries=False,
        showcoastlines=False,
        showland=False,
        showframe=False,
    )

    fig.update_layout(
        height=780,
        margin=dict(l=0, r=0, t=60, b=0),
        coloraxis_colorbar=dict(
            title="고령화율 (%)",
            ticksuffix="%",
        ),
    )

    st.plotly_chart(fig, use_container_width=True)

    # 코드 기준 데이터 표
    with st.expander("시군구별 상세 데이터 보기"):
        table = map_df[
            ["코드", "시군구명", "전체인구", "65세이상인구", "고령화율"]
        ].copy()
        table = table.rename(
            columns={
                "코드": "시군구 코드",
                "시군구명": "시군구",
                "전체인구": "전체 인구",
                "65세이상인구": "65세 이상 인구",
                "고령화율": "고령화율 (%)",
            }
        )
        table = table.sort_values("고령화율 (%)", ascending=False)
        st.dataframe(table, use_container_width=True, hide_index=True)

    st.caption(
        "자료: 제공된 읍·면·동 인구 CSV 및 시군구 경계 GeoJSON. "
        "고령화율은 시군구 내 65세 이상 인구 합계를 전체 인구 합계로 나누어 계산합니다."
    )

except requests.RequestException as exc:
    st.error(f"데이터 다운로드에 실패했습니다: {exc}")
except (ValueError, KeyError, zipfile.BadZipFile) as exc:
    st.error(f"데이터 처리 중 오류가 발생했습니다: {exc}")
except Exception as exc:
    st.error(f"앱 실행 중 오류가 발생했습니다: {exc}")
