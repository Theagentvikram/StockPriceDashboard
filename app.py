"""
app.py — StockScreener Dashboard

Streamlit UI with:
- Sidebar: market toggle (NSE / NYSE), filter controls, theme toggle, refresh button
- Market-hours banner (IST for NSE, ET for NYSE)
- KPI metrics row: scanned / passed / shown
- Ranked data table (top 25)
- Score distribution chart
- 60s auto-refresh via streamlit-autorefresh
- Light / Dark mode toggle
"""

import datetime as dt

import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from screener import run_screen
from universe import get_tickers

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="StockScreener — Live Market Scanner",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Theme state
# ---------------------------------------------------------------------------
if "theme" not in st.session_state:
    st.session_state.theme = "dark"

is_dark = st.session_state.theme == "dark"

# ---------------------------------------------------------------------------
# Theme palettes
# ---------------------------------------------------------------------------
DARK = {
    "bg_primary": "#020617",
    "bg_card": "#0E1223",
    "bg_card_hover": "#131836",
    "text_primary": "#F8FAFC",
    "text_muted": "#94A3B8",
    "accent_green": "#22C55E",
    "accent_red": "#EF4444",
    "accent_amber": "#F59E0B",
    "accent_blue": "#3B82F6",
    "border": "#1E293B",
    "glow_green": "rgba(34, 197, 94, 0.15)",
    "glow_blue": "rgba(59, 130, 246, 0.12)",
    "header_grad": "linear-gradient(135deg, #0F172A 0%, #1E293B 50%, #0F172A 100%)",
    "title_grad": "linear-gradient(135deg, #F8FAFC, #94A3B8)",
    "plotly_template": "plotly_dark",
    "plotly_paper": "#020617",
    "plotly_plot": "#0E1223",
    "plotly_grid": "#1E293B",
    "plotly_font": "#F8FAFC",
    "plotly_text": "#94A3B8",
    "scatter_line": "#1E293B",
}

LIGHT = {
    "bg_primary": "#F8FAFC",
    "bg_card": "#FFFFFF",
    "bg_card_hover": "#F1F5F9",
    "text_primary": "#0F172A",
    "text_muted": "#64748B",
    "accent_green": "#16A34A",
    "accent_red": "#DC2626",
    "accent_amber": "#D97706",
    "accent_blue": "#2563EB",
    "border": "#E2E8F0",
    "glow_green": "rgba(22, 163, 74, 0.10)",
    "glow_blue": "rgba(37, 99, 235, 0.08)",
    "header_grad": "linear-gradient(135deg, #FFFFFF 0%, #F1F5F9 50%, #FFFFFF 100%)",
    "title_grad": "linear-gradient(135deg, #0F172A, #334155)",
    "plotly_template": "plotly_white",
    "plotly_paper": "#F8FAFC",
    "plotly_plot": "#FFFFFF",
    "plotly_grid": "#E2E8F0",
    "plotly_font": "#0F172A",
    "plotly_text": "#64748B",
    "scatter_line": "#E2E8F0",
}

T = DARK if is_dark else LIGHT

# ---------------------------------------------------------------------------
# Custom CSS — adaptive theme
# ---------------------------------------------------------------------------
st.markdown(f"""
<style>
/* ── Import Fira Sans / Fira Code ── */
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Fira+Sans:wght@300;400;500;600;700&display=swap');

/* ── Root variables (set by Python theme toggle) ── */
:root {{
    --bg-primary: {T["bg_primary"]};
    --bg-card: {T["bg_card"]};
    --bg-card-hover: {T["bg_card_hover"]};
    --text-primary: {T["text_primary"]};
    --text-muted: {T["text_muted"]};
    --accent-green: {T["accent_green"]};
    --accent-red: {T["accent_red"]};
    --accent-amber: {T["accent_amber"]};
    --accent-blue: {T["accent_blue"]};
    --border: {T["border"]};
    --glow-green: {T["glow_green"]};
    --glow-blue: {T["glow_blue"]};
}}

/* ── Global font ── */
html, body, [class*="css"] {{
    font-family: 'Fira Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
}}

/* ── Override Streamlit backgrounds for light mode ── */
{"" if is_dark else """
.stApp, [data-testid="stAppViewContainer"], .main,
[data-testid="stAppViewContainer"] > section,
[data-testid="stMain"] {
    background-color: #F8FAFC !important;
    color: #0F172A !important;
}

/* Sidebar background */
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div,
[data-testid="stSidebar"] > div > div,
[data-testid="stSidebar"] section {
    background-color: #FFFFFF !important;
    color: #0F172A !important;
}

/* ALL sidebar text — nuclear override */
[data-testid="stSidebar"] * {
    color: #334155 !important;
}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] h4,
[data-testid="stSidebar"] h5,
[data-testid="stSidebar"] h6 {
    color: #0F172A !important;
}

