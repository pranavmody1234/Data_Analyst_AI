import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import json
import os
import re
from io import BytesIO
from dotenv import load_dotenv
from openai import OpenAI
import pandasql as ps

# Load OpenAI API key
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Streamlit config
st.set_page_config(page_title="📊 AI Business Data Assistant", layout="wide")
st.title("📊 AI Business Data Assistant (GPT-3.5 Turbo)")

# Session State Initialization
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "df" not in st.session_state:
    st.session_state.df = None

# File Upload
uploaded_file = st.file_uploader("Upload your Excel or CSV file", type=["xlsx", "xls", "csv"])
if uploaded_file:
    try:
        if uploaded_file.name.endswith(".csv"):
            st.session_state.df = pd.read_csv(uploaded_file)
        else:
            st.session_state.df = pd.read_excel(uploaded_file)
        st.success("✅ File uploaded and data loaded!")
    except Exception as e:
        st.error(f"❌ Failed to load file: {e}")

# Data Preview
if st.session_state.df is not None:
    with st.expander("📄 Preview Data"):
        st.dataframe(st.session_state.df.head(10))
    with st.expander("📋 Summary Statistics"):
        st.write(st.session_state.df.describe(include='all'))

# Helper: Extract JSON from text
def extract_json_block(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group() if match else None

# Chart Generator
def generate_chart(df, chart_type, column_x=None, column_y=None, group_by=None):
    fig, ax = plt.subplots(figsize=(8, 5))
    try:
        if chart_type == "bar":
            if group_by:
                data = df.groupby([column_x, group_by]).size().unstack().fillna(0)
                data.plot(kind='bar', ax=ax)
                ax.set_title(f"{column_x} grouped by {group_by}")
            else:
                data = df[column_x].value_counts()
                ax.bar(data.index, data.values)
                ax.set_title(f"Bar Chart of {column_x}")
            ax.set_xlabel(column_x)
            ax.set_ylabel("Count")

        elif chart_type == "pie":
            data = df[column_x].value_counts()
            ax.pie(data.values, labels=data.index, autopct="%1.1f%%", startangle=90)
            ax.set_title(f"Pie Chart of {column_x}")

        elif chart_type == "line" and column_y:
            ax.plot(df[column_x], df[column_y])
            ax.set_title(f"{column_y} over {column_x}")
            ax.set_xlabel(column_x)
            ax.set_ylabel(column_y)

        elif chart_type == "scatter" and column_y:
            ax.scatter(df[column_x], df[column_y])
            ax.set_title(f"{column_y} vs {column_x}")
            ax.set_xlabel(column_x)
            ax.set_ylabel(column_y)

        else:
            st.warning("Unsupported or incomplete chart configuration.")
            return

        st.pyplot(fig)

        buffer = BytesIO()
        fig.savefig(buffer, format="png")
        st.download_button("📥 Download Chart", buffer.getvalue(), file_name="chart.png", mime="image/png")

    except Exception as e:
        st.error(f"Failed to generate chart: {e}")

# AI Prompting for Chart/Insight
def ask_openai(prompt, df):
    preview = df.sample(min(5, len(df))).to_string(index=False)
    system_message = (
        "You are a helpful data analyst assistant.\n"
        "You analyze the user's dataset and respond to queries.\n"
        "Return chart instructions as JSON like:\n"
        '{ "chart_type": "bar", "column_x": "category", "column_y": null, "group_by": null }\n'
        "You can also return a full dashboard as:\n"
        '{ "dashboard": { "metrics": ["total_tickets"], "charts": [ ... ] } }\n'
        "Also include statistical insights if relevant."
    )
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": f"Sample data:\n{preview}\n\nUser: {prompt}"}
        ],
        temperature=0.3
    )
    return response.choices[0].message.content

# SQL Execution
def execute_sql_query(query, df):
    try:
        local_env = {"df": df.copy()}
        return ps.sqldf(query, local_env)
    except Exception as e:
        st.error(f"❌ SQL error: {e}")
        return None

# AI for SQL Generation
def ask_openai_for_sql(prompt, df):
    preview = df.sample(min(5, len(df))).to_string(index=False)
    system_message = (
        "You are a helpful data assistant.\n"
        "Generate SQL queries using the table 'df'.\n"
        "Return the full SELECT statement ending in a semicolon."
    )
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": f"Sample data:\n{preview}\n\nUser: {prompt}"}
        ],
        temperature=0.3
    )
    return response.choices[0].message.content

# Handle natural language input
prompt = st.chat_input("Ask a question or request a chart/dashboard...")
if prompt and st.session_state.df is not None:
    with st.spinner("🔎 Analyzing..."):
        ai_response = ask_openai(prompt, st.session_state.df)
        st.session_state.chat_history.append(("user", prompt))
        st.session_state.chat_history.append(("ai", ai_response))

        # Display chat
        st.chat_message("user").write(prompt)
        st.chat_message("ai").write(ai_response)

        # Try extracting JSON
        json_block = extract_json_block(ai_response)
        if json_block:
            try:
                config = json.loads(json_block)

                # Handle dashboard
                if "dashboard" in config:
                    dashboard = config["dashboard"]
                    st.markdown("## 📊 Dashboard")
                    cols = st.columns(len(dashboard.get("metrics", [])))

                    for i, metric in enumerate(dashboard.get("metrics", [])):
                        if metric == "total_tickets":
                            cols[i].metric("Total Tickets", len(st.session_state.df))
                        elif metric == "sla_met_percentage":
                            if "sla_met" in st.session_state.df.columns:
                                met = st.session_state.df['sla_met'].str.lower().value_counts().get("yes", 0)
                                total = st.session_state.df['sla_met'].notna().sum()
                                perc = (met / total * 100) if total else 0
                                cols[i].metric("SLA Met %", f"{perc:.1f}%")

                    # Plot all charts
                    for chart in dashboard.get("charts", []):
                        generate_chart(st.session_state.df,
                                       chart.get("chart_type"),
                                       chart.get("column_x"),
                                       chart.get("column_y"),
                                       chart.get("group_by"))

                # Handle single chart
                elif config.get("chart_type"):
                    st.markdown("### 📈 Generated Chart")
                    generate_chart(st.session_state.df,
                                   config.get("chart_type"),
                                   config.get("column_x"),
                                   config.get("column_y"),
                                   config.get("group_by"))

            except json.JSONDecodeError:
                st.warning("⚠️ Could not parse chart/dashboard instructions.")

# SQL Input
sql_prompt = st.chat_input("Ask a question or request a SQL query...")
if sql_prompt and st.session_state.df is not None:
    with st.spinner("🧠 Generating SQL..."):
        ai_response = ask_openai_for_sql(sql_prompt, st.session_state.df)
        st.session_state.chat_history.append(("user", sql_prompt))
        st.session_state.chat_history.append(("ai", ai_response))

        st.chat_message("user").write(sql_prompt)
        st.chat_message("ai").write(ai_response)

        sql_match = re.search(r"SELECT .*?;", ai_response, re.IGNORECASE | re.DOTALL)
        if sql_match:
            query = sql_match.group()
            result = execute_sql_query(query, st.session_state.df)
            if result is not None:
                st.markdown("## 📋 SQL Query Result")
                st.dataframe(result)
        else:
            st.warning("⚠️ No valid SQL query found in AI response.")

# Optional Debug Panel
with st.expander("🔍 Debug Info"):
    st.write("Chat History:")
    for role, msg in st.session_state.chat_history:
        st.write(f"**{role.upper()}**: {msg}")
