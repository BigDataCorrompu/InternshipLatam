"""
════════════════════════════════════════════════════════════════════════════
InternshipLatam — Pipeline Health & Insights
════════════════════════════════════════════════════════════════════════════
End-to-end observability for the data pipeline: ingestion -> bronze ->
LLM enrichment -> staging -> silver.

Reads exclusively from the serving.* schema (Gold views defined in
010_pipeline_health_views.sql). No joins are performed here: all aggregation
logic lives in the database.

Caching: fingerprint-based invalidation (row counts + max(collected_at)),
with a 5-minute TTL on the fingerprint query itself.

Expected location: data_vis/views/insights.py
════════════════════════════════════════════════════════════════════════════
"""

import importlib.util
import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# ════════════════════════════════════════════════════════════════════
# Local module resolution
# ────────────────────────────────────────────────────────────────────
# The Database class is loaded by absolute path: the top-level `database/`
# SQL folder would otherwise shadow the `database.py` module on import.
# ════════════════════════════════════════════════════════════════════
_DB_PATH = Path(__file__).resolve().parents[2] / "ingestion" / "python" / "src" / "database.py"
_spec = importlib.util.spec_from_file_location("db_module", _DB_PATH)
_db_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_db_module)
Database = _db_module.Database


# ════════════════════════════════════════════════════════════════════
# Constants
# ════════════════════════════════════════════════════════════════════
ACCENT = "#800020"          # burgundy
OK_COLOR = "#2E7D32"
WARN_COLOR = "#ED6C02"
ERR_COLOR = "#C62828"
NEUTRAL = "#9E9E9E"

FINGERPRINT_TTL = 600       # 5 minutes
DATA_TTL = 3600             # 1 hour — invalidated earlier by the fingerprint

VIEWS = [
    "pipeline_funnel",
    "query_performance",
    "volume_over_time",
    "company_recovery",
    "company_recovery_detail",
    "skills_extraction_volume",
    "top_skills",
    "ingestion_freshness",
    "enrichment_quality",
    "blocked_offers",
    "geographic_coverage",
]


# ════════════════════════════════════════════════════════════════════
# Cached resources
# ════════════════════════════════════════════════════════════════════
@st.cache_resource
def get_db() -> Database:
    """Persistent Database object (HTTP to Neon).

    Same secrets section as dashboard.py: [database] in secrets.toml,
    unpacked straight into the constructor.
    """
    return Database(**st.secrets["database"])


# ════════════════════════════════════════════════════════════════════
# Data loading — fingerprint-based cache invalidation
# ════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=FINGERPRINT_TTL, show_spinner=False)
def get_data_fingerprint() -> str:
    """Cheap signature of the current pipeline state.

    Changes as soon as a row lands at any stage, which invalidates every
    cached DataFrame keyed on it.
    """
    db = get_db()
    rows = db.execute("SELECT * FROM serving.data_fingerprint")
    if not rows:
        return "empty"
    row = rows[0]
    return "|".join(str(row.get(k)) for k in sorted(row.keys()))


@st.cache_data(ttl=DATA_TTL, show_spinner=False)
def load_view(view_name: str, fingerprint: str) -> pd.DataFrame:
    """Load one serving.* view into a DataFrame.

    `fingerprint` is unused in the body: it only acts as a cache key.
    """
    db = get_db()
    rows = db.execute(f"SELECT * FROM serving.{view_name}")
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def load_all(fingerprint: str) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Load every view. A missing or broken view degrades gracefully."""
    frames, problems = {}, []
    for view in VIEWS:
        try:
            frames[view] = load_view(view, fingerprint)
        except Exception as exc:
            frames[view] = pd.DataFrame()
            problems.append(f"`serving.{view}` — {exc}")
    return frames, problems


# ════════════════════════════════════════════════════════════════════
# Defensive accessors
# ────────────────────────────────────────────────────────────────────
# A view in the database may lag behind the expected definition (SQL file
# not re-run yet). The page must degrade, not crash.
# ════════════════════════════════════════════════════════════════════
def val(row, key, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return default if pd.isna(value) else value


def num(row, key, default=0) -> int:
    """Same as val(), but coerced to int (the HTTP driver may return Decimal/str)."""
    value = val(row, key, None)
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def kpi(col, label: str, value, delta=None, delta_color: str = "normal",
        help_text: str | None = None):
    with col:
        st.metric(label, value if value is not None else "—",
                  delta, delta_color=delta_color, help=help_text)


def section(title: str, subtitle: str | None = None):
    st.markdown(f"### {title}")
    if subtitle:
        st.caption(subtitle)


def empty_guard(df: pd.DataFrame, msg: str = "No data available for this view.") -> bool:
    if df.empty:
        st.info(msg)
        return True
    return False


def to_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Force numeric dtypes — Plotly refuses wide-form data with mixed types."""
    out = df.copy()
    for col in cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    return out


