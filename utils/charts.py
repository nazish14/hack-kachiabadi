import plotly.express as px
import plotly.graph_objects as go
from typing import List, Dict, Any
import pandas as pd

def create_department_breakdown_chart(tickets: List[Dict[str, Any]]):
    """Generates a bar chart breakdown of tickets per municipal authority."""
    if not tickets:
        fig = go.Figure()
        fig.update_layout(title="No Active Tickets Reported")
        return fig

    df = pd.DataFrame(tickets)
    dept_counts = df.groupby(["department", "status"]).size().reset_index(name="count")

    fig = px.bar(
        dept_counts,
        x="department",
        y="count",
        color="status",
        barmode="group",
        title="Departmental Workload & Resolution Status",
        color_discrete_map={"PENDING": "#EF4444", "RESOLVED": "#10B981"},
        labels={"count": "Total Tickets", "department": "Department"}
    )
    fig.update_layout(
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig

def create_severity_pie_chart(tickets: List[Dict[str, Any]]):
    """Generates a severity distribution donut chart."""
    if not tickets:
        return go.Figure()

    df = pd.DataFrame(tickets)
    fig = px.pie(
        df,
        names="severity",
        title="Hazard Severity Distribution",
        hole=0.45,
        color="severity",
        color_discrete_map={"CRITICAL": "#DC2626", "HIGH": "#F97316", "MEDIUM": "#EAB308"}
    )
    fig.update_layout(margin=dict(l=20, r=20, t=40, b=20))
    return fig