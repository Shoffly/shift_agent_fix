"""
Streamlit app to manage agent_schedule table in BigQuery.
Displays a grid of agents × days with role dropdowns.
Changes are written back to BigQuery on save.

Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ID = "pricing-338819"
DATASET_ID = "wholesale_test"
TABLE_ID = "agent_schedule"
FULL_TABLE_ID = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
ROLE_OPTIONS = ["OFF", "Cash_Morning", "Cash_Night", "Swift", "Dealer", "Premium"]


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


def load_schedule() -> pd.DataFrame:
    """Load current schedule from BigQuery into a DataFrame with columns:
    email, Sun, Mon, Tue, Wed, Thu, Fri, Sat
    """
    client = get_bq_client()
    query = f"""
        SELECT email, roles
        FROM `{FULL_TABLE_ID}`
        ORDER BY email
    """
    rows = list(client.query(query).result())

    if not rows:
        return pd.DataFrame(columns=["email"] + DAYS)

    data = []
    for row in rows:
        entry = {"email": row.email}
        roles = list(row.roles) if row.roles else ["OFF"] * 7
        # Pad to 7 if somehow short
        roles = (roles + ["OFF"] * 7)[:7]
        for i, day in enumerate(DAYS):
            entry[day] = roles[i]
        data.append(entry)

    return pd.DataFrame(data)


def save_schedule(df: pd.DataFrame):
    """Overwrite the entire agent_schedule table with the DataFrame contents."""
    client = get_bq_client()

    # Build rows for insertion
    rows = []
    for _, row in df.iterrows():
        roles = [row[day] for day in DAYS]
        rows.append({"email": row["email"], "roles": roles})

    # Delete all existing rows and re-insert (simplest for a small table)
    delete_query = f"DELETE FROM `{FULL_TABLE_ID}` WHERE TRUE"
    client.query(delete_query).result()

    if rows:
        errors = client.insert_rows_json(FULL_TABLE_ID, rows)
        if errors:
            st.error(f"BigQuery insert errors: {errors}")
            return False

    return True


def add_agent(email: str, roles: list[str]):
    """Insert a single new agent row."""
    client = get_bq_client()
    errors = client.insert_rows_json(FULL_TABLE_ID, [{"email": email.lower().strip(), "roles": roles}])
    if errors:
        st.error(f"Insert error: {errors}")
        return False
    return True


def delete_agent(email: str):
    """Delete a single agent row."""
    client = get_bq_client()
    query = f"DELETE FROM `{FULL_TABLE_ID}` WHERE email = @email"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("email", "STRING", email)]
    )
    client.query(query, job_config=job_config).result()


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Agent Schedule Manager", layout="wide")

st.title("Agent Schedule Manager")
st.caption(f"`{FULL_TABLE_ID}`")

# Load data
if "schedule_df" not in st.session_state or st.session_state.get("reload"):
    st.session_state.schedule_df = load_schedule()
    st.session_state.reload = False

df = st.session_state.schedule_df

# ---------------------------------------------------------------------------
# Main schedule grid
# ---------------------------------------------------------------------------
st.subheader("Weekly Schedule")
st.markdown("Edit roles per agent per day. Click **Save Changes** when done.")

if df.empty:
    st.warning("No agents found in the table. Add one below.")
else:
    # Build an editable dataframe with dropdowns
    edited_df = st.data_editor(
        df,
        column_config={
            "email": st.column_config.TextColumn("Email", disabled=True, width="large"),
            **{
                day: st.column_config.SelectboxColumn(
                    day,
                    options=ROLE_OPTIONS,
                    required=True,
                    width="small",
                )
                for day in DAYS
            },
        },
        hide_index=True,
        use_container_width=True,
        key="schedule_editor",
    )

    # Save button
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("💾 Save Changes", type="primary", use_container_width=True):
            with st.spinner("Saving to BigQuery..."):
                success = save_schedule(edited_df)
            if success:
                st.success("Schedule saved!")
                st.session_state.schedule_df = edited_df
            else:
                st.error("Failed to save. Check errors above.")

    with col2:
        if st.button("🔄 Reload from DB", use_container_width=False):
            st.session_state.reload = True
            st.rerun()

# ---------------------------------------------------------------------------
# Add / Remove agent
# ---------------------------------------------------------------------------
st.divider()

col_add, col_remove = st.columns(2)

with col_add:
    st.subheader("Add Agent")
    new_email = st.text_input("Email", placeholder="agent@sylndr.com")
    new_default_role = st.selectbox("Default role for all days", ROLE_OPTIONS, index=0)

    if st.button("➕ Add Agent", use_container_width=True):
        if not new_email or "@" not in new_email:
            st.error("Enter a valid email.")
        elif new_email.lower().strip() in df["email"].values:
            st.error("Agent already exists.")
        else:
            roles = [new_default_role] * 7
            with st.spinner("Adding..."):
                success = add_agent(new_email, roles)
            if success:
                st.success(f"Added {new_email}")
                st.session_state.reload = True
                st.rerun()

with col_remove:
    st.subheader("Remove Agent")
    if not df.empty:
        remove_email = st.selectbox("Select agent to remove", df["email"].tolist())
        if st.button("🗑️ Remove Agent", type="secondary", use_container_width=True):
            with st.spinner("Removing..."):
                delete_agent(remove_email)
            st.success(f"Removed {remove_email}")
            st.session_state.reload = True
            st.rerun()
    else:
        st.info("No agents to remove.")

# ---------------------------------------------------------------------------
# Shift summary (read-only view)
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Shift Summary — Who's on today?")

if not df.empty:
    import datetime
    # Python weekday → template index (Sun=0)
    today_idx = (datetime.datetime.now().weekday() + 1) % 7
    today_name = DAYS[today_idx]

    st.markdown(f"**Today: {today_name}**")

    today_col = edited_df[today_name] if "edited_df" in dir() else df[today_name]
    emails = edited_df["email"] if "edited_df" in dir() else df["email"]

    for role in ["Cash_Morning", "Cash_Night", "Swift", "Dealer", "Premium"]:
        agents_on = emails[today_col == role].tolist()
        if agents_on:
            st.markdown(f"**{role}:** {', '.join(agents_on)}")
        else:
            st.markdown(f"**{role}:** —")