# ════════════════════════════════════════════════════════════════════
# Sections
# ════════════════════════════════════════════════════════════════════
def render_funnel(funnel: pd.DataFrame):
    section(
        "Pipeline funnel",
        "Volume at each stage — processing backlog is kept separate from "
        "permanently unusable records",
    )
    if empty_guard(funnel):
        return

    f = funnel.iloc[0]

    missing = [c for c in ("transfer_health_pct", "unusable_no_company")
               if c not in funnel.columns]
    if missing:
        st.warning(
            f"`serving.pipeline_funnel` is behind the expected definition "
            f"(missing columns: {', '.join(missing)}). "
            "Re-run `010_pipeline_health_views.sql` for the full view."
        )

    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "Bronze", num(f, "bronze_total"), help_text="Raw offers, normalised")
    kpi(c2, "Staging", num(f, "staging_total"), help_text="LLM-enriched offers")
    kpi(c3, "Silver", num(f, "silver_total"), help_text="Usable, modelled offers")

    health = val(f, "transfer_health_pct")
    kpi(c4, "Transfer health", f"{health}%" if health is not None else "—",
        help_text="Silver / (Bronze − unusable). 100% means no backlog.")

    st.markdown("#### Backlog status")
    c5, c6, c7 = st.columns(3)

    pending_enrich = num(f, "pending_enrichment")
    pending_silver = num(f, "pending_silver")
    unusable = num(f, "unusable_no_company", num(f, "dropped_no_company"))

    with c5:
        st.metric("Awaiting enrichment", pending_enrich,
                  help="Bronze rows with no staging row yet. Clears on the next "
                       "silver_enrichment run.")
        st.caption("🟠 Processing backlog — run the DAG" if pending_enrich
                   else "🟢 Up to date")

    with c6:
        st.metric("Awaiting transfer", pending_silver,
                  help="Enriched AND usable, but not in Silver yet. Clears on the "
                       "next staging_to_silver run.")
        st.caption("🟠 Processing backlog — run the DAG" if pending_silver
                   else "🟢 Up to date")

    with c7:
        st.metric("Unusable", unusable,
                  help="No employer could be identified in the posting. These will "
                       "never reach Silver — this is not a backlog.")
        st.caption("⚪ Permanently discarded (expected)")

    stages = pd.DataFrame({
        "stage": ["Bronze", "Staging", "Silver"],
        "offers": [num(f, "bronze_total"), num(f, "staging_total"), num(f, "silver_total")],
    })
    fig = px.funnel(stages, x="offers", y="stage", color_discrete_sequence=[ACCENT])
    fig.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, width="stretch")


def render_freshness(fresh: pd.DataFrame):
    section("Ingestion freshness", "Detects a missed run or a stalled source")
    if empty_guard(fresh, "Ingestion tracking table not found — view not created."):
        return

    success = fresh[fresh["status"] == "success"] if "status" in fresh.columns else fresh
    if not success.empty:
        cols = st.columns(len(success))
        for col, (_, row) in zip(cols, success.iterrows()):
            status = val(row, "freshness_status", "OK")
            icon = {"OK": "🟢", "WARN": "🟠", "STALE": "🔴"}.get(status, "⚪")
            elapsed = str(val(row, "time_since_last_load", "")).split(".")[0]
            with col:
                st.metric(f"{icon} {val(row, 'source', '—')}",
                          f"{num(row, 'nb_files')} files",
                          delta=elapsed or None,
                          delta_color="off",
                          help=f"Last load: {val(row, 'last_load', 'n/a')}")

    with st.expander("Breakdown by status"):
        st.dataframe(fresh, hide_index=True, width="stretch")


