import streamlit as st
from PIL import Image
from pathlib import Path
from streamlit_folium import st_folium

try:
    from streamlit_js_eval import get_geolocation
except ImportError:
    get_geolocation = None

from config import DEFAULT_CITY, DEFAULT_LAT, DEFAULT_LNG, STATIC_DIR
from core.database import init_db, insert_ticket, get_all_tickets, mark_ticket_resolved
from core.geo_utils import extract_exif_gps, reverse_geocode_coords
from core.vision_detector import detect_civic_hazards
from core.agents.triage_agent import triage_and_route_hazards
from utils.visualizer import annotate_image_with_hazards
from utils.map_renderer import render_civic_map
from utils.charts import create_department_breakdown_chart, create_severity_pie_chart

# Page Configuration
st.set_page_config(
    page_title="ShehrBehtar AI - Civic Hub",
    page_icon="🏙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Database
init_db()

# Track submitted tickets in current session
if "submitted_uids" not in st.session_state:
    st.session_state.submitted_uids = []

# Visual Styling (CSS only)
CSS_PATH = Path(__file__).parent / "static" / "style.css"
st.markdown(
    f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>",
    unsafe_allow_html=True
)

# Sidebar Navigation
st.sidebar.title("🏙️ ShehrBehtar AI")
st.sidebar.caption("Bahawalpur Urban Operations Platform")

portal_view = st.sidebar.radio(
    "Navigation Portal",
    ["📢 Citizen Portal (Report & Track)", "🛡️ Super Admin (City Command Desk)"]
)

# ==========================================
# 1. CITIZEN PORTAL (REPORT & LIVE TRACK)
# ==========================================
if portal_view == "📢 Citizen Portal (Report & Track)":
    # Sidebar Live Tracking
    st.sidebar.markdown("---")
    st.sidebar.subheader("📋 Aapki Reports (Live Track)")
    
    if not st.session_state.submitted_uids:
        st.sidebar.info("Is session mein abhi tak koi complaint register nahi hui.")
    else:
        all_recs = get_all_tickets()
        user_recs = [r for r in all_recs if r["ticket_uid"] in st.session_state.submitted_uids]
        
        for r in user_recs:
            is_res = r["status"] == "RESOLVED"
            badge_bg = "#064e3b" if is_res else "#1e1b4b"
            status_text = "RESOLVED ✅" if is_res else "IN PROGRESS ⏳"
            
            st.sidebar.markdown(f"""
            <div style="background-color: {badge_bg}; color: #ffffff; padding: 12px; border-radius: 6px; margin-bottom: 8px; border-left: 4px solid {'#10b981' if is_res else '#6366f1'};">
                <div style="display:flex; justify-content:space-between; font-size:12px;">
                    <b>{r['ticket_uid']}</b>
                    <span style="font-weight:bold;">{status_text}</span>
                </div>
                <div style="font-size:12px; margin-top:4px;"><b>Dept:</b> {r['department']}</div>
                <div style="font-size:11px; opacity:0.85;"><b>SLA:</b> {r['sla_hours']} Hours</div>
                {f"<div style='font-size:11px; color:#34d399; margin-top:4px;'><b>Resolved:</b> {r['resolved_at']}</div>" if is_res else ""}
            </div>
            """, unsafe_allow_html=True)

    st.title("📢 Public Civic Hazard Reporting")
    st.caption("Broken roads, open gutters, aur garbage dumps foran report karein.")

    tab_report, tab_track = st.tabs(["🚀 Report New Hazard", "🔍 Search Any Ticket"])

    with tab_report:
        col_left, col_right = st.columns([1.1, 1], gap="large")

        with col_left:
            st.subheader("1. Street Photographic Evidence")
            uploaded_file = st.file_uploader("Upload street photo (Max 10MB)", type=["jpg", "jpeg", "png"])

            # Demo Presets Selection
            test_samples_dir = STATIC_DIR / "test_samples"
            sample_files = list(test_samples_dir.glob("*.jpg")) + list(test_samples_dir.glob("*.png"))
            
            selected_sample = None
            chosen = "-- Quick Demo Sample --"
            if sample_files:
                preset_options = ["-- Quick Demo Sample --"] + [f.name for f in sample_files]
                chosen = st.selectbox("Quick Test Images", preset_options)
                if chosen != "-- Quick Demo Sample --":
                    selected_sample = Image.open(test_samples_dir / chosen)

            active_img = uploaded_file if uploaded_file else selected_sample
            if active_img:
                img_obj = Image.open(active_img) if uploaded_file else active_img
                st.image(img_obj, caption="Evidence Source View")

                auto_lat, auto_lng, detected_addr = extract_exif_gps(img_obj)

                st.subheader("2. Geo-Location Details")

                # Mobile Browser Live Location Access
                current_lat, current_lng, current_addr = auto_lat, auto_lng, detected_addr
                if get_geolocation is not None:
                    loc = get_geolocation()
                    if loc and "coords" in loc:
                        current_lat = float(loc["coords"]["latitude"])
                        current_lng = float(loc["coords"]["longitude"])
                        current_addr = reverse_geocode_coords(current_lat, current_lng)
                        st.success("📍 Live GPS Location captured from mobile/browser!")

                # Issue Selection Dropdown
                selected_cat = st.selectbox(
                    "Hazard Category Selection",
                    [
                        "🤖 Auto-Detect (AI Multi-Model)",
                        "Open Gutter / Manhole (MCB Water Wing)",
                        "Road Pothole / Surface Damage (C&W Roads)",
                        "Garbage Dump / Solid Waste (BWMC)"
                    ]
                )

                c1, c2 = st.columns(2)
                with c1:
                    in_lat = st.number_input("Latitude", value=current_lat, format="%.6f")
                with c2:
                    in_lng = st.number_input("Longitude", value=current_lng, format="%.6f")
                in_addr = st.text_input("Area / Landmark", value=current_addr)

                # Determine filename hint
                file_hint = ""
                if uploaded_file is not None:
                    file_hint = uploaded_file.name
                elif selected_sample is not None and chosen != "-- Quick Demo Sample --":
                    file_hint = chosen

                if st.button("🚀 Analyze & Dispatch Report", type="primary"):
                    with st.spinner("AI Vision Inspector analyzing hazard..."):
                        det_res = detect_civic_hazards(
                            img_obj, 
                            filename_hint=file_hint, 
                            user_category_hint=selected_cat
                        )

                    if not det_res.hazards:
                        st.warning("No critical municipal hazard detected in this photo.")
                    else:
                        annotated = annotate_image_with_hazards(img_obj, det_res.hazards)
                        st.image(annotated, caption="Computer Vision Detection Overlay")

                        with st.spinner("Multi-Agent Policy RAG routing complaints..."):
                            tickets = triage_and_route_hazards(det_res, lat=in_lat, lng=in_lng, address=in_addr)

                            for t in tickets:
                                img_path = STATIC_DIR / f"{t.ticket_uid}.jpg"
                                annotated.save(img_path)

                                insert_ticket({
                                    "ticket_uid": t.ticket_uid,
                                    "hazard_type": t.hazard_type,
                                    "department": t.department,
                                    "severity": t.severity,
                                    "sla_hours": t.sla_hours,
                                    "hazard_score": t.hazard_score,
                                    "latitude": t.latitude,
                                    "longitude": t.longitude,
                                    "address": t.address,
                                    "notes": t.notes,
                                    "materials_needed": t.materials_needed,
                                    "image_path": str(img_path)
                                })
                                st.session_state.submitted_uids.append(t.ticket_uid)

                                # Feedback Banner
                                st.markdown(f"""
                                <div style="background-color: #064e3b; color: #ecfdf5; padding: 16px; border-radius: 8px; border-left: 6px solid #10b981; margin-bottom: 10px;">
                                    <h4 style="margin:0 0 6px 0; color:#34d399;">Ticket Generated: {t.ticket_uid}</h4>
                                    <p style="margin:0 0 4px 0;"><b>Assigned Authority:</b> {t.department}</p>
                                    <p style="margin:0; color:#a7f3d0;"><b>Mandated Resolution Window (SLA):</b> {t.sla_hours} Hours mein resolve hoga.</p>
                                </div>
                                """, unsafe_allow_html=True)
                            st.rerun()

        with col_right:
            st.subheader("City Live Anomaly Map")
            active_tickets = get_all_tickets("PENDING")
            st_folium(render_civic_map(active_tickets), width=580, height=520, key="cit_map")

    with tab_track:
        st.subheader("Track Complaint Resolution Status")
        search_uid = st.text_input("Enter Ticket Tracking ID (e.g. BW-A1B2C)", "").strip().upper()
        if search_uid:
            all_recs = get_all_tickets()
            matched = next((item for item in all_recs if item["ticket_uid"] == search_uid), None)
            if matched:
                is_resolved = matched["status"] == "RESOLVED"
                st.markdown(f"""
                <div style="background-color: {'#064e3b' if is_resolved else '#451a03'}; padding: 20px; border-radius: 8px; color: #ffffff;">
                    <h3 style="margin:0;">Status: {'RESOLVED ✅' if is_resolved else 'IN PROGRESS ⏳'}</h3>
                    <p style="margin:8px 0 0 0;"><b>Department:</b> {matched['department']}</p>
                    <p style="margin:4px 0 0 0;"><b>Hazard:</b> {matched['hazard_type']}</p>
                    <p style="margin:4px 0 0 0;"><b>SLA Response Window:</b> {matched['sla_hours']} Hours</p>
                    <p style="margin:4px 0 0 0;"><b>Reported Date:</b> {matched['created_at']}</p>
                    {f"<p style='margin:4px 0 0 0; color:#34d399;'><b>Resolved At:</b> {matched['resolved_at']}</p>" if is_resolved else ""}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.error("No record found for this Ticket ID. Please verify the code.")

# ==========================================
# 2. SUPER ADMIN COMMAND DESK
# ==========================================
else:
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🏛️ Municipal Policy Standards")
    st.sidebar.markdown("""
    - 🔴 **MCB Water Wing**: SLA 4h (Critical)
    - 🟡 **BWMC Suthra Punjab**: SLA 12-24h
    - 🟠 **C&W / MCB Roads**: SLA 48h
    """)

    st.title("🛡️ Super Admin Command & Operations")
    st.caption("Consolidated city-wide dispatch control across all Bahawalpur Municipal Authorities.")

    all_tickets = get_all_tickets()
    pending = [t for t in all_tickets if t["status"] == "PENDING"]
    resolved = [t for t in all_tickets if t["status"] == "RESOLVED"]

    # KPIs
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Reported", len(all_tickets))
    k1_val = sum(1 for t in pending if t["severity"] == "CRITICAL")
    k2.metric("Critical Hazards (<4h)", k1_val, delta=f"{k1_val} Actionable", delta_color="inverse")
    k3.metric("Resolved Cases", len(resolved))
    comp_rate = round((len(resolved) / max(1, len(all_tickets))) * 100, 1)
    k4.metric("City SLA Compliance", f"{comp_rate}%")

    st.markdown("---")

    # Filter Work Orders by Department
    dept_filter = st.selectbox(
        "🏢 Filter Work Orders by Department:",
        [
            "All Departments",
            "MCB - Water & Sanitation Branch",
            "Bahawalpur Waste Management Company (BWMC)",
            "Communication & Works (C&W) / MCB Roads"
        ]
    )

    filtered_tickets = all_tickets
    if dept_filter != "All Departments":
        filtered_tickets = [t for t in all_tickets if dept_filter.lower() in t["department"].lower()]

    col_map_view, col_list_view = st.columns([1.1, 1], gap="large")

    with col_map_view:
        st.subheader("Geospatial Overview (OpenStreetMap)")
        st_folium(render_civic_map(filtered_tickets), width=650, height=480, key="adm_map")

    with col_list_view:
        st.subheader("Incident Dispatch Orders")
        pending_filtered = [t for t in filtered_tickets if t["status"] == "PENDING"]
        
        if not pending_filtered:
            st.info("No pending work orders under this selection.")
        else:
            for item in pending_filtered:
                with st.expander(f"🔴 [{item['severity']}] {item['ticket_uid']} - {item['hazard_type']}", expanded=True):
                    st.write(f"**Department:** {item['department']}")
                    st.write(f"**Location:** {item['address']}")
                    st.write(f"**SLA Window:** {item['sla_hours']} Hours")
                    st.write(f"**Required Equipment:** {item['materials_needed']}")
                    st.write(f"**Action Notes:** {item['notes']}")
                    
                    if st.button("Mark Resolved & Close Ticket", key=f"btn_{item['ticket_uid']}", type="primary"):
                        mark_ticket_resolved(item['ticket_uid'])
                        st.success(f"Ticket {item['ticket_uid']} marked as RESOLVED!")
                        st.rerun()

    st.markdown("---")
    st.subheader("📊 Workload Analytics & Departmental Performance")
    ch1, ch2 = st.columns(2)
    with ch1:
        st.plotly_chart(create_department_breakdown_chart(filtered_tickets))
    with ch2:
        st.plotly_chart(create_severity_pie_chart(filtered_tickets))