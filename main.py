"""
Shift Agents Manager — Streamlit App
Reads and updates the wholesale_test.shift_agents table in BigQuery.
"""

import streamlit as st
from google.cloud import bigquery
from google.oauth2 import service_account

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ID = "pricing-338819"
DATASET_ID = "wholesale_test"
TABLE_ID = "shift_agents"
FULL_TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

# All known agents across all shifts (master list for the multiselect)
ALL_AGENTS = sorted([
    "hagar.ali@sylndr.com",
    "hagar.nazeh@sylndr.com",
    "mohamed.aly@sylndr.com",
    "mohamed.hanfy@sylndr.com",
    "monira.galal@sylndr.com",
    "omar.naser@sylndr.com",
    "nada.amr@sylndr.com",
    "sama.mostafa@sylndr.com",
    "dunia.naser@sylndr.com",
    "zahra.sayed@sylndr.com",
    "esraa.tarek@sylndr.com",
    "karim.wael@sylndr.com",
    "mohamed.elsaied@sylndr.com",
    "dunya.sayed@sylndr.com",
    "mai.sobhy@sylndr.com",
    "kerolos.reyad@sylndr.com",
])

SHIFT_LABELS = {
    "Cash_Morning": "☀️ Cash Morning",
    "Cash_Night": "🌙 Cash Night",
    "Swift": "⚡ Swift",
}


# ---------------------------------------------------------------------------
# BigQuery helpers
# ---------------------------------------------------------------------------
@st.cache_resource
def get_bq_client():
    try:
        credentials = service_account.Credentials.from_service_account_info(
            st.secrets["service_account"]
        )
    except (KeyError, FileNotFoundError):
        try:
            credentials = service_account.Credentials.from_service_account_file(
                'service_account.json'
            )
        except FileNotFoundError:
            st.error(
                "No credentials found. Please configure either Streamlit secrets or provide a service_account.json file."
            )
            st.stop()

    return bigquery.Client(credentials=credentials, project=PROJECT_ID)


def load_shifts(client) -> dict[str, list[str]]:
    """Return {shift_name: [agent_emails]} from BigQuery."""
    query = f"SELECT shift_name, agents FROM `{FULL_TABLE_ID}`"
    rows = client.query(query).result()
    shifts = {}
    for row in rows:
        agents = [a.strip() for a in row.agents.split(",") if a.strip()]
        shifts[row.shift_name] = agents
    return shifts


def update_shift(client, shift_name: str, agents: list[str]):
    """Overwrite the agents string for a given shift using DML."""
    agents_str = ",".join(agents)
    dml = f"""
        UPDATE `{FULL_TABLE_ID}`
        SET agents = @agents
        WHERE shift_name = @shift_name
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("agents", "STRING", agents_str),
            bigquery.ScalarQueryParameter("shift_name", "STRING", shift_name),
        ]
    )
    client.query(dml, job_config=job_config).result()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Shift Agents Manager", page_icon="👥", layout="wide")

st.markdown(
    """
    <style>
    .block-container { max-width: 900px; }
    div[data-testid="stVerticalBlock"] > div { padding: 0.25rem 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("👥 Shift Agents Manager")
st.caption("Edit which agents are assigned to each shift. Changes write directly to BigQuery.")

client = get_bq_client()

# Load current state
if "shifts" not in st.session_state or st.session_state.get("_reload"):
    st.session_state.shifts = load_shifts(client)
    st.session_state._reload = False

shifts = st.session_state.shifts

# ---------------------------------------------------------------------------
# Render one card per shift
# ---------------------------------------------------------------------------
for shift_name in ["Cash_Morning", "Cash_Night", "Swift"]:
    current_agents = shifts.get(shift_name, [])
    label = SHIFT_LABELS.get(shift_name, shift_name)

    st.markdown("---")
    col_header, col_count = st.columns([4, 1])
    with col_header:
        st.subheader(label)
    with col_count:
        st.metric("Agents", len(current_agents))

    # Multiselect to add/remove agents
    selected = st.multiselect(
        f"Agents on **{shift_name}**",
        options=ALL_AGENTS,
        default=current_agents,
        key=f"ms_{shift_name}",
        label_visibility="collapsed",
    )

    # Quick add: type a new email not in master list
    new_email = st.text_input(
        "Add a new agent email (not in list)",
        key=f"new_{shift_name}",
        placeholder="e.g. newagent@sylndr.com",
    )

    col_save, col_status = st.columns([1, 3])
    with col_save:
        if st.button("💾 Save", key=f"save_{shift_name}", use_container_width=True):
            final_agents = list(selected)
            if new_email and new_email.strip():
                clean = new_email.strip().lower()
                if clean not in final_agents:
                    final_agents.append(clean)
                    # Also add to master list for future use in this session
                    if clean not in ALL_AGENTS:
                        ALL_AGENTS.append(clean)
                        ALL_AGENTS.sort()

            if not final_agents:
                st.warning("Cannot save an empty shift.")
            else:
                try:
                    update_shift(client, shift_name, final_agents)
                    st.session_state.shifts[shift_name] = final_agents
                    st.success(f"Updated **{shift_name}** → {len(final_agents)} agents")
                    st.rerun()
                except Exception as e:
                    st.error(f"BigQuery error: {e}")

    with col_status:
        # Show diff vs what's in DB
        db_set = set(shifts.get(shift_name, []))
        ui_set = set(selected)
        if new_email and new_email.strip():
            ui_set.add(new_email.strip().lower())
        if db_set != ui_set:
            added = ui_set - db_set
            removed = db_set - ui_set
            parts = []
            if added:
                parts.append(f"**+{len(added)}** added")
            if removed:
                parts.append(f"**-{len(removed)}** removed")
            st.info(f"Unsaved changes: {', '.join(parts)}")

# ---------------------------------------------------------------------------
# Footer: reload from DB
# ---------------------------------------------------------------------------
st.markdown("---")
if st.button("🔄 Reload from database"):
    st.session_state._reload = True
    st.rerun()