def render_query_performance(qp: pd.DataFrame):
    section(
        "API query performance",
        "Pick a search configuration to inspect its yield — used to tune the "
        "fetch configs",
    )
    if empty_guard(qp):
        return

    qp = qp.copy()

    def _label(row) -> str:
        keywords = row.get("keywords") or "—"
        location = row.get("location") or "—"
        pct = row.get("pct_relevant")
        pct_txt = f"{float(pct):.0f}% relevant" if pd.notna(pct) else "n/a"
        return (f"{row.get('api_source', '?')} │ {keywords} @ {location} — "
                f"{int(row.get('nb_offers', 0))} offers, {pct_txt}")

    qp["_label"] = qp.apply(_label, axis=1)
    options_list = qp["_label"].tolist()


    default_idx = 0
    for i, row in qp.iterrows():
        # Utilisation de val() avec 0 comme fallback, puis conversion en float
        es = float(val(row, "pct_spanish", 0) or 0)
        en = float(val(row, "pct_english", 0) or 0)
        pt = float(val(row, "pct_portuguese", 0) or 0)
        
        if es > 0 or en > 0 or pt > 0:
            default_idx = options_list.index(row["_label"])
            break

    selected = st.selectbox(
        "Search configuration",
        options=qp["_label"].tolist(),
        index=default_idx,
        help="Sorted by relevance rate, highest first",
    )
    row = qp[qp["_label"] == selected].iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    pct_relevant = val(row, "pct_relevant")
    kpi(c1, "Offers collected", num(row, "nb_offers"))
    kpi(c2, "Relevant offers", num(row, "nb_relevant"),
        delta=f"{pct_relevant}%" if pct_relevant is not None else None,
        help_text="Relevancy score ≥ 6")
    kpi(c3, "Average score", val(row, "avg_score", "—"))
    kpi(c4, "Best score", val(row, "max_score", "—"))

    left, right = st.columns(2)

    with left:
        st.markdown("**Required spoken languages**")
        pairs = [("Spanish", val(row, "pct_spanish")),
                 ("English", val(row, "pct_english")),
                 ("Portuguese", val(row, "pct_portuguese"))]
        lang_df = pd.DataFrame(
            [(name, float(v)) for name, v in pairs if v is not None and float(v) > 0],
            columns=["language", "pct"],
        )
        if lang_df.empty:
            st.info("No language detected for this configuration.")
        else:
            fig = px.pie(lang_df, values="pct", names="language", hole=0.45)
            fig.update_traces(texttemplate="%{label}<br>%{value:.0f}%")
            fig.update_layout(height=280, showlegend=False,
                              margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, width="stretch")

    with right:
        st.markdown("**Seniority required**")
        pairs = [("Junior", val(row, "n_junior")),
                 ("Mid", val(row, "n_mid")),
                 ("Senior", val(row, "n_senior")),
                 ("Unknown", val(row, "n_seniority_unknown"))]
        sen_df = pd.DataFrame(
            [(name, int(float(v))) for name, v in pairs if v is not None and float(v) > 0],
            columns=["seniority", "offers"],
        )
        if sen_df.empty:
            st.info("No seniority data for this configuration.")
        else:
            fig = px.bar(sen_df, x="seniority", y="offers", color="seniority",
                         text="offers",
                         color_discrete_map={"Junior": OK_COLOR, "Mid": WARN_COLOR,
                                             "Senior": ERR_COLOR, "Unknown": NEUTRAL})
            fig.update_layout(height=280, showlegend=False, xaxis_title="",
                              yaxis_title="", margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, width="stretch")

    st.markdown("**Exact parameters stored in the database** "
                "(`raw.job_offer.query_parameters`)")
    params = val(row, "params_json")
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except json.JSONDecodeError:
            pass
    st.json(params if params is not None else val(row, "params_text", {}))

    with st.expander("Compare all configurations"):
        st.dataframe(
            qp.drop(columns=["_label", "params_json"], errors="ignore"),
            hide_index=True,
            width="stretch",
            column_config={
                "params_text":  st.column_config.TextColumn("Parameters JSON", width="large"),
                "api_source":   st.column_config.TextColumn("Source", width="small"),
                "keywords":     st.column_config.TextColumn("Keywords"),
                "location":     st.column_config.TextColumn("Location"),
                "nb_offers":    st.column_config.NumberColumn("Offers", width="small"),
                "nb_relevant":  st.column_config.NumberColumn("Relevant", width="small"),
                "pct_relevant": st.column_config.ProgressColumn(
                    "Relevance", min_value=0, max_value=100, format="%.1f%%"),
                "avg_score":    st.column_config.NumberColumn("Avg score", format="%.2f"),
                "max_score":    st.column_config.NumberColumn("Best score", format="%.2f"),
            },
        )


