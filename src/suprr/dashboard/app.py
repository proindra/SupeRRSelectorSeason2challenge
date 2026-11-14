from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit.runtime.uploaded_file_manager import UploadedFile

from suprr.config import load_config
from suprr.ingestion.loader import InputFilesError
from suprr.pipeline import run_pipeline
from suprr.schemas import SOURCE_FILES

PROJECT_DIR = Path(__file__).resolve().parents[3]

st.set_page_config(
    page_title="Batman Plays Under Pressure",
    page_icon="🏏",
    layout="wide",
    initial_sidebar_state="expanded",
)

px.defaults.template = "plotly_dark"
px.defaults.color_discrete_sequence = ["#E91E8C", "#17479E", "#FF4FA3", "#5679BC", "#A9B5CC"]
px.defaults.color_continuous_scale = ["#17479E", "#E91E8C"]

st.markdown(
    """
    <style>
    :root {
        --navy: #0B1020;
        --panel: #151D32;
        --panel-soft: #1B2640;
        --pink: #E91E8C;
        --pink-bright: #FF4FA3;
        --royal-blue: #17479E;
        --muted: #A9B5CC;
        --text: #F8FAFC;
        --line: #2B3855;
    }
    .stApp {
        background:
            radial-gradient(ellipse at 10% 0%, rgba(23, 71, 158, .22), transparent 40%),
            radial-gradient(ellipse at 88% 0%, rgba(233, 30, 140, .15), transparent 34%),
            var(--navy);
        color: var(--text);
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0B1020, #10182B 70%, #0B1020);
        border-right: 1px solid var(--line);
    }
    [data-testid="stSidebar"] [role="radiogroup"] { gap: .35rem; }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        padding: .55rem .7rem;
        border: 1px solid transparent;
        border-radius: 10px;
        transition: background .18s ease, border-color .18s ease, transform .18s ease;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {
        background: rgba(23, 71, 158, .18);
        border-color: rgba(23, 71, 158, .38);
        transform: translateX(2px);
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
        background: linear-gradient(100deg, rgba(23, 71, 158, .42), rgba(233, 30, 140, .13));
        border-color: rgba(23, 71, 158, .62);
        box-shadow: inset 3px 0 var(--pink);
    }
    h1, h2, h3 { letter-spacing: -0.025em; color: var(--text); }
    h1 { font-weight: 750; }
    h2, h3 { font-weight: 650; }
    p, label, [data-testid="stMarkdownContainer"] { color: var(--text); }
    [data-testid="stCaptionContainer"] p { color: var(--muted); }
    .hero {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1.5rem;
        padding: 1.35rem 1.5rem;
        margin: 0.3rem 0 1.35rem;
        border: 1px solid rgba(43, 56, 85, .95);
        border-radius: 18px;
        background:
            radial-gradient(ellipse at 0% 50%, rgba(233, 30, 140, .19), transparent 43%),
            linear-gradient(
                115deg,
                rgba(23, 71, 158, .28),
                rgba(21, 29, 50, .98) 54%,
                rgba(233, 30, 140, .10)
            );
        box-shadow: 0 14px 44px rgba(4, 8, 18, .24);
    }
    .hero-title {
        margin: .25rem 0 .35rem;
        font-size: clamp(1.7rem, 3vw, 2.45rem);
        line-height: 1.12;
    }
    .hero-copy { max-width: 46rem; margin: 0; color: var(--muted); line-height: 1.55; }
    .eyebrow {
        color: var(--pink-bright);
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: .14em;
        text-transform: uppercase;
    }
    .theme-note {
        margin-top: .3rem;
        color: var(--muted);
        font-size: .72rem;
        letter-spacing: .04em;
    }
    .status-badge {
        flex: 0 0 auto;
        padding: .48rem .75rem;
        border: 1px solid rgba(169, 181, 204, .25);
        border-radius: 999px;
        background: rgba(21, 29, 50, .76);
        color: var(--muted);
        font-size: .68rem;
        font-weight: 700;
        letter-spacing: .1em;
        white-space: nowrap;
    }
    [data-testid="stMetric"] {
        background: linear-gradient(145deg, var(--panel-soft), var(--panel));
        border: 1px solid rgba(43, 56, 85, .88);
        border-radius: 14px;
        padding: 18px 20px;
        box-shadow: 0 0 0 1px rgba(233, 30, 140, .025), 0 8px 26px rgba(3, 7, 17, .18);
    }
    [data-testid="stMetricLabel"] {
        color: var(--muted);
        font-size: .84rem;
        line-height: 1.25;
    }
    [data-testid="stMetricValue"] {
        color: var(--text);
        font-size: clamp(1.25rem, 2.2vw, 1.75rem);
        line-height: 1.15;
    }
    .st-key-overview-kpi-band {
        margin: .4rem 0 1rem;
        padding: .45rem .25rem;
        border: 1px solid var(--line);
        border-radius: 14px;
        background: rgba(21, 29, 50, .55);
    }
    .st-key-overview-kpi-band [data-testid="stMetric"] {
        padding: .3rem .65rem;
        border: 0;
        border-radius: 0;
        background: transparent;
        box-shadow: none;
    }
    .st-key-featured-player-cards {
        margin: 1rem 0;
        padding: .8rem 1.1rem;
        border: 1px solid rgba(43, 56, 85, .95);
        border-radius: 16px;
        background:
            linear-gradient(105deg, rgba(233, 30, 140, .1), rgba(23, 71, 158, .15) 70%),
            var(--panel);
        box-shadow: 0 8px 26px rgba(3, 7, 17, .18), 0 0 22px rgba(233, 30, 140, .06);
    }
    [data-testid="stExpander"] {
        border: 1px solid rgba(43, 56, 85, .92);
        border-radius: 12px;
        background: rgba(21, 29, 50, .7);
    }
    [data-testid="stDataFrame"] {
        border: 1px solid var(--line);
        border-radius: 12px;
        overflow: hidden;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--line) !important;
        background: rgba(21, 29, 50, .58);
    }
    div.stButton > button[kind="primary"] {
        background: linear-gradient(100deg, var(--pink), var(--pink-bright));
        border: 0;
        color: white;
        font-weight: 700;
        border-radius: 9px;
        box-shadow: 0 5px 18px rgba(233, 30, 140, .2);
    }
    div.stButton > button[kind="primary"]:hover {
        border: 1px solid var(--pink-bright);
        box-shadow: 0 7px 22px rgba(233, 30, 140, .3);
    }
    [data-testid="stDownloadButton"] button {
        border-color: var(--royal-blue);
        color: var(--text);
        border-radius: 9px;
    }
    [data-testid="stDownloadButton"] button:hover {
        border-color: var(--pink);
        color: var(--pink-bright);
    }
    [data-baseweb="select"] > div, [data-baseweb="input"] > div {
        background-color: var(--panel);
        border-color: var(--line);
    }
    hr { border-color: var(--line); }
    .subtle { color: var(--muted); }
    @media (max-width: 1200px) {
        .hero { align-items: flex-start; flex-direction: column; padding: 1.1rem; }
        .status-badge { margin-top: .2rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def _read_json(path: str, modified: float) -> dict:
    del modified
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


@st.cache_data(show_spinner=False)
def _read_csv(path: str, modified: float) -> pd.DataFrame:
    del modified
    return pd.read_csv(
        path,
        dtype={
            "player_id": "string",
            "striker_id": "string",
            "bowler_id": "string",
            "match_id": "string",
        },
    )


@st.cache_data(show_spinner=False)
def _read_parquet(path: str, modified: float) -> pd.DataFrame:
    del modified
    return pd.read_parquet(path)


def _existing_json(path: Path) -> dict | None:
    return _read_json(str(path), path.stat().st_mtime) if path.is_file() else None


def _existing_csv(path: Path) -> pd.DataFrame | None:
    return _read_csv(str(path), path.stat().st_mtime) if path.is_file() else None


def _run_status() -> dict:
    exploratory_run = _latest_exploratory_run()
    return exploratory_run[1] if exploratory_run is not None else {"status": "NOT_RUN"}


def _audit() -> dict | None:
    report_dir = _active_run_report_dir()
    return _existing_json(report_dir / "data_audit.json") if report_dir else None


def _exploratory_runs() -> list[tuple[Path, dict[str, Any]]]:
    root = PROJECT_DIR / "artifacts" / "exploratory"
    runs: list[tuple[Path, dict[str, Any]]] = []
    if not root.is_dir():
        return runs
    for run_dir in root.iterdir():
        manifest = _existing_json(run_dir / "reports" / "run_manifest.json")
        if (
            manifest is not None
            and manifest.get("analysis_mode") == "ASSUMPTION_BASED_EXPLORATORY"
            and manifest.get("output_label") == "EXPLORATORY"
        ):
            runs.append((run_dir, manifest))
    return sorted(
        runs,
        key=lambda item: str(item[1].get("completed_at", "")),
        reverse=True,
    )


def _latest_exploratory_run() -> tuple[Path, dict[str, Any]] | None:
    return next(
        (run for run in _exploratory_runs() if run[1].get("status") == "EXPLORATORY_COMPLETE"),
        None,
    )


def _active_run_report_dir() -> Path | None:
    exploratory_run = _latest_exploratory_run()
    return exploratory_run[0] / "reports" if exploratory_run else None


def _top10_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if "rank" not in frame.columns:
        return frame.iloc[0:0].copy()
    ranks = pd.to_numeric(frame["rank"], errors="coerce")
    return (
        frame.loc[ranks.between(1, 10)]
        .assign(rank=ranks.loc[ranks.between(1, 10)].astype(int))
        .sort_values("rank", kind="stable")
        .copy()
    )


def _top10_columns(role: str, frame: pd.DataFrame) -> list[str]:
    preferred = [
        "rank",
        "player_name",
        "composite_score",
        "pressure_runs" if role == "batter" else "pressure_wickets",
        "pressure_strike_rate" if role == "batter" else "pressure_economy",
    ]
    return [column for column in preferred if column in frame.columns]


def _saved_ranking_frames(
    role: str, manifest: dict
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, bool, str]:
    exploratory_run = _latest_exploratory_run()
    if exploratory_run is None:
        return None, None, False, ""
    run_dir, exploratory_manifest = exploratory_run
    rankings_dir = run_dir / "rankings"
    run_id = str(exploratory_manifest.get("run_id", run_dir.name))
    full = _existing_csv(rankings_dir / f"{role}_full_rankings.csv")
    top_file = _existing_csv(rankings_dir / f"top_10_{role}s.csv")
    top = _top10_rows(top_file) if top_file is not None else None
    return full, top, True, run_id


def _coach_table(frame: pd.DataFrame, role: str) -> pd.DataFrame:
    labels = {
        "rank": "Saved rank",
        "player_name": "Player",
    }
    if role == "batter":
        labels.update(
            {
                "pressure_runs": "Runs in pressure",
                "pressure_balls": "Balls faced in pressure",
                "pressure_strike_rate": "Pressure runs per 100 balls",
                "normal_strike_rate": "Normal runs per 100 balls",
                "strike_rate_change": "Pressure change",
                "fours": "Fours",
                "sixes": "Sixes",
                "dots": "Scoreless balls",
                "dot_ball_rate": "Scoreless-ball percentage",
                "boundary_rate": "Boundary percentage",
                "consistency": "Consistency (regularity)",
                "dismissals": "Dismissals in pressure",
            }
        )
    else:
        labels.update(
            {
                "pressure_wickets": "Wickets in pressure",
                "pressure_conceded_runs": "Runs conceded in pressure",
                "legal_pressure_balls": "Legal balls in pressure",
                "pressure_economy": "Pressure runs per over",
                "normal_economy": "Normal runs per over",
                "economy_improvement": "Pressure economy change",
                "dots": "Scoreless balls",
                "dot_ball_rate": "Scoreless-ball percentage",
                "boundary_conceded_rate": "Boundary-ball percentage conceded",
                "consistency": "Consistency (regularity)",
            }
        )
    available = [column for column in labels if column in frame.columns]
    return frame[available].rename(columns={column: labels[column] for column in available})


def _format_metric(value: object, decimals: int = 1) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "—" if pd.isna(number) else f"{number:,.{decimals}f}"


def _style_coach_chart(figure, *, height: int = 360):
    figure.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, Segoe UI, sans-serif", "color": "#F8FAFC", "size": 12},
        colorway=["#E91E8C", "#17479E", "#FF4FA3", "#5679BC", "#A9B5CC"],
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"l": 18, "r": 18, "t": 72, "b": 24},
        height=height,
        hovermode="closest",
    )
    figure.update_xaxes(showgrid=True, gridcolor="rgba(43, 56, 85, 0.62)", zeroline=False)
    figure.update_yaxes(showgrid=False, zeroline=False)
    figure.update_traces(hoverlabel={"bgcolor": "#151D32", "font_color": "#F8FAFC"})
    return figure


def _player_choices(frame: pd.DataFrame, id_column: str) -> tuple[list[str], dict[str, str]]:
    if frame.empty or "player_name" not in frame or id_column not in frame:
        return [], {}
    players = frame.loc[frame["player_name"].notna() & frame[id_column].notna()].copy()
    players = players.sort_values("rank", na_position="last", kind="stable")
    labels: list[str] = []
    identifiers: dict[str, str] = {}
    for row in (
        players[[id_column, "player_name"]]
        .drop_duplicates(id_column)
        .itertuples(index=False, name=None)
    ):
        player_id, name = str(row[0]), str(row[1])
        label = f"{name} · {player_id}"
        labels.append(label)
        identifiers[label] = player_id
    return labels, identifiers


def _full_coach_table(frame: pd.DataFrame, role: str) -> None:
    with st.expander("Browse the full player rankings", expanded=False):
        search = (
            st.text_input("Find a player by name", key=f"coach-{role}-search").strip().casefold()
        )
        filtered = frame.copy()
        if search:
            filtered = filtered.loc[
                filtered["player_name"].fillna("").astype(str).str.casefold().str.contains(search)
            ]
        if "comparison_context" in filtered.columns:
            contexts = filtered["comparison_context"].fillna("").astype(str).str.split(",")
            competitions = sorted(
                {value.strip() for values in contexts for value in values if value.strip()}
            )
            selected = st.multiselect(
                "Competition",
                competitions,
                default=competitions,
                key=f"coach-{role}-competition",
            )
            filtered = filtered.loc[
                contexts.map(
                    lambda values: bool(
                        set(selected).intersection(value.strip() for value in values)
                    )
                )
            ]
        table = _coach_table(filtered.sort_values("rank", na_position="last"), role)
        if table.empty:
            st.info("No players match the selected filters.")
        else:
            st.dataframe(table, width="stretch", hide_index=True)


def _coach_metric_cards(row: pd.Series, role: str) -> None:
    if role == "batter":
        metrics = [
            ("Pressure runs", row.get("pressure_runs"), 0),
            ("Pressure balls faced", row.get("pressure_balls"), 0),
            ("Runs per 100 pressure balls", row.get("pressure_strike_rate"), 1),
            ("Normal runs per 100 balls", row.get("normal_strike_rate"), 1),
            ("Fours + sixes", row.get("fours", 0) + row.get("sixes", 0), 0),
        ]
    else:
        metrics = [
            ("Pressure wickets", row.get("pressure_wickets"), 0),
            ("Pressure runs per over", row.get("pressure_economy"), 2),
            ("Normal runs per over", row.get("normal_economy"), 2),
            ("Legal pressure balls", row.get("legal_pressure_balls"), 0),
            ("Scoreless-ball percentage", row.get("dot_ball_rate"), 1),
        ]
    for start in range(0, len(metrics), 3):
        row_metrics = metrics[start : start + 3]
        columns = st.columns(len(row_metrics))
        for column, (label, value, decimals) in zip(columns, row_metrics, strict=True):
            column.metric(label, _format_metric(value, decimals))


def _coach_rankings(role: str, manifest: dict) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    full, top, exploratory, run_id = _saved_ranking_frames(role, manifest)
    title = "Batting Under Pressure" if role == "batter" else "Bowling Under Pressure"
    st.title(title)
    st.caption(
        ("EXPLORATORY ANALYSIS · " if exploratory else "")
        + f"Saved results from run {run_id}. "
        + (
            "These rankings use assumptions that are not source-confirmed."
            if exploratory
            else "Metrics are shown in cricket terms; the original saved rank order is preserved."
        )
    )
    if full is None or full.empty or top is None or top.empty:
        st.info("No saved ranking data is available for this view.")
        return None
    id_column = "striker_id" if role == "batter" else "bowler_id"
    metric_columns = (
        {
            "pressure_runs",
            "pressure_balls",
            "pressure_strike_rate",
            "normal_strike_rate",
            "strike_rate_change",
            "fours",
            "sixes",
            "dot_ball_rate",
            "boundary_rate",
        }
        if role == "batter"
        else {
            "pressure_wickets",
            "pressure_economy",
            "normal_economy",
            "legal_pressure_balls",
            "dot_ball_rate",
            "boundary_conceded_rate",
        }
    )
    required = metric_columns | {"rank", "player_name", id_column}
    missing = required.difference(full.columns) | required.difference(top.columns)
    if missing:
        st.warning(
            "Saved ranking data is missing fields needed for coach charts: "
            + ", ".join(sorted(missing))
        )
        return None
    top = top.loc[top["player_name"].notna()].sort_values("rank", kind="stable")
    full = full.loc[full["player_name"].notna()].sort_values("rank", na_position="last")
    if top.empty or full.empty:
        st.info("The saved ranking file contains no player rows to display.")
        return None

    if role == "batter":
        st.markdown("### Top 10 pressure run-scorers")
        chart_data = top.sort_values("rank", ascending=False)
        figure = px.bar(
            chart_data,
            x="pressure_runs",
            y="player_name",
            orientation="h",
            color_discrete_sequence=["#E91E8C"],
            hover_data={
                "rank": True,
                "pressure_balls": True,
                "pressure_strike_rate": ":.1f",
                "player_name": False,
            },
            labels={
                "pressure_runs": "Runs in high-pressure chases",
                "player_name": "Batter",
                "rank": "Saved overall rank",
                "pressure_balls": "Balls faced in pressure",
                "pressure_strike_rate": "Runs per 100 pressure balls",
            },
            title="Runs scored in high-pressure situations",
        )
        figure.update_yaxes(
            categoryorder="array",
            categoryarray=chart_data["player_name"].astype(str).tolist(),
        )
    else:
        st.markdown("### Top 10 pressure wicket-takers")
        chart_data = top.sort_values("rank", ascending=False)
        figure = px.bar(
            chart_data,
            x="pressure_wickets",
            y="player_name",
            orientation="h",
            color_discrete_sequence=["#17479E"],
            hover_data={
                "rank": True,
                "legal_pressure_balls": True,
                "pressure_economy": ":.2f",
                "player_name": False,
            },
            labels={
                "pressure_wickets": "Wickets in high-pressure chases",
                "player_name": "Bowler",
                "rank": "Saved overall rank",
                "legal_pressure_balls": "Legal pressure balls",
                "pressure_economy": "Runs conceded per over",
            },
            title="Wickets taken in high-pressure situations",
        )
        figure.update_yaxes(
            categoryorder="array",
            categoryarray=chart_data["player_name"].astype(str).tolist(),
        )
    st.plotly_chart(
        _style_coach_chart(figure, height=440),
        width="stretch",
        config={"displayModeBar": False},
    )

    st.markdown("### Choose a player")
    labels, identifiers = _player_choices(full, id_column)
    if not labels:
        st.info("Player names or identifiers are missing in the saved ranking.")
        return full, top
    selection = st.selectbox(
        "Player profile",
        labels,
        index=0,
        key=f"coach-{role}-profile",
    )
    selected_id = identifiers[selection]
    row = full.loc[full[id_column].astype(str).eq(selected_id)].iloc[0]
    st.subheader(str(row["player_name"]))
    context = row.get("comparison_context", "competition not listed")
    st.caption(f"Saved overall rank {int(row['rank'])} · {context}")
    _coach_metric_cards(row, role)
    if role == "batter":
        st.caption(
            "Strike rate means runs scored per 100 balls. Boundary percentage is the share "
            "of pressure balls ending in a four or six."
        )
    else:
        st.caption(
            "Economy means runs conceded per over. Dot-ball percentage is the share of "
            "pressure balls on which the batter scored no runs."
        )

    if role == "batter":
        _batting_charts(full, top)
    else:
        _bowling_charts(top)
    _full_coach_table(full, role)
    return full, top


def _batting_charts(full: pd.DataFrame, top: pd.DataFrame) -> None:
    st.markdown("### Batting comparison")
    chart_data = top.sort_values("rank", ascending=False)
    chart = px.bar(
        chart_data,
        x="pressure_runs",
        y="player_name",
        orientation="h",
        color_discrete_sequence=["#E91E8C"],
        hover_data={"rank": True, "pressure_balls": True, "player_name": False},
        labels={
            "pressure_runs": "Runs",
            "player_name": "Batter",
            "rank": "Saved overall rank",
            "pressure_balls": "Pressure balls faced",
        },
        title="Pressure runs · saved Top 10",
    )
    chart.update_yaxes(
        categoryorder="array",
        categoryarray=chart_data["player_name"].astype(str).tolist(),
    )
    st.plotly_chart(_style_coach_chart(chart), width="stretch", config={"displayModeBar": False})

    chart = px.bar(
        chart_data,
        x="pressure_strike_rate",
        y="player_name",
        orientation="h",
        color_discrete_sequence=["#E91E8C"],
        hover_data={"rank": True, "pressure_balls": True, "player_name": False},
        labels={
            "pressure_strike_rate": "Runs per 100 balls",
            "player_name": "Batter",
            "rank": "Saved overall rank",
            "pressure_balls": "Pressure balls faced",
        },
        title="Runs per 100 pressure balls · saved Top 10",
    )
    chart.update_yaxes(
        categoryorder="array",
        categoryarray=chart_data["player_name"].astype(str).tolist(),
    )
    st.plotly_chart(_style_coach_chart(chart), width="stretch", config={"displayModeBar": False})

    rate_comparison = top.melt(
        id_vars=["player_name", "rank"],
        value_vars=["normal_strike_rate", "pressure_strike_rate"],
        var_name="match_situation",
        value_name="runs_per_100_balls",
    )
    rate_comparison["match_situation"] = rate_comparison["match_situation"].map(
        {
            "normal_strike_rate": "Normal chases",
            "pressure_strike_rate": "High-pressure chases",
        }
    )
    rate_comparison = rate_comparison.rename(
        columns={"player_name": "Batter", "runs_per_100_balls": "Runs per 100 balls"}
    )
    comparison_chart = px.bar(
        rate_comparison,
        x="Batter",
        y="Runs per 100 balls",
        color="match_situation",
        barmode="group",
        color_discrete_map={"Normal chases": "#17479E", "High-pressure chases": "#E91E8C"},
        hover_data={"rank": True},
        title="Scoring rate: normal vs high-pressure chases",
    )
    st.plotly_chart(
        _style_coach_chart(comparison_chart, height=410),
        width="stretch",
        config={"displayModeBar": False},
    )

    boundaries = pd.DataFrame(
        {
            "Boundary": ["Fours", "Sixes"],
            "Count": [
                pd.to_numeric(top["fours"], errors="coerce").sum(),
                pd.to_numeric(top["sixes"], errors="coerce").sum(),
            ],
        }
    )
    if boundaries["Count"].sum() > 0:
        pie = px.pie(
            boundaries,
            names="Boundary",
            values="Count",
            hole=0.62,
            color="Boundary",
            color_discrete_map={"Fours": "#FF4FA3", "Sixes": "#17479E"},
            title="Fours and sixes · saved Top 10",
        )
        pie.update_traces(
            textinfo="label+percent", hovertemplate="%{label}: %{value}<extra></extra>"
        )
        st.plotly_chart(
            _style_coach_chart(pie, height=380),
            width="stretch",
            config={"displayModeBar": False},
        )
    else:
        st.info("No boundary counts are available for the saved Top 10.")

    scatter = px.scatter(
        full,
        x="pressure_balls",
        y="pressure_strike_rate",
        size="pressure_runs",
        color="comparison_context",
        hover_name="player_name",
        hover_data={"rank": True, "pressure_runs": True},
        labels={
            "pressure_balls": "Balls faced in pressure situations",
            "pressure_strike_rate": "Runs per 100 pressure balls",
            "pressure_runs": "Pressure runs",
            "comparison_context": "Competition group",
        },
        title="Scoring rate and pressure experience",
        color_discrete_sequence=["#E91E8C", "#17479E", "#5679BC"],
    )
    st.plotly_chart(
        _style_coach_chart(scatter, height=380),
        width="stretch",
        config={"displayModeBar": False},
    )

    st.markdown("### Compare batters")
    labels, identifiers = _player_choices(full, "striker_id")
    defaults = labels[:3]
    selected = st.multiselect(
        "Choose up to five batters",
        labels,
        default=defaults,
        max_selections=5,
        key="coach-batter-compare",
    )
    compare_ids = [identifiers[label] for label in selected]
    comparison = full.loc[full["striker_id"].astype(str).isin(compare_ids)]
    if not comparison.empty:
        chart_data = comparison.melt(
            id_vars=["player_name", "rank"],
            value_vars=["normal_strike_rate", "pressure_strike_rate"],
            var_name="match_situation",
            value_name="runs_per_100_balls",
        )
        chart_data["match_situation"] = chart_data["match_situation"].map(
            {
                "normal_strike_rate": "Normal chases",
                "pressure_strike_rate": "High-pressure chases",
            }
        )
        chart = px.bar(
            chart_data,
            x="player_name",
            y="runs_per_100_balls",
            color="match_situation",
            barmode="group",
            color_discrete_map={"Normal chases": "#17479E", "High-pressure chases": "#E91E8C"},
            hover_data={"rank": True},
            labels={"player_name": "Batter", "runs_per_100_balls": "Runs per 100 balls"},
            title="Selected batters · normal and high-pressure scoring rate",
        )
        st.plotly_chart(
            _style_coach_chart(chart, height=410), width="stretch", config={"displayModeBar": False}
        )


def _bowling_charts(top: pd.DataFrame) -> None:
    st.markdown("### Bowling comparison · saved Top 10")
    economy_comparison = top.melt(
        id_vars=["player_name", "rank"],
        value_vars=["normal_economy", "pressure_economy"],
        var_name="match_situation",
        value_name="runs_per_over",
    )
    economy_comparison["match_situation"] = economy_comparison["match_situation"].map(
        {
            "normal_economy": "Normal chases",
            "pressure_economy": "High-pressure chases",
        }
    )
    economy_chart = px.bar(
        economy_comparison,
        x="player_name",
        y="runs_per_over",
        color="match_situation",
        barmode="group",
        color_discrete_map={"Normal chases": "#E91E8C", "High-pressure chases": "#17479E"},
        hover_data={"rank": True},
        labels={
            "player_name": "Bowler",
            "runs_per_over": "Runs conceded per over",
        },
        title="Economy: normal vs high-pressure chases",
    )
    st.plotly_chart(
        _style_coach_chart(economy_chart, height=410),
        width="stretch",
        config={"displayModeBar": False},
    )
    st.caption("A lower economy means fewer runs conceded per over.")
    chart_specs = [
        ("pressure_wickets", "Wickets in pressure situations", "Wickets"),
        ("pressure_economy", "Runs conceded per pressure over", "Runs per over"),
        ("dot_ball_rate", "Scoreless-ball percentage", "Percentage of legal pressure balls"),
        (
            "boundary_conceded_rate",
            "Boundary-ball percentage conceded",
            "Percentage of legal pressure balls",
        ),
    ]
    data = top.sort_values("rank", ascending=False)
    for metric, title, unit in chart_specs:
        chart = px.bar(
            data,
            x=metric,
            y="player_name",
            orientation="h",
            color_discrete_sequence=["#17479E"],
            hover_data={
                "rank": True,
                "legal_pressure_balls": True,
                "pressure_wickets": True,
                "player_name": False,
            },
            labels={
                metric: unit,
                "player_name": "Bowler",
                "rank": "Saved overall rank",
                "legal_pressure_balls": "Legal pressure balls",
                "pressure_wickets": "Pressure wickets",
            },
            title=title,
        )
        chart.update_yaxes(
            categoryorder="array",
            categoryarray=data["player_name"].astype(str).tolist(),
        )
        st.plotly_chart(
            _style_coach_chart(chart),
            width="stretch",
            config={"displayModeBar": False},
        )

    st.markdown("### Bowling performance and experience")
    scatter = px.scatter(
        top,
        x="legal_pressure_balls",
        y="pressure_economy",
        size="pressure_wickets",
        color="dot_ball_rate",
        hover_name="player_name",
        hover_data={
            "rank": True,
            "pressure_wickets": True,
            "dot_ball_rate": ":.1f",
            "boundary_conceded_rate": ":.1f",
        },
        labels={
            "legal_pressure_balls": "Legal balls bowled in pressure situations",
            "pressure_economy": "Runs conceded per over",
            "pressure_wickets": "Pressure wickets",
            "dot_ball_rate": "Scoreless-ball percentage",
        },
        title="Economy, pressure wickets, and scoreless balls",
        color_continuous_scale=["#17479E", "#FF4FA3"],
    )
    st.plotly_chart(
        _style_coach_chart(scatter, height=410), width="stretch", config={"displayModeBar": False}
    )


def _coach_insights(manifest: dict) -> None:
    st.title("Coach Insights")
    batters = _saved_ranking_frames("batter", manifest)[1]
    bowlers = _saved_ranking_frames("bowler", manifest)[1]
    if batters is None or bowlers is None or batters.empty or bowlers.empty:
        st.info("Saved Top 10 rankings are unavailable, so no insights can be shown.")
        return
    if not {"player_name", "rank"}.issubset(batters.columns) or not {
        "player_name",
        "rank",
    }.issubset(bowlers.columns):
        st.info("Saved player metrics do not include the names and ranks needed for insights.")
        return
    st.caption(
        "EXPLORATORY observations from saved player metrics; assumptions are not source-confirmed."
    )
    st.markdown(
        "Observations below describe this dataset only; they are not claims about cricket overall."
    )
    st.caption("Insights are limited to players in the saved Top 10 batter and bowler rankings.")
    insights: list[tuple[str, str, str]] = []
    ranked_batters = batters.assign(
        _insight_rank=pd.to_numeric(batters["rank"], errors="coerce")
    ).dropna(subset=["_insight_rank"])
    if not ranked_batters.empty:
        player = ranked_batters.sort_values("_insight_rank").iloc[0]
        ranking_detail = (
            f"Rank {_format_metric(player['_insight_rank'], 0)} in the saved "
            "overall exploratory ranking"
        )
        if "pressure_runs" in player.index and pd.notna(player["pressure_runs"]):
            ranking_detail += f" · {_format_metric(player['pressure_runs'], 0)} pressure runs"
        if "pressure_balls" in player.index and pd.notna(player["pressure_balls"]):
            ranking_detail += f" · {_format_metric(player['pressure_balls'], 0)} balls faced"
        insights.append(
            ("Top overall pressure batter", str(player["player_name"]), ranking_detail)
        )
    batter_rate = (
        batters.dropna(subset=["pressure_strike_rate"])
        if "pressure_strike_rate" in batters.columns
        else batters.iloc[0:0]
    )
    if not batter_rate.empty:
        player = batter_rate.loc[batter_rate["pressure_strike_rate"].idxmax()]
        insights.append(
            (
                "Highest pressure scoring rate",
                str(player["player_name"]),
                f"{_format_metric(player['pressure_strike_rate'])} runs per 100 pressure balls · "
                f"{_format_metric(player.get('pressure_balls'), 0)} balls faced",
            )
        )
    improvement = (
        batters.dropna(subset=["strike_rate_change"])
        if "strike_rate_change" in batters.columns
        else batters.iloc[0:0]
    )
    if not improvement.empty:
        player = improvement.loc[improvement["strike_rate_change"].idxmax()]
        change = float(player["strike_rate_change"])
        if change > 0:
            insights.append(
                (
                    "Largest scoring-rate increase",
                    str(player["player_name"]),
                    f"+{_format_metric(change)} runs per 100 balls vs normal chases",
                )
            )
        else:
            insights.append(
                (
                    "Pressure scoring comparison",
                    "No positive increase in this dataset",
                    "Highest recorded change was not above normal scoring rate.",
                )
            )
    wicket_rows = (
        bowlers.dropna(subset=["pressure_wickets"])
        if "pressure_wickets" in bowlers.columns
        else bowlers.iloc[0:0]
    )
    if not wicket_rows.empty:
        player = wicket_rows.loc[wicket_rows["pressure_wickets"].idxmax()]
        insights.append(
            (
                "Most pressure wickets",
                str(player["player_name"]),
                f"{_format_metric(player['pressure_wickets'], 0)} wickets in pressure situations",
            )
        )
    economy_rows = (
        bowlers.dropna(subset=["pressure_economy"])
        if "pressure_economy" in bowlers.columns
        else bowlers.iloc[0:0]
    )
    if not economy_rows.empty:
        player = economy_rows.loc[economy_rows["pressure_economy"].idxmin()]
        insights.append(
            (
                "Fewest runs conceded per pressure over",
                str(player["player_name"]),
                f"{_format_metric(player['pressure_economy'], 2)} runs per over",
            )
        )
    dot_rows = (
        bowlers.dropna(subset=["dot_ball_rate"])
        if "dot_ball_rate" in bowlers.columns
        else bowlers.iloc[0:0]
    )
    if not dot_rows.empty:
        player = dot_rows.loc[dot_rows["dot_ball_rate"].idxmax()]
        insights.append(
            (
                "Highest scoreless-ball percentage",
                str(player["player_name"]),
                f"{_format_metric(player['dot_ball_rate'])}% of legal pressure balls",
            )
        )
    if not insights:
        st.info("The saved data does not contain enough complete metrics to generate insights.")
        return
    for start in range(0, len(insights), 3):
        columns = st.columns(3)
        for column, (label, player, detail) in zip(
            columns, insights[start : start + 3], strict=False
        ):
            card = column.container(border=True)
            card.markdown(f"**{label}**")
            card.subheader(player)
            card.caption(detail)
    for role, frame in [("Batting", batters), ("Bowling", bowlers)]:
        top_rows = frame.loc[
            pd.to_numeric(frame["rank"], errors="coerce").between(1, 3)
        ].sort_values("rank")
        if not top_rows.empty:
            names = ", ".join(top_rows["player_name"].dropna().astype(str))
            st.markdown(f"**Top three in the saved {role.lower()} ranking:** {names}.")
    st.caption(
        "Strike rate = runs per 100 balls · Economy = runs conceded per over · "
        "Dot-ball percentage = legal pressure balls with no runs scored."
    )


def _mapping_editor(files: Mapping[str, UploadedFile], config) -> dict[str, dict[str, str]]:
    source_columns: dict[str, list[str]] = {}
    for table, filename in SOURCE_FILES.items():
        uploaded = files.get(filename)
        if uploaded is None:
            continue
        columns = pd.read_csv(uploaded, nrows=0, encoding="utf-8-sig").columns
        source_columns[table] = [str(column).strip() for column in columns]
        uploaded.seek(0)
    overrides: dict[str, dict[str, str]] = {}
    with st.expander("Review source-to-canonical column mappings", expanded=False):
        st.caption(
            "Select the source column that represents each canonical field. "
            "Mappings are applied in memory; uploaded CSVs are not edited."
        )
        for table, mappings in config.source_fields.items():
            if table not in source_columns:
                continue
            st.markdown(f"**{table.replace('_', ' ').title()}**")
            for canonical_name, default_source in mappings.items():
                options = source_columns[table]
                default_index = options.index(default_source) if default_source in options else 0
                selected = st.selectbox(
                    canonical_name,
                    options=options,
                    index=default_index,
                    key=f"mapping-{table}-{canonical_name}",
                    label_visibility="collapsed",
                )
                if selected != default_source:
                    overrides.setdefault(table, {})[canonical_name] = selected
    return overrides


def _upload_and_run(config) -> None:
    uploaded_files = st.file_uploader(
        "Upload the six source CSV files",
        type=["csv"],
        accept_multiple_files=True,
        key="source_csv_uploads",
    )
    if not uploaded_files:
        return
    by_name = {file.name: file for file in uploaded_files}
    expected = set(SOURCE_FILES.values())
    missing = sorted(expected - set(by_name))
    unexpected = sorted(set(by_name) - expected)
    if missing:
        st.info(f"Still needed: {', '.join(missing)}")
    if unexpected:
        st.warning("Files with unexpected names will not be used: " + ", ".join(unexpected))
    overrides = _mapping_editor(by_name, config)
    can_run = not missing
    if st.button("Run analysis", type="primary", disabled=not can_run):
        try:
            with tempfile.TemporaryDirectory(prefix="suprr-upload-") as directory:
                raw_dir = Path(directory)
                for filename in expected:
                    by_name[filename].seek(0)
                    (raw_dir / filename).write_bytes(by_name[filename].getvalue())
                with st.spinner("Auditing the uploaded data and running eligible analyses…"):
                    result = run_pipeline(
                        PROJECT_DIR,
                        raw_dir=raw_dir,
                        mapping_overrides=overrides,
                    )
            st.session_state["last_upload_run"] = result["status"]
            st.cache_data.clear()
            st.success(f"Run finished with status: {result['status']}")
            st.rerun()
        except InputFilesError as error:
            st.error(f"Input files could not be loaded: {error}")
        except ValueError as error:
            st.error(f"Analysis could not continue: {error}")


def _overview(audit: dict | None, manifest: dict) -> None:
    exploratory_run = _latest_exploratory_run()
    badge = "EXPLORATORY ANALYSIS"
    st.markdown(
        f"""
        <section class="hero">
          <div>
            <div class="eyebrow">SupeRR Selector · Cricket analytics</div>
            <div class="theme-note">
              Rajasthan Royals-inspired colors · Not affiliated with the team
            </div>
            <h1 class="hero-title">Batman Plays Under Pressure</h1>
            <p class="hero-copy">
              Explore saved batting and bowling performance in high-pressure chases.
            </p>
          </div>
          <span class="status-badge">{badge}</span>
        </section>
        """,
        unsafe_allow_html=True,
    )
    if audit is not None:
        tables = audit.get("tables", {})
        source_deliveries = tables.get("deliveries", {}).get("rows")
        source_matches = tables.get("matches", {}).get("rows")
        competitions = tables.get("competitions", {}).get("rows")
        season_schema: dict[str, object] = next(
            (
                column
                for column in audit.get("schemas", {}).get("competitions", [])
                if column["column"] == "season"
            ),
            {},
        )
        season_count = season_schema.get("distinct_non_null")
        pressure_summary: dict = {}
        if exploratory_run is not None:
            run_dir, _ = exploratory_run
            pressure_summary = (
                _existing_json(run_dir / "reports" / "pressure_validation.json") or {}
            ).get("summary", {})
        analyzed_matches = pressure_summary.get("distinct_matches")
        pressure_deliveries = pressure_summary.get("valid_delivery_rows")
        coverage = [
            (
                "Matches analyzed" if analyzed_matches is not None else "Source matches",
                analyzed_matches if analyzed_matches is not None else source_matches,
            ),
            (
                "Pressure deliveries"
                if pressure_deliveries is not None
                else "Source deliveries",
                pressure_deliveries if pressure_deliveries is not None else source_deliveries,
            ),
            ("Competitions", competitions),
            ("Seasons", season_count),
        ]
        st.markdown("### At a glance")
        with st.container(key="overview-kpi-band"):
            columns = st.columns(4)
            for column, (label, value) in zip(columns, coverage, strict=True):
                if value is not None:
                    column.metric(
                        label,
                        f"{value:,}" if isinstance(value, int) else str(value),
                    )
                else:
                    column.metric(label, "—")
        if pressure_summary:
            st.caption(
                "Match and delivery totals use saved pressure-analysis coverage; "
                "competitions and seasons use source-file coverage."
            )
        else:
            st.caption("Coverage counts are from the audited source files.")
    else:
        st.info("Upload the six CSV files and run the analysis to inspect actual coverage.")

    batter_full = _saved_ranking_frames("batter", manifest)[0]
    bowler_full = _saved_ranking_frames("bowler", manifest)[0]
    if batter_full is not None and not batter_full.empty:
        batter_first = batter_full.sort_values("rank", na_position="last").iloc[0]
    else:
        batter_first = None
    if bowler_full is not None and not bowler_full.empty:
        bowler_first = bowler_full.sort_values("rank", na_position="last").iloc[0]
    else:
        bowler_first = None
    if batter_first is not None or bowler_first is not None:
        st.markdown("### Featured performers")
        with st.container(key="featured-player-cards"):
            leaders = st.columns(2)
            if batter_first is not None:
                leaders[0].caption("TOP PRESSURE BATTER")
                leaders[0].subheader(str(batter_first.get("player_name", "Not available")))
                leaders[0].write(
                    f"**{_format_metric(batter_first.get('pressure_runs'), 0)}** pressure runs"
                )
            else:
                leaders[0].caption("TOP PRESSURE BATTER")
                leaders[0].write("No saved batter ranking is available.")
            if bowler_first is not None:
                leaders[1].caption("TOP PRESSURE BOWLER")
                leaders[1].subheader(str(bowler_first.get("player_name", "Not available")))
                leaders[1].write(
                    f"**{_format_metric(bowler_first.get('pressure_wickets'), 0)}** "
                    "pressure wickets"
                )
            else:
                leaders[1].caption("TOP PRESSURE BOWLER")
                leaders[1].write("No saved bowler ranking is available.")
        st.caption(
            "Featured players follow saved exploratory rankings, not validated results."
        )
    else:
        st.caption("Saved player rankings are not available yet.")

    with st.expander("Data Quality & Methodology", expanded=False):
        st.markdown(
            "The rankings below use saved **EXPLORATORY** results and conventional assumptions. "
            "Those assumptions are not confirmed by an authoritative source."
        )
        st.markdown("#### Source mapping")
        st.write(
            "The supplied files do not include an authoritative scoring codebook or independent "
            "scorecards. The original publisher and dataset version are unresolved. The `runs` "
            "field aligns with recorded four/six flags, but its meaning is inferred rather than "
            "source-confirmed."
        )
        extra_col, legal_col = st.columns(2)
        with extra_col:
            st.markdown("#### Extras classification")
            st.write(
                "Exploratory analysis treats `Overstep` as a no-ball. It treats `Penalty` and "
                "`other` as team extras, not charged to the bowler. The meanings of "
                "`extras1_runs` and `extras_2_runs` have no authoritative source definition."
            )
        with legal_col:
            st.markdown("#### Legal deliveries")
            st.write(
                "Exploratory analysis treats wides and no-balls as illegal; `None`, byes, "
                "leg-byes, `Penalty`, and `other` as legal. The source provides no legal-ball "
                "flag or confirmed rule for these labels."
            )
        st.markdown("#### Bowler runs conceded")
        st.code(
            "Exploratory: runs + extras1_runs + extras_2_runs for wide/no-ball; runs otherwise",
            language="text",
        )
        st.caption(
            "This concession rule and the exploratory `Stump` → `Stumped` dismissal mapping "
            "are not source-confirmed. Pressure validation PASS applies only under these "
            "assumptions."
        )
        if audit is not None:
            findings = pd.DataFrame(audit.get("findings", []))
            if not findings.empty:
                st.markdown("#### Open audit findings")
                st.dataframe(findings, width="stretch", hide_index=True)
        report_dir = _active_run_report_dir()
        machine_status = (
            _existing_json(report_dir / "audit_status.json") or {} if report_dir else {}
        )
        exclusions = machine_status.get("confirmed_exclusions", {})
        if exclusions:
            st.markdown("#### Exclusions retained")
            st.caption(
                f"{exclusions.get('super_overs', {}).get('innings_groups', 0)} confirmed "
                "Super Over innings groups and "
                f"{exclusions.get('revised_conditions', {}).get('matches', 0)} revised-condition "
                "matches are excluded from the primary analysis."
            )
        st.caption(
            "Open Data Quality & Methodology for source evidence, assumptions, and limitations."
        )

    if exploratory_run is not None:
        run_dir, exploratory_manifest = exploratory_run
        st.caption(
            f"Saved exploratory run {exploratory_manifest.get('run_id', run_dir.name)} · "
            f"completed {exploratory_manifest.get('completed_at', 'date unavailable')}. "
            "Full rankings and player profiles are in Batting and Bowling."
        )
    batter_rates = (
        batter_full.dropna(subset=["pressure_strike_rate"])
        if batter_full is not None and "pressure_strike_rate" in batter_full.columns
        else pd.DataFrame()
    )
    bowler_economy = (
        bowler_full.dropna(subset=["pressure_economy"])
        if bowler_full is not None and "pressure_economy" in bowler_full.columns
        else pd.DataFrame()
    )
    if not batter_rates.empty or not bowler_economy.empty:
        st.markdown("### A quick read")
        insights = st.columns(2)
        if not batter_rates.empty:
            player = batter_rates.loc[batter_rates["pressure_strike_rate"].idxmax()]
            insights[0].markdown("**Fastest pressure scoring rate**")
            insights[0].write(
                f"{player['player_name']} · "
                f"{_format_metric(player['pressure_strike_rate'])} runs per 100 balls "
                f"across {_format_metric(player.get('pressure_balls'), 0)} pressure balls."
            )
        if not bowler_economy.empty:
            player = bowler_economy.loc[bowler_economy["pressure_economy"].idxmin()]
            insights[1].markdown("**Tightest pressure economy**")
            insights[1].write(
                f"{player['player_name']} · "
                f"{_format_metric(player['pressure_economy'], 2)} runs conceded per over."
            )
        st.caption("Dataset-specific observations from saved exploratory rankings.")


def _pressure_page(manifest: dict, audit: dict | None) -> None:
    st.title("Pressure Model")
    st.markdown(
        r"**Pre-delivery score:** $P = 0.35R + 0.25W + 0.25D + 0.15S$ "
        "with each component clamped to [0, 1]. A state is live only when runs, "
        "legal balls, and wickets in hand remain."
    )
    st.caption(
        "Primary threshold: P ≥ 0.60. First-innings deliveries are not pooled into "
        "the primary lower-pressure chase baseline."
    )
    exploratory_run = _latest_exploratory_run()
    if exploratory_run is None:
        st.info("No saved exploratory pressure diagnostics are available.")
        return
    run_dir, _ = exploratory_run
    report_dir = run_dir / "reports"
    state_path = run_dir / "processed" / "pressure_states.parquet"
    st.caption(
        "Exploratory pressure diagnostics use assumptions that are not source-confirmed."
    )
    result = _existing_json(report_dir / "pressure_validation.json")
    if result:
        st.metric("Validation status", result.get("status", "Unknown"))
        st.json(result.get("summary", {}), expanded=False)
        if result.get("diagnostics"):
            for diagnostic in result["diagnostics"]:
                st.warning(diagnostic)
        gradient = pd.DataFrame(result.get("outcome_gradient", []))
        if not gradient.empty:
            st.dataframe(gradient, width="stretch", hide_index=True)
            plot = px.line(
                gradient,
                x="pressure_band",
                y="win_rate",
                error_y=gradient["ci95_high"] - gradient["win_rate"],
                error_y_minus=gradient["win_rate"] - gradient["ci95_low"],
                markers=True,
                title="Chasing-team win rate by pressure band",
            )
            st.plotly_chart(plot, width="stretch")
        ablations = pd.DataFrame(result.get("ablations", []))
        if not ablations.empty:
            st.dataframe(ablations, width="stretch", hide_index=True)
        correlations = result.get("correlations", {})
        if correlations:
            components = ["R", "W", "D", "S"]
            matrix = pd.DataFrame(1.0, index=components, columns=components)
            for key, value in correlations.items():
                left, right = key.split("_", maxsplit=1)
                matrix.loc[left, right] = value
                matrix.loc[right, left] = value
            heatmap = px.imshow(
                matrix,
                text_auto=".2f",
                color_continuous_scale="RdBu_r",
                zmin=-1,
                zmax=1,
                title="Pressure-component correlation",
            )
            st.plotly_chart(heatmap, width="stretch")
        if state_path.is_file():
            states = _read_parquet(str(state_path), state_path.stat().st_mtime)
            component_columns = ["R", "W", "D", "S"]
            if not states.empty:
                distribution = states[component_columns].melt(
                    var_name="component", value_name="value"
                )
                distribution = distribution.loc[distribution["value"].notna()]
                component_chart = px.violin(
                    distribution,
                    x="component",
                    y="value",
                    box=True,
                    points=False,
                    title="Observed pressure-component distributions",
                    color="component",
                )
                st.plotly_chart(component_chart, width="stretch")
    else:
        st.info("No saved pressure-model validation report is available for this run.")
    if state_path.is_file():
        states = _read_parquet(str(state_path), state_path.stat().st_mtime)
        if not states.empty:
            chart = px.histogram(
                states.loc[states["pressure_score"].notna()],
                x="pressure_score",
                nbins=25,
                title="Observed live-chase pressure-score distribution",
                color_discrete_sequence=["#E91E8C"],
            )
            st.plotly_chart(chart, width="stretch")


def _ranking_page(role: str, manifest: dict, audit: dict | None) -> pd.DataFrame | None:
    title = "Batter Rankings" if role == "batter" else "Bowler Rankings"
    st.title(title)
    exploratory_run = _latest_exploratory_run()
    if exploratory_run is None:
        st.info("No saved exploratory rankings are available.")
        return None
    run_dir, exploratory_manifest = exploratory_run
    rankings_dir = run_dir / "rankings"
    path = rankings_dir / f"{role}_full_rankings.csv"
    top_path = rankings_dir / f"top_10_{role}s.csv"
    st.caption(
        "EXPLORATORY results use assumptions that are not source-confirmed; they are not "
        "validated rankings."
    )
    st.caption(
        f"Exploratory run {exploratory_manifest.get('run_id', run_dir.name)} · "
        f"Pressure validation: "
        f"{(exploratory_manifest.get('pressure_validation') or {}).get('status', 'see report')}"
    )
    assumption_status = _existing_json(
        run_dir / "reports" / "exploratory_assumption_status.json"
    )
    if assumption_status is not None:
        with st.expander("Exploratory assumptions and unresolved source evidence"):
            st.json(assumption_status, expanded=False)
    if top_path.is_file():
        top_frame = _existing_csv(top_path)
        if top_frame is not None:
            top_frame = _top10_rows(top_frame)
            st.markdown(f"#### EXPLORATORY Top 10 {role}s")
            if top_frame.empty:
                st.info("The saved leaderboard has no rows with a valid Top-10 rank.")
            else:
                st.dataframe(
                    top_frame[_top10_columns(role, top_frame)],
                    width="stretch",
                    hide_index=True,
                )
                st.download_button(
                    f"Download EXPLORATORY Top 10 {role}s",
                    top_frame.to_csv(index=False).encode("utf-8"),
                    file_name=top_path.name,
                    mime="text/csv",
                    key=f"{role}-exploratory-top10",
                )
    if role == "batter":
        stability_path = run_dir / "rankings" / "stability_adjusted_top10.csv"
        stability = _existing_csv(stability_path)
        if stability is not None and "role" in stability.columns:
            batter_stability = stability.loc[stability["role"].eq("batter")]
            if not batter_stability.empty:
                st.markdown("#### Existing stability-adjusted batter Top 10")
                st.caption(
                    "This is the saved robustness output; it does not replace the baseline "
                    "exploratory ranking."
                )
                st.dataframe(
                    batter_stability,
                    width="stretch",
                    hide_index=True,
                )
    mapping_summary_path = run_dir / "reports" / "scoring_mapping_sensitivity_summary.csv"
    mapping_summary = _existing_csv(mapping_summary_path)
    if mapping_summary is not None:
        role_summary = mapping_summary.loc[mapping_summary["ranking_track"].eq(role)]
        if not role_summary.empty:
            st.markdown("#### Hypothetical mapping sensitivity")
            st.caption(
                "Alternative mappings are hypothetical what-if scenarios; they are not "
                "source-confirmed and are not used in the baseline ranking."
            )
            st.dataframe(role_summary, width="stretch", hide_index=True)
    st.markdown(f"#### Full EXPLORATORY {role} rankings")
    frame = _existing_csv(path)
    if frame is None:
        st.info("Ranking exports have not been generated.")
        return None
    if st.button("Reset filters", key=f"{role}-reset"):
        st.session_state[f"{role}-search"] = ""
        st.rerun()
    search = st.text_input("Search by player name or ID", key=f"{role}-search").strip().casefold()
    if search:
        text = frame.get("player_name", pd.Series("", index=frame.index)).fillna("").astype(str)
        player_column = "striker_id" if role == "batter" else "bowler_id"
        identifiers = frame.get(player_column, pd.Series("", index=frame.index)).astype(str)
        frame = frame.loc[
            text.str.casefold().str.contains(search)
            | identifiers.str.casefold().str.contains(search)
        ]
    if "comparison_group" in frame.columns:
        groups = sorted(frame["comparison_group"].dropna().astype(str).unique())
        selection = st.multiselect("Competition comparison group", groups, default=groups)
        frame = frame.loc[frame["comparison_group"].astype(str).isin(selection)]
    elif "comparison_context" in frame.columns:
        contexts = frame["comparison_context"].fillna("").astype(str).str.split(",")
        groups = sorted({item.strip() for values in contexts for item in values if item.strip()})
        selection = st.multiselect("Competition comparison group", groups, default=groups)
        frame = frame.loc[
            contexts.map(
                lambda values: bool(set(selection).intersection(item.strip() for item in values))
            )
        ]
    sort_column = "rank" if "rank" in frame else frame.columns[0]
    st.dataframe(
        frame.sort_values(sort_column, na_position="last"),
        width="stretch",
        hide_index=True,
    )
    if "rank" in frame and "composite_score" in frame:
        ranked = frame.loc[pd.to_numeric(frame["rank"], errors="coerce").le(10)].sort_values(
            "rank", ascending=True
        )
        if not ranked.empty:
            plot = px.bar(
                ranked,
                x="composite_score",
                y="player_name" if "player_name" in ranked else ranked.columns[0],
                orientation="h",
                title=f"Top {role} composite scores",
                color_discrete_sequence=["#17479E" if role == "bowler" else "#E91E8C"],
            )
            st.plotly_chart(plot, width="stretch")
    if role == "batter" and {
        "pressure_strike_rate_shrunk",
        "consistency",
        "pressure_balls",
    }.issubset(frame.columns):
        scatter = px.scatter(
            frame,
            x="pressure_strike_rate_shrunk",
            y="consistency",
            size="pressure_balls",
            hover_name="player_name" if "player_name" in frame else None,
            title="Pressure strike rate vs ball-weighted consistency",
            labels={
                "pressure_strike_rate_shrunk": "Shrunk pressure strike rate",
                "consistency": "Ball-weighted consistency",
                "pressure_balls": "Pressure balls",
            },
            color_discrete_sequence=["#E91E8C"],
        )
        st.plotly_chart(scatter, width="stretch")
    if role == "bowler" and {
        "pressure_economy_shrunk",
        "consistency",
        "legal_pressure_balls",
    }.issubset(frame.columns):
        scatter = px.scatter(
            frame,
            x="pressure_economy_shrunk",
            y="consistency",
            size="legal_pressure_balls",
            hover_name="player_name" if "player_name" in frame else None,
            title="Pressure economy vs ball-weighted consistency",
            labels={
                "pressure_economy_shrunk": "Shrunk pressure economy",
                "consistency": "Ball-weighted consistency",
                "legal_pressure_balls": "Legal pressure balls",
            },
            color_discrete_sequence=["#17479E"],
        )
        st.plotly_chart(scatter, width="stretch")
    if top_path.is_file():
        st.download_button(
            f"Download Top 10 {role}s",
            top_path.read_bytes(),
            file_name=top_path.name,
            mime="text/csv",
        )
    return frame


def _player_explorer(manifest: dict) -> None:
    st.title("Player Explorer")
    run = _latest_exploratory_run()
    if run is None:
        st.info("No completed exploratory ranking output is available for player profiles.")
        return
    run_dir, _ = run
    rankings_dir = run_dir / "rankings"
    states_path = run_dir / "processed" / "pressure_states.parquet"
    st.caption(
        "EXPLORATORY player metrics use assumptions that are not source-confirmed."
    )
    st.caption(f"Reading saved profiles and pressure states from {run_dir.name}.")

    batters = _existing_csv(rankings_dir / "batter_full_rankings.csv")
    bowlers = _existing_csv(rankings_dir / "bowler_full_rankings.csv")
    available_profiles = [frame for frame in [batters, bowlers] if frame is not None]
    if not available_profiles:
        st.info("No saved batter or bowler ranking files are available.")
        return
    profiles = pd.concat(available_profiles, ignore_index=True)
    if profiles.empty:
        st.info("No calculated player profiles are available.")
        return
    profiles["role"] = profiles["striker_id"].notna().map({True: "Batter", False: "Bowler"})
    profiles["player_id"] = profiles["striker_id"].fillna(profiles["bowler_id"])
    profiles["player_name"] = profiles.get("player_name", profiles["player_id"]).fillna(
        profiles["player_id"]
    )
    labels = profiles["player_name"].astype(str) + " · " + profiles["role"]
    selected = st.selectbox("Select a calculated player", labels.tolist())
    row = profiles.loc[labels.eq(selected)].iloc[0]
    st.subheader(str(row["player_name"]))
    st.caption(f"{row['role']} · player ID {row['player_id']}")
    if row["role"] == "Batter":
        summary_metrics = [
            ("Rank", row.get("rank")),
            ("Pressure runs", row.get("pressure_runs")),
            ("Pressure balls", row.get("pressure_balls")),
            ("Pressure SR", row.get("pressure_strike_rate")),
            ("Normal SR", row.get("normal_strike_rate")),
        ]
        pressure_key, normal_key, rate_label = (
            "pressure_strike_rate",
            "normal_strike_rate",
            "Strike rate",
        )
    else:
        summary_metrics = [
            ("Rank", row.get("rank")),
            ("Pressure wickets", row.get("pressure_wickets")),
            ("Pressure economy", row.get("pressure_economy")),
            ("Normal economy", row.get("normal_economy")),
            ("Legal pressure balls", row.get("legal_pressure_balls")),
        ]
        pressure_key, normal_key, rate_label = (
            "pressure_economy",
            "normal_economy",
            "Economy",
        )
    metric_columns = st.columns(len(summary_metrics))
    for column, (label, value) in zip(metric_columns, summary_metrics, strict=True):
        if pd.isna(value):
            column.metric(label, "—")
        elif label in {"Pressure SR", "Normal SR", "Pressure economy", "Normal economy"}:
            column.metric(label, f"{float(value):.2f}")
        elif label == "Rank":
            column.metric(label, f"{float(value):.0f}")
        else:
            column.metric(label, f"{float(value):,.0f}")
    rate_values = pd.to_numeric(
        pd.Series([row.get(pressure_key), row.get(normal_key)]), errors="coerce"
    )
    if rate_values.notna().all():
        comparison = pd.DataFrame(
            {"State": ["Pressure", "Normal"], rate_label: rate_values.to_numpy()}
        )
        chart = px.bar(
            comparison,
            x="State",
            y=rate_label,
            color="State",
            title=f"{rate_label}: pressure vs normal",
            color_discrete_map={"Pressure": "#E91E8C", "Normal": "#17479E"},
        )
        st.plotly_chart(chart, width="stretch")
    available = row.dropna().astype("string").to_frame("value")
    st.dataframe(available, width="stretch")
    if states_path.is_file():
        states = _read_parquet(str(states_path), states_path.stat().st_mtime)
        player_column = "striker_id" if row["role"] == "Batter" else "bowler_id"
        detail = states.loc[states[player_column].astype("string").eq(str(row["player_id"]))].copy()
        if not detail.empty:
            st.markdown("### Match and phase profile")
            if row["role"] == "Batter":
                detail["ball_faced"] = ~detail["extras_category"].eq("wide")
                detail["batter_runs"] = pd.to_numeric(
                    detail["batter_runs"], errors="coerce"
                ).fillna(0)
                detail["pressure_runs"] = detail["batter_runs"].where(detail["is_high_pressure"], 0)
                detail["pressure_balls"] = detail["ball_faced"] & detail["is_high_pressure"]
                profile = detail.groupby("match_id", as_index=False).agg(
                    pressure_runs=("pressure_runs", "sum"),
                    pressure_balls=("pressure_balls", "sum"),
                )
                profile["pressure_strike_rate"] = (
                    100 * profile["pressure_runs"] / profile["pressure_balls"].replace(0, pd.NA)
                )
                denominator = "pressure_balls"
                rate = "pressure_strike_rate"
            else:
                detail["is_wide"] = detail["extras_category"].eq("wide")
                detail["is_no_ball"] = detail["extras_category"].eq("no_ball")
                detail["legal_ball"] = ~(detail["is_wide"] | detail["is_no_ball"])
                charged = detail["is_wide"] | detail["is_no_ball"]
                detail["bowler_runs"] = pd.to_numeric(
                    detail["batter_runs"], errors="coerce"
                ).fillna(0) + (
                    pd.to_numeric(detail["extras_1"], errors="coerce").fillna(0)
                    + pd.to_numeric(detail["extras_2"], errors="coerce").fillna(0)
                ).where(charged, 0)
                detail["pressure_runs"] = detail["bowler_runs"].where(detail["is_high_pressure"], 0)
                detail["pressure_balls"] = detail["legal_ball"] & detail["is_high_pressure"]
                profile = detail.groupby("match_id", as_index=False).agg(
                    pressure_runs=("pressure_runs", "sum"),
                    pressure_balls=("pressure_balls", "sum"),
                )
                profile["pressure_economy"] = (
                    6 * profile["pressure_runs"] / profile["pressure_balls"].replace(0, pd.NA)
                )
                denominator = "pressure_balls"
                rate = "pressure_economy"
            st.dataframe(profile, width="stretch", hide_index=True)
            trend = px.line(
                profile,
                x="match_id",
                y=rate,
                hover_data=[denominator],
                markers=True,
                title=f"Match-level {rate.replace('_', ' ')} (exposure shown on hover)",
            )
            st.plotly_chart(trend, width="stretch")
            phase_profile = (
                detail.loc[detail["is_high_pressure"]]
                .groupby("phase", as_index=False)
                .agg(
                    pressure_runs=("pressure_runs", "sum"), pressure_balls=("pressure_balls", "sum")
                )
            )
            if not phase_profile.empty:
                phase_profile["rate"] = (
                    100
                    * phase_profile["pressure_runs"]
                    / phase_profile["pressure_balls"].replace(0, pd.NA)
                    if row["role"] == "Batter"
                    else 6
                    * phase_profile["pressure_runs"]
                    / phase_profile["pressure_balls"].replace(0, pd.NA)
                )
                st.dataframe(phase_profile, width="stretch", hide_index=True)
        st.caption(
            "Ball-by-ball matchup fields are not included in the published canonical profile."
        )


def _robustness_page(manifest: dict) -> None:
    st.title("Robustness")
    run = _latest_exploratory_run()
    if run is None:
        st.info("No saved robustness outputs are available.")
        return
    run_dir, _ = run
    rankings_dir = run_dir / "rankings"
    st.caption(
        "EXPLORATORY robustness outputs describe the assumption-based rankings; "
        "they do not scientifically validate them."
    )
    filenames = [
        "batter_sensitivity.csv",
        "bowler_sensitivity.csv",
        "scenario_stability.csv",
        "bootstrap_results.csv",
        "batter_bootstrap_summary.csv",
        "bowler_bootstrap_summary.csv",
        "stability_adjusted_top10.csv",
    ]
    for filename in filenames:
        path = rankings_dir / filename
        if path.is_file():
            st.markdown(f"#### {filename.replace('_', ' ').replace('.csv', '').title()}")
            st.dataframe(
                _read_csv(str(path), path.stat().st_mtime),
                width="stretch",
                hide_index=True,
            )
        elif filename == "scenario_stability.csv":
            st.caption(
                "Full robustness has not been run. Use the pipeline's --full-robustness option."
            )


def _data_quality(audit: dict | None, config) -> None:
    st.title("Data Quality & Methodology")
    _upload_and_run(config)
    st.info(
        "This project presents exploratory results only. The scoring mappings are assumptions "
        "and are not confirmed by an authoritative source."
    )
    exploratory_manifests = _exploratory_runs()
    st.markdown("### Saved exploratory results")
    if not exploratory_manifests:
        st.caption("No exploratory runs have been recorded.")
    for run_dir, manifest in exploratory_manifests:
        label = (
            f"EXPLORATORY — {manifest.get('status', 'UNKNOWN')} — "
            f"{manifest.get('run_id', run_dir.name)}"
        )
        with st.expander(label):
            st.warning(
                "These results depend on selected assumptions and must not be presented as "
                "source-validated rankings."
            )
            assumption_status_path = run_dir / "reports" / "exploratory_assumption_status.json"
            if assumption_status_path.is_file():
                st.markdown("#### Assumption and validation status")
                st.json(_existing_json(assumption_status_path) or {}, expanded=False)
            pressure_path = run_dir / "reports" / "pressure_validation.json"
            if pressure_path.is_file():
                pressure = _existing_json(pressure_path) or {}
                st.markdown("#### Pressure validation")
                st.metric("Exploratory pressure status", pressure.get("status", "UNKNOWN"))
                st.json(pressure.get("summary", {}), expanded=False)
            for filename in ["top_10_batters.csv", "top_10_bowlers.csv"]:
                path = run_dir / "rankings" / filename
                if path.is_file():
                    st.markdown(f"**EXPLORATORY: {filename.replace('_', ' ').title()}**")
                    st.dataframe(
                        _read_csv(str(path), path.stat().st_mtime),
                        width="stretch",
                        hide_index=True,
                    )
                    st.download_button(
                        f"Download EXPLORATORY {filename}",
                        path.read_bytes(),
                        file_name=filename,
                        mime="text/csv",
                        key=f"exploratory-{run_dir.name}-{filename}",
                    )
            mapping_summary_path = run_dir / "reports" / "scoring_mapping_sensitivity_summary.csv"
            if mapping_summary_path.is_file():
                st.markdown("#### Hypothetical scoring-mapping sensitivity")
                st.caption(
                    "These alternative mappings are hypothetical what-if scenarios. They are "
                    "not source-confirmed and are not used in the baseline rankings."
                )
                st.dataframe(
                    _read_csv(str(mapping_summary_path), mapping_summary_path.stat().st_mtime),
                    width="stretch",
                    hide_index=True,
                )
                st.download_button(
                    "Download mapping sensitivity summary",
                    mapping_summary_path.read_bytes(),
                    file_name=mapping_summary_path.name,
                    mime="text/csv",
                    key=f"mapping-summary-{run_dir.name}",
                )
            mapping_detail_path = run_dir / "rankings" / "scoring_mapping_sensitivity.csv"
            if mapping_detail_path.is_file():
                mapping_detail = _read_csv(
                    str(mapping_detail_path), mapping_detail_path.stat().st_mtime
                )
                if "significant_change" in mapping_detail:
                    changed = mapping_detail.loc[
                        mapping_detail["significant_change"].astype(str).str.lower().eq("true")
                    ]
                    st.dataframe(
                        changed.head(30),
                        width="stretch",
                        hide_index=True,
                    )
                st.download_button(
                    "Download full mapping sensitivity details",
                    mapping_detail_path.read_bytes(),
                    file_name=mapping_detail_path.name,
                    mime="text/csv",
                    key=f"mapping-details-{run_dir.name}",
                )
            mapping_report_path = run_dir / "reports" / "scoring_mapping_sensitivity.md"
            if mapping_report_path.is_file():
                st.markdown(mapping_report_path.read_text(encoding="utf-8"))
    if audit is None:
        st.info("No data audit has been generated yet.")
        return
    report_dir = _active_run_report_dir()
    if report_dir is None:
        st.info("No completed exploratory run reports are available.")
        return
    findings = pd.DataFrame(audit.get("findings", []))
    st.metric("Source-audit findings", len(findings))
    machine_status = _existing_json(report_dir / "audit_status.json") or {}
    source_evidence = machine_status.get(
        "source_evidence",
        audit.get("checks", {}).get(
            "source_evidence", audit.get("checks", {}).get("gate_statuses", [])
        ),
    )
    if source_evidence:
        st.markdown("### Source-evidence review")
        st.caption(
            "Confirmed, inferred, unresolved, and excluded evidence are shown separately. "
            "Unconfirmed source mappings remain exploratory assumptions; they do not gate results."
        )
        st.dataframe(
            pd.DataFrame(source_evidence).rename(columns={"gate_id": "evidence_topic"}),
            width="stretch",
            hide_index=True,
        )
    confirmed_exclusions = machine_status.get("confirmed_exclusions", {})
    super_over_exclusions = confirmed_exclusions.get("super_overs", {})
    revised_exclusions = confirmed_exclusions.get("revised_conditions", {})
    if confirmed_exclusions:
        st.markdown("### Exclusions retained")
        first, second = st.columns(2)
        first.metric(
            "Confirmed Super Over groups",
            super_over_exclusions.get("innings_groups", 0),
        )
        second.metric(
            "Revised-condition matches excluded",
            revised_exclusions.get("matches", 0),
        )
        st.caption(
            f"Super Overs ({super_over_exclusions.get('status', 'UNASSESSED')}): "
            f"{super_over_exclusions.get('delivery_rows', 0)} delivery rows across "
            f"{super_over_exclusions.get('matches', 0)} matches. "
            f"{super_over_exclusions.get('reason', '')}"
        )
        st.caption(
            f"Revised conditions ({revised_exclusions.get('status', 'UNASSESSED')}): "
            f"{revised_exclusions.get('reason', '')}"
        )
        super_over_path = report_dir / "super_over_reconciliation.csv"
        revised_path = report_dir / "revised_target_exclusions.csv"
        with st.expander("View confirmed Super Over innings and evidence"):
            frame = _existing_csv(super_over_path)
            if frame is not None:
                st.dataframe(frame, width="stretch", hide_index=True)
        with st.expander("View revised-condition matches and exclusion reasons"):
            frame = _existing_csv(revised_path)
            if frame is not None:
                st.dataframe(frame, width="stretch", hide_index=True)
    metric_dependencies = machine_status.get("metric_dependencies", [])
    if metric_dependencies:
        st.markdown("### Source evidence by metric")
        st.caption(
            "These labels describe source-evidence limits for exploratory metrics, not whether "
            "the saved rankings were calculated."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "metric": metric["metric"],
                        "ranking_track": metric["ranking_track"],
                        "evidence_topics": ", ".join(metric["required_gates"]),
                        "status": metric["status"],
                        "unconfirmed_evidence": ", ".join(
                            metric["unconfirmed_dependencies"]
                        ),
                        "excluded_dependencies": ", ".join(metric["excluded_dependencies"]),
                    }
                    for metric in metric_dependencies
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    impact_path = report_dir / "audit_impact_matrix.csv"
    impact = _existing_csv(impact_path)
    if impact is not None:
        with st.expander("View metric-level audit impact matrix"):
            st.dataframe(impact, width="stretch", hide_index=True)
    findings = pd.DataFrame(audit.get("findings", []))
    priority_findings = (
        findings.loc[findings["severity"].eq("high-priority")]
        if not findings.empty
        else findings
    )
    warnings = findings.loc[findings["severity"].eq("warning")] if not findings.empty else findings
    first, second = st.columns(2)
    first.metric("High-priority diagnostics", len(priority_findings))
    second.metric("Warnings", len(warnings))
    if not findings.empty:
        st.dataframe(findings, width="stretch", hide_index=True)
    tables = audit.get("tables", {})
    if tables:
        st.markdown("### Source file inventory")
        st.dataframe(
            pd.DataFrame([{"table": name, **details} for name, details in tables.items()]),
            width="stretch",
            hide_index=True,
        )
    schemas = audit.get("schemas", {})
    if schemas:
        with st.expander("Detected columns, nulls and distinct counts"):
            for table, columns in schemas.items():
                st.markdown(f"**{table}**")
                st.dataframe(pd.DataFrame(columns), width="stretch", hide_index=True)
    checks = audit.get("checks", {})
    if checks:
        with st.expander("Join coverage and validation evidence"):
            st.json(checks, expanded=False)
    report_path = report_dir / "data_audit.md"
    if report_path.is_file():
        st.download_button(
            "Download audit report",
            report_path.read_bytes(),
            file_name=report_path.name,
            mime="text/markdown",
        )
    download_files = [
        ("Source investigation (MD)", "data_investigation.md", "text/markdown"),
        ("Scoring dictionary (MD)", "data_dictionary.md", "text/markdown"),
        ("Investigation summary (PDF)", "data_investigation.pdf", "application/pdf"),
        ("Affected deliveries (CSV)", "investigation_records.csv", "text/csv"),
        ("Raw-value frequencies (CSV)", "source_value_frequencies.csv", "text/csv"),
        ("Dismissal reconciliation (CSV)", "dismissal_reconciliation.csv", "text/csv"),
        ("Super-over reconciliation (CSV)", "super_over_reconciliation.csv", "text/csv"),
        ("Revised-match exclusions (CSV)", "revised_target_exclusions.csv", "text/csv"),
        ("Source evidence diagnostics (JSON)", "audit_status.json", "application/json"),
        ("Audit impact matrix (CSV)", "audit_impact_matrix.csv", "text/csv"),
        ("Audit impact matrix (MD)", "audit_impact_matrix.md", "text/markdown"),
        ("Manual confirmation sheet (CSV)", "manual_data_confirmation.csv", "text/csv"),
        ("Innings reconciliation (CSV)", "innings_reconciliation.csv", "text/csv"),
        ("Scorecard reconciliation (CSV)", "scorecard_reconciliation.csv", "text/csv"),
        ("Scoring semantics evidence (MD)", "scoring_semantics_evidence.md", "text/markdown"),
    ]
    existing_downloads = [
        (label, report_dir / filename, mime)
        for label, filename, mime in download_files
        if (report_dir / filename).is_file()
    ]
    if existing_downloads:
        st.markdown("### Investigation downloads")
        columns = st.columns(2)
        for index, (label, path, mime) in enumerate(existing_downloads):
            columns[index % len(columns)].download_button(
                label,
                path.read_bytes(),
                file_name=path.name,
                mime=mime,
                key=f"download-{path.name}",
                width="stretch",
            )
    for label, path, mime in [
        (
            "Scoring decisions (MD)",
            PROJECT_DIR / "docs" / "scoring_decisions.md",
            "text/markdown",
        ),
        (
            "Exploratory assumptions (MD)",
            PROJECT_DIR / "docs" / "exploratory_assumptions.md",
            "text/markdown",
        ),
        (
            "Analysis configuration (YAML)",
            PROJECT_DIR / "config" / "default.yaml",
            "text/yaml",
        ),
    ]:
        if path.is_file():
            st.download_button(
                label,
                path.read_bytes(),
                file_name=path.name,
                mime=mime,
                key=f"download-{path.name}",
                width="stretch",
            )


def main() -> None:
    config = load_config(PROJECT_DIR / "config" / "default.yaml")
    manifest = _run_status()
    audit = _audit()
    page = st.sidebar.radio(
        "Navigation",
        [
            "Overview",
            "Batting Under Pressure",
            "Bowling Under Pressure",
            "Coach Insights",
            "Pressure Model",
            "Player Explorer",
            "Technical Rankings",
            "Robustness",
            "Data Quality & Methodology",
        ],
    )
    st.sidebar.markdown("---")
    st.sidebar.caption("Exploratory rankings · assumption-based")
    st.sidebar.caption(f"Config · {config.version}")
    if page == "Overview":
        _overview(audit, manifest)
    elif page == "Batting Under Pressure":
        _coach_rankings("batter", manifest)
    elif page == "Bowling Under Pressure":
        _coach_rankings("bowler", manifest)
    elif page == "Coach Insights":
        _coach_insights(manifest)
    elif page == "Pressure Model":
        _pressure_page(manifest, audit)
    elif page == "Player Explorer":
        _player_explorer(manifest)
    elif page == "Technical Rankings":
        role = st.sidebar.radio(
            "Ranking type",
            ["Batter", "Bowler"],
            key="technical-ranking-role",
        )
        _ranking_page(role.lower(), manifest, audit)
    elif page == "Robustness":
        _robustness_page(manifest)
    else:
        _data_quality(audit, config)


if __name__ == "__main__":
    main()
