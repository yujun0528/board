# main.py
# 동네별 인구 피라미드
# 최신 연도 인구 데이터로 지표 카드와 피라미드를 표시합니다.

import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ==================================================
# 1. 페이지 설정 및 따뜻한 색상 테마
# ==================================================
st.set_page_config(
    page_title="동네별 인구 피라미드",
    page_icon="🏡",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp {
        background-color: #FFF9F2;
    }
    h1, h2, h3 {
        color: #70452F;
    }
    div[data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #F0DDCC;
        border-radius: 12px;
        padding: 14px;
    }
    .warning-note {
        background-color: #FFF0E8;
        border: 1px solid #E8A080;
        border-radius: 10px;
        padding: 10px 14px;
        color: #963D20;
        font-weight: 600;
        margin-bottom: 12px;
    }
    .summary-note {
        background-color: #FFFFFF;
        border-left: 5px solid #D9826B;
        border-radius: 8px;
        padding: 14px 18px;
        color: #70452F;
        margin-top: 12px;
        margin-bottom: 20px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ==================================================
# 2. 데이터 주소 및 나이 목록
# ==================================================
DATA_URL = (
    "https://raw.githubusercontent.com/yujun0528/board/"
    "main/population_ts_yearly_gender.zip"
)

# 0세부터 100세 이상까지 순서대로 만듭니다.
AGE_LABELS = [f"{age}세" for age in range(101)]
AGE_LABELS[-1] = "100세 이상"


# ==================================================
# 3. 데이터 불러오기
# ==================================================
@st.cache_data(show_spinner=False)
def load_data(url):
    """ZIP 파일 안의 CSV를 읽고 열의 자료형을 정리합니다."""

    data = pd.read_csv(url, compression="zip", low_memory=False)
    data.columns = data.columns.astype(str).str.strip()

    # 반드시 필요한 기본 열이 있는지 확인합니다.
    required_columns = ["연도", "시도", "시군구", "동"]
    missing_columns = [
        col for col in required_columns if col not in data.columns
    ]

    if missing_columns:
        raise ValueError(
            f"필수 열이 없습니다: {', '.join(missing_columns)}"
        )

    # 연도를 숫자로 변환하고 잘못된 행은 제외합니다.
    data["연도"] = pd.to_numeric(data["연도"], errors="coerce")
    data = data.dropna(subset=["연도"]).copy()
    data["연도"] = data["연도"].astype(int)

    # 행정구역 이름은 문자열로 통일합니다.
    for col in ["시도", "시군구", "동"]:
        data[col] = data[col].fillna("").astype(str).str.strip()

    # 남_0세, 여_0세, 남_100세 이상 등의 열을 찾습니다.
    age_pattern = re.compile(r"^(남|여)_(\d+세(?:\s*이상)?)$")
    age_columns = [
        col for col in data.columns
        if age_pattern.fullmatch(col)
    ]

    if not age_columns:
        raise ValueError(
            "'남_0세', '여_0세' 형식의 인구 열을 찾지 못했습니다."
        )

    # 인구 열을 숫자로 변환하고 빈 값은 0명으로 처리합니다.
    for col in age_columns:
        data[col] = pd.to_numeric(
            data[col].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        ).fillna(0)

    return data


def get_age_column(gender, age):
    """성별과 나이를 실제 데이터 열 이름으로 바꿉니다."""
    return f"{gender}_{age}"


def make_age_values(rows, gender):
    """선택한 지역의 나이별 인구를 0세부터 순서대로 반환합니다."""

    # 동일 지역에 여러 행이 있으면 나이별로 합산합니다.
    values_by_column = rows.sum(numeric_only=True)
    result = []

    for age in AGE_LABELS:
        column = get_age_column(gender, age)
        value = values_by_column.get(column, 0)
        result.append(int(value))

    return result


# ==================================================
# 4. 평균연령 계산
# ==================================================
def calculate_average_age(male_values, female_values):
    """남녀 인구를 합산한 가중평균 연령을 계산합니다."""

    total_by_age = [
        male + female
        for male, female in zip(male_values, female_values)
    ]
    total_population = sum(total_by_age)

    if total_population == 0:
        return None

    # 100세 이상은 계산상 100세로 근사합니다.
    weighted_age_sum = sum(
        age * population
        for age, population in enumerate(total_by_age)
    )

    return weighted_age_sum / total_population


# ==================================================
# 5. 앱 제목과 설명
# ==================================================
st.title("🏡 동네별 인구 피라미드")

st.markdown(
    """
    우리 동네에는 연령대별로 몇 명이 살고 있을까요?

    시도 → 시군구 → 읍·면·동을 차례로 선택하면
    최신 연도의 인구 지표와 남녀 인구 분포를 확인할 수 있습니다.
    """
)


# ==================================================
# 6. 데이터 읽기 및 최신 연도 선택
# ==================================================
with st.spinner("전국 인구 데이터를 불러오는 중입니다..."):
    try:
        population = load_data(DATA_URL)
    except Exception as error:
        st.error(
            "데이터를 불러오지 못했습니다. 인터넷 연결과 "
            "데이터 주소를 확인해 주세요."
        )
        with st.expander("오류 상세 내용"):
            st.code(str(error))
        st.stop()

if population.empty:
    st.error("불러온 데이터가 비어 있습니다.")
    st.stop()

# 실제 데이터에 포함된 가장 최신 연도를 선택합니다.
latest_year = int(population["연도"].max())
df = population.loc[population["연도"] == latest_year].copy()

st.caption(f"📅 데이터 기준 연도: {latest_year}년")


# ==================================================
# 7. 시도 → 시군구 → 동 드롭다운
# ==================================================
st.subheader("📍 우리 동네 선택")

sido_col, sigungu_col, dong_col = st.columns(3)

# 첫 번째 드롭다운: 시도
sido_options = sorted(
    value for value in df["시도"].unique() if value
)

if not sido_options:
    st.error("선택할 수 있는 시도 데이터가 없습니다.")
    st.stop()

with sido_col:
    selected_sido = st.selectbox(
        "① 시도",
        options=sido_options,
        key="selected_sido",
    )

# 두 번째 드롭다운: 선택한 시도의 시군구
sido_df = df.loc[df["시도"] == selected_sido]
sigungu_options = sorted(
    value for value in sido_df["시군구"].unique() if value
)

with sigungu_col:
    selected_sigungu = st.selectbox(
        "② 시군구",
        options=sigungu_options,
        key="selected_sigungu",
        disabled=not sigungu_options,
    )

# 세 번째 드롭다운: 선택한 시군구의 읍·면·동
sigungu_df = sido_df.loc[
    sido_df["시군구"] == selected_sigungu
]
dong_options = sorted(
    value for value in sigungu_df["동"].unique() if value
)

with dong_col:
    selected_dong = st.selectbox(
        "③ 읍·면·동",
        options=dong_options,
        key="selected_dong",
        disabled=not dong_options,
    )

if not sigungu_options or not dong_options:
    st.warning("선택한 행정구역에 표시할 데이터가 없습니다.")
    st.stop()


# ==================================================
# 8. 선택한 동네의 남녀 인구 계산
# ==================================================
selected_rows = df.loc[
    (df["시도"] == selected_sido)
    & (df["시군구"] == selected_sigungu)
    & (df["동"] == selected_dong)
]

if selected_rows.empty:
    st.warning("선택한 동네의 인구 데이터가 없습니다.")
    st.stop()

male_values = make_age_values(selected_rows, "남")
female_values = make_age_values(selected_rows, "여")

# 남녀 인구를 합산합니다.
total_by_age = [
    male + female
    for male, female in zip(male_values, female_values)
]

total_male = sum(male_values)
total_female = sum(female_values)
total_population = total_male + total_female

# 65세 이상 인구는 65세부터 100세 이상까지 합산합니다.
elderly_population = sum(total_by_age[65:])

if total_population > 0:
    aging_rate = elderly_population / total_population * 100
else:
    aging_rate = 0.0

average_age = calculate_average_age(male_values, female_values)


# ==================================================
# 9. 지표 카드 3개
# ==================================================
st.divider()

st.subheader(
    f"📊 {selected_sido} {selected_sigungu} {selected_dong}"
)

metric1, metric2, metric3 = st.columns(3)

with metric1:
    st.metric(
        label="👥 총인구",
        value=f"{total_population:,}명",
    )

with metric2:
    average_age_text = (
        f"{average_age:.1f}세"
        if average_age is not None
        else "계산 불가"
    )
    st.metric(
        label="🎂 평균연령",
        value=average_age_text,
    )

with metric3:
    st.metric(
        label="🌳 고령화율 (65세 이상)",
        value=f"{aging_rate:.1f}%",
    )

    # 고령화율이 20%를 초과할 때 주의 문구를 표시합니다.
    if aging_rate > 20:
        st.markdown(
            '<div class="warning-note">'
            '⚠️ 주의: 고령화율이 20%를 초과합니다.'
            '</div>',
            unsafe_allow_html=True,
        )


# ==================================================
# 10. 인구 피라미드
# ==================================================
st.subheader("인구 피라미드")

fig = go.Figure()

# 남성은 음수로 바꿔 왼쪽에 표시합니다.
fig.add_trace(
    go.Bar(
        name="남성",
        y=AGE_LABELS,
        x=[-value for value in male_values],
        orientation="h",
        marker_color="#D9826B",
        customdata=male_values,
        hovertemplate=(
            "나이: %{y}<br>"
            "남성 인구: %{customdata:,}명"
            "<extra></extra>"
        ),
    )
)

# 여성은 양수 그대로 오른쪽에 표시합니다.
fig.add_trace(
    go.Bar(
        name="여성",
        y=AGE_LABELS,
        x=female_values,
        orientation="h",
        marker_color="#E8B65C",
        hovertemplate=(
            "나이: %{y}<br>"
            "여성 인구: %{x:,}명"
            "<extra></extra>"
        ),
    )
)

# 좌우 축 범위를 같게 설정합니다.
max_population = max(male_values + female_values + [1])
axis_limit = max_population * 1.1

fig.update_layout(
    template="plotly_white",
    barmode="overlay",
    title={
        "text": f"{selected_dong} 연령별 남녀 인구 ({latest_year}년)",
        "x": 0.5,
        "xanchor": "center",
        "font": {"size": 20, "color": "#70452F"},
    },
    height=1000,
    margin={"l": 85, "r": 45, "t": 90, "b": 80},
    paper_bgcolor="#FFF9F2",
    plot_bgcolor="#FFFDF9",
    font={"family": "sans-serif", "color": "#5C4638"},
    bargap=0.12,
    hovermode="y unified",
    legend={
        "orientation": "h",
        "yanchor": "bottom",
        "y": 1.02,
        "xanchor": "center",
        "x": 0.5,
    },
)

# 세로축의 나이 순서를 명시적으로 고정합니다.
# categoryarray를 역순으로 지정하여 0세가 아래쪽,
# 100세 이상이 위쪽에 오도록 합니다.
fig.update_yaxes(
    title_text="나이",
    type="category",
    categoryorder="array",
    categoryarray=AGE_LABELS[::-1],
    showgrid=False,
    tickfont={"size": 10},
)

# 남성의 음수 눈금도 절댓값으로 표시합니다.
tick_values = np.linspace(
    -axis_limit, axis_limit, 9
).round().astype(int)

fig.update_xaxes(
    title_text="인구 (명)",
    range=[-axis_limit, axis_limit],
    tickmode="array",
    tickvals=tick_values.tolist(),
    ticktext=[f"{abs(value):,}" for value in tick_values],
    zeroline=True,
    zerolinecolor="#BDAA99",
    zerolinewidth=1.5,
    gridcolor="#F0E5DA",
)

st.plotly_chart(fig, use_container_width=True)

st.caption(
    "나이 축 확인: 맨 아래 0세 · 맨 위 100세 이상 | "
    "남성은 왼쪽 · 여성은 오른쪽"
)


# ==================================================
# 11. 동네 인구 구성 한 줄 설명
# ==================================================
st.subheader("💬 우리 동네 한 줄 해석")

# 아이는 0~14세, 어르신은 65세 이상으로 정의합니다.
child_population = sum(total_by_age[:15])

if total_population == 0:
    summary = (
        "인구 자료가 없어 동네의 연령 구성을 판단하기 어렵습니다."
    )
else:
    child_rate = child_population / total_population * 100
    elderly_share = elderly_population / total_population * 100

    if child_rate > elderly_share:
        summary = (
            f"이 동네는 0~14세 인구 비율({child_rate:.1f}%)이 "
            f"65세 이상 비율({elderly_share:.1f}%)보다 높아, "
            "상대적으로 아이의 비중이 큰 편입니다."
        )
    elif elderly_share > child_rate:
        summary = (
            f"이 동네는 65세 이상 인구 비율({elderly_share:.1f}%)이 "
            f"0~14세 비율({child_rate:.1f}%)보다 높아, "
            "상대적으로 어르신의 비중이 큰 편입니다."
        )
    else:
        summary = (
            f"이 동네는 0~14세와 65세 이상 인구 비율이 "
            f"각각 {child_rate:.1f}%로 같습니다."
        )

st.markdown(
    f'<div class="summary-note">{summary}</div>',
    unsafe_allow_html=True,
)


# ==================================================
# 12. 나이별 인구 표
# ==================================================
with st.expander("📋 나이별 인구 숫자 확인"):
    result_df = pd.DataFrame(
        {
            "나이": AGE_LABELS,
            "남성 인구": male_values,
            "여성 인구": female_values,
            "전체 인구": total_by_age,
        }
    )

    st.dataframe(
        result_df.style.format(
            {
                "남성 인구": "{:,}",
                "여성 인구": "{:,}",
                "전체 인구": "{:,}",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

st.markdown(
    """
    ---
    <div style="text-align:center; color:#9B8371; font-size:13px;">
        동네별 인구 피라미드 · 최신 연도 기준
    </div>
    """,
    unsafe_allow_html=True,
)