def render_volume(vot: pd.DataFrame):
    section("Volume over time", "Offers collected, enriched and transferred per day")
    if empty_guard(vot):
        return

    numeric_cols = ["offers_collected", "offers_enriched", "offers_in_silver",
                    "collected_careerjet", "collected_jsearch"]
    vot = to_numeric(vot, numeric_cols)
    vot["day"] = pd.to_datetime(vot["day"])

    stage_labels = {
        "offers_collected": "Collected (Bronze)",
        "offers_enriched": "Enriched (Staging)",
        "offers_in_silver": "Transferred (Silver)",
    }
    stage_cols = [c for c in stage_labels if c in vot.columns]
    if stage_cols:
        long_df = vot.melt(id_vars="day", value_vars=stage_cols,
                           var_name="stage", value_name="offers")
        long_df["stage"] = long_df["stage"].map(stage_labels)
        fig = px.line(long_df, x="day", y="offers", color="stage",
                      markers=True, labels={"day": ""})
        fig.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0),
                          legend=dict(orientation="h", y=1.1, title=""))
        st.plotly_chart(fig, width="stretch")

    source_labels = {"collected_careerjet": "CareerJet", "collected_jsearch": "JSearch"}
    source_cols = [c for c in source_labels if c in vot.columns]
    if source_cols:
        src_df = vot.melt(id_vars="day", value_vars=source_cols,
                          var_name="source", value_name="offers")
        src_df["source"] = src_df["source"].map(source_labels)
        fig = px.bar(src_df, x="day", y="offers", color="source",
                     labels={"day": ""}, title="Collection by source")
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0),
                          legend=dict(orientation="h", y=1.15, title=""))
        st.plotly_chart(fig, width="stretch")


def render_enrichment_quality(eq: pd.DataFrame, recovery: pd.DataFrame,
                              recovery_detail: pd.DataFrame):
    section("LLM enrichment quality", "Field-level resolution rate, per model")

    if not empty_guard(eq):
        st.dataframe(
            eq, hide_index=True, width="stretch",
            column_config={
                "llm_model":         st.column_config.TextColumn("Model"),
                "total_enriched":    st.column_config.NumberColumn("Enriched"),
                "company_found":     st.column_config.NumberColumn("Company found"),
                "seniority_unknown": st.column_config.NumberColumn("Seniority unknown"),
                "location_found":    st.column_config.NumberColumn("Location found"),
                "empty_job_titles":  st.column_config.NumberColumn("Empty job titles"),
                "empty_languages":   st.column_config.NumberColumn("Empty languages"),
                "score_missing":     st.column_config.NumberColumn("Score missing"),
                "avg_score":         st.column_config.NumberColumn("Avg score", format="%.2f"),
                "first_run":         st.column_config.DatetimeColumn("First run"),
                "last_run":          st.column_config.DatetimeColumn("Last run"),
            },
        )

    if not recovery.empty:
        st.markdown("#### Employer recovery by the LLM")
        r = recovery.iloc[0]
        rate = val(r, "recovery_rate_pct")
        c1, c2, c3 = st.columns(3)
        kpi(c1, "Missing employer in Bronze", num(r, "bronze_company_null"),
            help_text="The source API returned no employer name")
        kpi(c2, "Recovered by the LLM", num(r, "recovered_by_llm"),
            delta=f"{rate}%" if rate is not None else None,
            help_text="extract_company found the name inside the job description")
        kpi(c3, "Still unresolved", num(r, "still_unresolved"),
            help_text="Information absent from the source text — discarded")

    if not recovery_detail.empty:
        with st.expander(f"Employers recovered by the LLM ({len(recovery_detail)})"):
            st.dataframe(
                recovery_detail, hide_index=True, width="stretch",
                column_config={
                    "company_name": st.column_config.TextColumn("Company"),
                    "nb_offers":    st.column_config.NumberColumn("Offers", width="small"),
                    "api_source":   st.column_config.TextColumn("Source", width="small"),
                },
            )