/* Radio buttons */
[data-testid="stSidebar"] [role="radiogroup"] label,
[data-testid="stSidebar"] [role="radiogroup"] label span,
[data-testid="stSidebar"] [role="radiogroup"] label p,
[data-testid="stSidebar"] [role="radiogroup"] label div,
[data-testid="stSidebar"] .stRadio label {
    color: #1E293B !important;
}

/* Slider labels and values */
[data-testid="stSidebar"] [data-testid="stSlider"] label,
[data-testid="stSidebar"] [data-testid="stSlider"] div,
[data-testid="stSidebar"] [data-testid="stSlider"] span,
[data-testid="stSidebar"] [data-testid="stThumbValue"],
[data-testid="stSidebar"] .stSlider label {
    color: #334155 !important;
}

/* Slider track for light mode */
[data-testid="stSidebar"] [data-testid="stSlider"] [role="slider"] {
    background-color: #16A34A !important;
}

/* Horizontal rule in sidebar */
[data-testid="stSidebar"] hr {
    border-color: #E2E8F0 !important;
}

/* Main content text overrides */
.main p, .main span, .main div, .main label {
    color: #0F172A;
}
.main [data-testid="stDataFrame"] {
    color: #0F172A !important;
}
"""}


/* ── Main container ── */
.main .block-container {{
    padding-top: 1.5rem;
    max-width: 1400px;
}}

/* ── Header gradient bar ── */
.header-bar {{
    background: {T["header_grad"]};
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1.25rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
}}
.header-bar h1 {{
    font-size: 1.65rem;
    font-weight: 700;
    margin: 0;
    background: {T["title_grad"]};
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.5px;
}}
.header-bar .subtitle {{
    font-size: 0.82rem;
    color: var(--text-muted);
    margin: 0.15rem 0 0 0;
}}

/* ── Market banner ── */
.market-banner {{
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.55rem 1.1rem;
    border-radius: 8px;
    font-size: 0.82rem;
    font-weight: 500;
    white-space: nowrap;
}}
.market-open {{
    background: rgba(34, 197, 94, 0.12);
    border: 1px solid rgba(34, 197, 94, 0.25);
    color: var(--accent-green);
}}
.market-closed {{
    background: rgba(239, 68, 68, 0.10);
    border: 1px solid rgba(239, 68, 68, 0.22);
    color: var(--accent-red);
}}
.pulse-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
    animation: pulse 2s ease-in-out infinite;
}}
.pulse-green {{ background: var(--accent-green); }}
.pulse-red {{ background: var(--accent-red); }}
@keyframes pulse {{
    0%, 100% {{ opacity: 1; transform: scale(1); }}
    50% {{ opacity: 0.4; transform: scale(0.8); }}
}}

/* ── KPI metric cards ── */
.kpi-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 0.9rem;
    margin-bottom: 1.25rem;
}}
.kpi-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem 1.2rem;
    transition: all 0.2s ease;
}}
.kpi-card:hover {{
    border-color: rgba(59, 130, 246, 0.3);
    box-shadow: 0 0 20px var(--glow-blue);
    transform: translateY(-1px);
}}
.kpi-label {{
    font-size: 0.72rem;
    font-weight: 500;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 0.35rem;
}}
.kpi-value {{
    font-family: 'Fira Code', monospace;
    font-size: 1.6rem;
    font-weight: 600;
    color: var(--text-primary);
}}
.kpi-value.green {{ color: var(--accent-green); }}
.kpi-value.amber {{ color: var(--accent-amber); }}
.kpi-value.blue {{ color: var(--accent-blue); }}

/* ── Data table wrapper ── */
.table-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.6rem;
    flex-wrap: wrap;
    gap: 0.5rem;
}}
.table-title {{
    font-size: 1.05rem;
    font-weight: 600;
    color: var(--text-primary);
}}
.table-badge {{
    font-size: 0.72rem;
    font-weight: 500;
    padding: 0.25rem 0.65rem;
    border-radius: 20px;
    background: rgba(34, 197, 94, 0.12);
    color: var(--accent-green);
    border: 1px solid rgba(34, 197, 94, 0.2);
}}

/* ── Streamlit dataframe styling ── */
[data-testid="stDataFrame"] {{
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
}}
[data-testid="stDataFrame"] table {{
    font-family: 'Fira Code', monospace !important;
    font-size: 0.82rem !important;
}}

/* ── Sidebar styling ── */
[data-testid="stSidebar"] {{
    border-right: 1px solid var(--border);
}}

/* ── Progress bar color ── */
.stProgress > div > div > div {{
    background-color: var(--accent-green) !important;
}}

/* ── Refresh timer badge ── */
.refresh-badge {{
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.75rem;
    color: var(--text-muted);
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.3rem 0.7rem;
}}

/* ── Remove default streamlit padding/gaps ── */
.stAlert {{ border-radius: 10px !important; }}

/* ── Section divider ── */
.section-divider {{
    border: none;
    height: 1px;
    background: var(--border);
    margin: 1.2rem 0;
}}

/* ── Theme toggle button ── */
.theme-toggle {{
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.8rem;
    font-weight: 500;
    color: var(--text-muted);
    cursor: pointer;
}}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Auto-refresh (60 s)
# ---------------------------------------------------------------------------
st_autorefresh(interval=60_000, limit=None, key="auto_refresh")

# ---------------------------------------------------------------------------
# Market hours logic
# ---------------------------------------------------------------------------

_MARKET_CONFIG = {
    "IN": {
        "name": "NSE",
        "tz_name": "Asia/Kolkata",
        "tz_label": "IST",
        "open_h": 9, "open_m": 15,
        "close_h": 15, "close_m": 30,
    },
    "US": {
        "name": "NYSE",
        "tz_name": "US/Eastern",
        "tz_label": "ET",
        "open_h": 9, "open_m": 30,
        "close_h": 16, "close_m": 0,
    },
}


def _is_market_open(market: str) -> tuple[bool, str, str]:
    """
    Check if the market is currently open.
    Returns (is_open, status_text, local_time_str).
    """
    cfg = _MARKET_CONFIG[market]

    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    tz = ZoneInfo(cfg["tz_name"])
    now = dt.datetime.now(tz)
    weekday = now.weekday()  # 0=Mon … 6=Sun

    open_time = now.replace(hour=cfg["open_h"], minute=cfg["open_m"], second=0, microsecond=0)
    close_time = now.replace(hour=cfg["close_h"], minute=cfg["close_m"], second=0, microsecond=0)

    local_str = now.strftime(f"%I:%M %p {cfg['tz_label']}  •  %a, %d %b %Y")

    # Weekend
    if weekday >= 5:
        return False, "Market closed — Weekend", local_str

    # Before open
    if now < open_time:
        mins = int((open_time - now).total_seconds() // 60)
        h, m = divmod(mins, 60)
        return False, f"Pre-market — Opens in {h}h {m}m", local_str

    # After close
    if now >= close_time:
        return False, "Market closed — After hours", local_str

    # During trading
    mins = int((close_time - now).total_seconds() // 60)
    h, m = divmod(mins, 60)
    return True, f"Market open — Closes in {h}h {m}m", local_str


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 🎯 Market & Filters")

    market = st.radio(
        "Market",
        options=["US", "IN"],
        format_func=lambda x: "🇺🇸  NYSE  (S&P 500)" if x == "US" else "🇮🇳  NSE  (Nifty 500)",
        horizontal=True,
        key="market_toggle",
    )

    st.markdown("---")
    st.markdown("##### Filter Thresholds")

    pe_thresh = st.slider("P/E below", min_value=5.0, max_value=50.0, value=20.0, step=1.0, key="pe")
    vol_thresh = st.slider("Volume ratio above", min_value=1.0, max_value=10.0, value=2.0, step=0.5, key="vol")
    rsi_thresh = st.slider("RSI(14) above", min_value=30.0, max_value=80.0, value=50.0, step=5.0, key="rsi")
    top_n = st.slider("Show top N results", min_value=5, max_value=50, value=25, step=5, key="topn")

    st.markdown("---")

    # Theme toggle
    col_theme1, col_theme2 = st.columns([1, 1])
    with col_theme1:
        if st.button("☀️ Light" if is_dark else "☀️ Light ✓", use_container_width=True,
                     type="secondary" if is_dark else "primary", key="light_btn"):
            st.session_state.theme = "light"
            st.rerun()
    with col_theme2:
        if st.button("🌙 Dark" if not is_dark else "🌙 Dark ✓", use_container_width=True,
                     type="secondary" if not is_dark else "primary", key="dark_btn"):
            st.session_state.theme = "dark"
            st.rerun()

    st.markdown("---")

    if st.button("🔄  Refresh Now", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown(
        '<div class="refresh-badge">⏱ Auto-refresh: 60s</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"Last refresh: {dt.datetime.now().strftime('%H:%M:%S')}")


# ---------------------------------------------------------------------------
# Header + Market Banner
# ---------------------------------------------------------------------------

is_open, status_text, local_time = _is_market_open(market)
exchange_name = _MARKET_CONFIG[market]["name"]

banner_cls = "market-open" if is_open else "market-closed"
dot_cls = "pulse-green" if is_open else "pulse-red"

st.markdown(f"""
<div class="header-bar">
    <div>
        <h1>StockScreener</h1>
        <p class="subtitle">Real-time stock scanner  •  {exchange_name} market</p>
    </div>
    <div class="market-banner {banner_cls}">
        <span class="pulse-dot {dot_cls}"></span>
        {status_text}  •  {local_time}
    </div>