def render_blocked(blocked: pd.DataFrame):
    section("Not transferred to Silver",
            "Processing backlog (self-resolving) vs unusable records (permanent)")
    if empty_guard(blocked, "Nothing pending — staging and Silver are in sync. ✅"):
        return

    blocked = to_numeric(blocked, ["nb_offers"])

    if "blocking_type" in blocked.columns:
        backlog = int(blocked.loc[blocked["blocking_type"] == "backlog", "nb_offers"].sum())
        unusable = int(blocked.loc[blocked["blocking_type"] == "unusable", "nb_offers"].sum())
        c1, c2 = st.columns(2)
        kpi(c1, "Processing backlog", backlog,
            help_text="Usable — will transfer on the next run")
        kpi(c2, "Unusable", unusable,
            help_text="No identifiable employer — permanently discarded")

    left, right = st.columns(2)
    with left:
        st.dataframe(
            blocked, hide_index=True, width="stretch",
            column_config={
                "blocking_reason": st.column_config.TextColumn("Reason"),
                "blocking_type":   st.column_config.TextColumn("Type", width="small"),
                "nb_offers":       st.column_config.NumberColumn("Offers", width="small"),
                "oldest":          st.column_config.DatetimeColumn("Oldest"),
                "newest":          st.column_config.DatetimeColumn("Newest"),
            },
        )
    with right:
        fig = px.pie(blocked, values="nb_offers", names="blocking_reason", hole=0.45)
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")


def render_skills(volume: pd.DataFrame, top: pd.DataFrame):
    section("Keyword extraction",
            "Volume of structured keywords produced by the LLM, per category")

    if not volume.empty:
        cols = st.columns(len(volume))
        for col, (_, row) in zip(cols, volume.iterrows()):
            kpi(col, str(val(row, "skill_type", "—")).capitalize(),
                f"{num(row, 'distinct_skills')} unique",
                delta=f"{num(row, 'total_mentions')} mentions",
                delta_color="off")

    if empty_guard(top, "No keyword extracted yet."):
        return

    available = sorted(top["skill_type"].dropna().unique().tolist())
    default = available

    left, right = st.columns([3, 1])
    with left:
        selected_types = st.multiselect(
            "Categories to display",
            options=available,
            default=default,
            help="Programming languages, frameworks, aptitudes, soft skills "
                 "and related job titles are all extracted by the LLM.",
        )
    with right:
        top_n = st.slider("Top N", 10, 60, 25, step=5)

    if not selected_types:
        st.info("Select at least one category.")
        return

    subset = top[top["skill_type"].isin(selected_types)].head(top_n)
    subset = to_numeric(subset, ["nb_mentions"])

    if subset.empty:
        st.info("No keyword for the selected categories.")
        return

    fig = px.bar(subset, x="nb_mentions", y="skill", color="skill_type",
                 orientation="h", labels={"nb_mentions": "mentions", "skill": "",
                                          "skill_type": "category"})
    fig.update_layout(height=max(320, 22 * len(subset)),
                      margin=dict(l=0, r=0, t=10, b=0),
                      yaxis=dict(autorange="reversed"),
                      legend=dict(orientation="h", y=1.05, title=""))
    st.plotly_chart(fig, width="stretch")