</div>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Run screener
# ---------------------------------------------------------------------------

tickers = get_tickers(market, cap=50)

with st.spinner(f"Scanning {len(tickers)} {exchange_name} stocks…"):
    results, stats = run_screen(
        tickers=tickers,
        pe_threshold=pe_thresh,
        vol_threshold=vol_thresh,
        rsi_threshold=rsi_thresh,
        top_n=top_n,
    )

# ---------------------------------------------------------------------------
# KPI Metrics Row
# ---------------------------------------------------------------------------

st.markdown(f"""
<div class="kpi-row">
    <div class="kpi-card">
        <div class="kpi-label">Stocks Scanned</div>
        <div class="kpi-value blue">{stats['scanned']}</div>
    </div>
    <div class="kpi-card">
        <div class="kpi-label">Passed All Filters</div>
        <div class="kpi-value {'green' if stats['passed'] > 0 else 'amber'}">{stats['passed']}</div>
    </div>
    <div class="kpi-card">
        <div class="kpi-label">Showing Top</div>
        <div class="kpi-value green">{stats['shown']}</div>
    </div>
    <div class="kpi-card">
        <div class="kpi-label">Filter Criteria</div>
        <div class="kpi-value" style="font-size:0.85rem; line-height:1.5;">
            P/E &lt; {pe_thresh:.0f}<br>
            Vol &gt; {vol_thresh:.1f}×<br>
            RSI &gt; {rsi_thresh:.0f}
        </div>
    </div>
</div>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Results Table
# ---------------------------------------------------------------------------

st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

if results.empty:
    st.markdown(f"""
    <div style="text-align:center; padding: 3rem 1rem;">
        <div style="font-size: 3rem; margin-bottom: 0.5rem;">🔍</div>
        <h3 style="color: var(--text-muted); font-weight: 500;">No stocks match all filters</h3>
        <p style="color: var(--text-muted); font-size: 0.85rem;">
            Try relaxing the P/E, volume ratio, or RSI thresholds in the sidebar.
        </p>
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown(f"""
    <div class="table-header">
        <span class="table-title">🏆 Top {stats['shown']} Ranked Stocks</span>
        <span class="table-badge">Composite Score = 0.5×Vol + 0.3×RSI + 0.2×(1/PE)</span>
    </div>
    """, unsafe_allow_html=True)

    # Currency symbol
    curr = "₹" if market == "IN" else "$"

    # Format for display
    display_df = results.copy()
    display_df["Price"] = display_df["Price"].apply(lambda x: f"{curr}{x:,.2f}")
    display_df["P/E"] = display_df["P/E"].apply(lambda x: f"{x:.1f}")
    display_df["Vol Ratio"] = display_df["Vol Ratio"].apply(lambda x: f"{x:.2f}×")
    display_df["RSI(14)"] = display_df["RSI(14)"].apply(lambda x: f"{x:.1f}")
    display_df["Score"] = display_df["Score"].apply(lambda x: f"{x:.3f}")

    st.dataframe(
        display_df,
        width="stretch",
        height=min(36 * len(display_df) + 38, 950),
        column_config={
            "Ticker": st.column_config.TextColumn("Ticker", width="small"),
            "Company": st.column_config.TextColumn("Company", width="medium"),
            "Price": st.column_config.TextColumn("Price", width="small"),
            "P/E": st.column_config.TextColumn("P/E", width="small"),
            "Vol Ratio": st.column_config.TextColumn("Vol Ratio", width="small"),
            "RSI(14)": st.column_config.TextColumn("RSI(14)", width="small"),
            "Score": st.column_config.TextColumn("Score", width="small"),
        },
    )

    # ------------------------------------------------------------------
    # Chart: Score Distribution (horizontal bar)
    # ------------------------------------------------------------------
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    st.markdown('<div class="table-title">📊 Composite Score Distribution</div>', unsafe_allow_html=True)

    chart_df = results.sort_values("Score", ascending=True)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=chart_df["Ticker"],
        x=chart_df["Score"],
        orientation="h",
        marker=dict(
            color=chart_df["Score"],
            colorscale=[
                [0.0, "#94A3B8" if not is_dark else "#1E293B"],
                [0.3, "#3B82F6"],
                [0.6, "#22C55E"],
                [1.0, "#F59E0B"],
            ],
            line=dict(width=0),
            cornerradius=4,
        ),
        text=chart_df["Score"].apply(lambda x: f"{x:.3f}"),
        textposition="outside",
        textfont=dict(family="Fira Code", size=11, color=T["text_muted"]),
        hovertemplate="<b>%{y}</b><br>Score: %{x:.3f}<extra></extra>",
    ))

    fig.update_layout(
        template=T["plotly_template"],
        paper_bgcolor=T["plotly_paper"],
        plot_bgcolor=T["plotly_plot"],
        font=dict(family="Fira Sans", color=T["plotly_font"]),
        height=max(350, 30 * len(chart_df)),
        margin=dict(l=10, r=60, t=10, b=10),
        xaxis=dict(
            title="Composite Score",
            gridcolor=T["plotly_grid"],
            zeroline=False,
            title_font=dict(size=12, color=T["plotly_text"]),
        ),
        yaxis=dict(
            gridcolor=T["plotly_grid"],
            tickfont=dict(family="Fira Code", size=11),
        ),
        bargap=0.25,
    )

    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    # ------------------------------------------------------------------
    # Chart: RSI vs Volume Scatter
    # ------------------------------------------------------------------
    st.markdown('<div class="table-title">🔬 RSI vs Volume Ratio</div>', unsafe_allow_html=True)

    scatter_df = results.copy()
    scatter_df["Bubble"] = (1 / scatter_df["P/E"].astype(float)) * 300

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=scatter_df["RSI(14)"],
        y=scatter_df["Vol Ratio"],
        mode="markers+text",
        marker=dict(
            size=scatter_df["Bubble"].clip(8, 50),
            color=scatter_df["Score"],
            colorscale="Viridis" if is_dark else "Bluered",
            showscale=True,
            colorbar=dict(title="Score", tickfont=dict(size=10)),
            line=dict(width=1, color=T["scatter_line"]),
            opacity=0.85,
        ),
        text=scatter_df["Ticker"],
        textposition="top center",
        textfont=dict(family="Fira Code", size=9, color=T["text_muted"]),
        hovertemplate=(
            "<b>%{text}</b><br>"
            "RSI: %{x:.1f}<br>"
            "Vol Ratio: %{y:.2f}×<br>"
            "<extra></extra>"
        ),
    ))

    fig2.update_layout(
        template=T["plotly_template"],
        paper_bgcolor=T["plotly_paper"],
        plot_bgcolor=T["plotly_plot"],
        font=dict(family="Fira Sans", color=T["plotly_font"]),
        height=420,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(
            title="RSI (14)",
            gridcolor=T["plotly_grid"],
            zeroline=False,
            title_font=dict(size=12, color=T["plotly_text"]),
        ),
        yaxis=dict(
            title="Volume Ratio (× 20-day avg)",
            gridcolor=T["plotly_grid"],
            zeroline=False,
            title_font=dict(size=12, color=T["plotly_text"]),
        ),
    )

    st.plotly_chart(fig2, width="stretch", config={"displayModeBar": False})


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
st.markdown(
    f'<p style="text-align:center; color:{T["text_muted"]}; font-size:0.72rem;">'
    'StockScreener  •  Data: Yahoo Finance via yfinance  •  Not financial advice  •  '
    f'Built with Streamlit  •  Refresh interval: 60s'
    '</p>',
    unsafe_allow_html=True,
)