def render_geography(geo: pd.DataFrame):
    section("Geographic coverage", "Where the usable offers are concentrated")
    if empty_guard(geo):
        return

    geo = to_numeric(geo, ["nb_offers", "nb_companies", "nb_relevant"])
    left, right = st.columns(2)

    with left:
        st.dataframe(
            geo.head(20), hide_index=True, width="stretch",
            column_config={
                "country":      st.column_config.TextColumn("Country", width="small"),
                "city":         st.column_config.TextColumn("City"),
                "nb_offers":    st.column_config.NumberColumn("Offers", width="small"),
                "nb_companies": st.column_config.NumberColumn("Companies", width="small"),
                "avg_score":    st.column_config.NumberColumn("Avg score", format="%.2f"),
                "nb_relevant":  st.column_config.NumberColumn("Relevant", width="small"),
            },
        )
    with right:
        by_country = geo.groupby("country", as_index=False)["nb_offers"].sum()
        fig = px.pie(by_country, values="nb_offers", names="country", hole=0.45,
                     title="Offers by country")
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig, width="stretch")

# ════════════════════════════════════════════════════════════════════
# Page
# ════════════════════════════════════════════════════════════════════
def render():
    st.sidebar.title("📌 Summary")
    
    # --- MENU DE NAVIGATION STYLISÉ ---
    st.sidebar.markdown("""
    <style>
    /* Supprime les puces et les marges par défaut */
    .nav-menu {
        list-style-type: none;
        padding-left: 0;
        margin-top: 0;
    }
    .nav-menu li {
        margin-bottom: 4px;
    }
    /* Style des liens */
    .nav-menu a {
        text-decoration: none !important;
        color: var(--text-color) !important; /* S'adapte au mode clair ou sombre de Streamlit */
        display: block;
        padding: 8px 12px;
        border-radius: 8px;
        font-size: 15px;
        font-weight: 500;
        transition: all 0.2s ease-in-out;
    }
    /* Effet au survol (Hover) */
    .nav-menu a:hover {
        background-color: rgba(128, 128, 128, 0.15); /* Fond gris transparent */
        transform: translateX(4px); /* Légère animation vers la droite */
    }
    </style>

    <ul class="nav-menu">
        <li><a href="#pipeline-funnel">📊 Pipeline funnel</a></li>
        <li><a href="#ingestion-freshness">⏳ Ingestion freshness</a></li>
        <li><a href="#api-query-performance">⚡ API query performance</a></li>
        <li><a href="#volume-over-time">📈 Volume over time</a></li>
        <li><a href="#llm-enrichment-quality">🧠 LLM enrichment quality</a></li>
        <li><a href="#not-transferred-to-silver">🛑 Not transferred to Silver</a></li>
        <li><a href="#keyword-extraction">🔑 Keyword extraction</a></li>
        <li><a href="#geographic-coverage">🌍 Geographic coverage</a></li>
    </ul>
    """, unsafe_allow_html=True)
    # -----------------------------------

    st.title("🩺 Pipeline Health")
    st.caption(
        "End-to-end observability: ingestion → bronze → LLM enrichment → "
        "staging → silver. Every metric is computed in-database "
        "(`serving` schema)."
    )

    fingerprint = get_data_fingerprint()
    data, problems = load_all(fingerprint)

    _, refresh_col = st.columns([4, 1])
    with refresh_col:
        if st.button("🔄 Refresh", width="stretch"):
            st.cache_data.clear()
            st.rerun()

    if problems:
        with st.expander(f"⚠️ {len(problems)} view(s) unavailable", expanded=False):
            for problem in problems:
                st.text(problem)
            st.caption("Re-run `010_pipeline_health_views.sql` to (re)create them.")

    render_funnel(data["pipeline_funnel"])
    st.divider()

    render_freshness(data["ingestion_freshness"])
    st.divider()

    render_query_performance(data["query_performance"])
    st.divider()

    render_volume(data["volume_over_time"])
    st.divider()

    render_enrichment_quality(
        data["enrichment_quality"],
        data["company_recovery"],
        data["company_recovery_detail"],
    )
    st.divider()

    render_blocked(data["blocked_offers"])
    st.divider()

    render_skills(data["skills_extraction_volume"], data["top_skills"])
    st.divider()

    render_geography(data["geographic_coverage"])

    st.caption(
        f"Cache fingerprint: `{fingerprint[:60]}…` — invalidated automatically "
        "whenever the underlying data changes."
    )


render()