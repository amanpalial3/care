import streamlit as st
import pytesseract
import ollama
import tempfile
import re
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from streamlit_lottie import st_lottie
import requests

from pdf2image import convert_from_bytes
from pdfminer.high_level import extract_text
from streamlit_option_menu import option_menu

# =========================================================
# TESSERACT PATH (adjust if needed)
# =========================================================
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# =========================================================
# PAGE CONFIG
# =========================================================
st.set_page_config(page_title="AI Medical Dashboard", page_icon="🩺", layout="wide")

# =========================================================
# CUSTOM CSS (modern dark theme)
# =========================================================
# =========================================================
# LIGHT THEME + BACKGROUND IMAGE
# =========================================================

st.markdown("""
<style>

.stApp {
    background-image: url("https://images.unsplash.com/photo-1579684385127-1ef15d508118?q=80&w=2070&auto=format&fit=crop");
    background-size: cover;
    background-position: center;
    background-attachment: fixed;
}

</style>
""", unsafe_allow_html=True)

# =========================================================
# SESSION STATE
# =========================================================
if "report_text" not in st.session_state:
    st.session_state.report_text = ""
if "summary" not in st.session_state:
    st.session_state.summary = ""
if "extracted_params" not in st.session_state:
    st.session_state.extracted_params = {}

# =========================================================
# PDF + OCR EXTRACTION
# =========================================================
def extract_report_text(uploaded_file):
    text = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded_file.read())
            temp_path = tmp.name
        text = extract_text(temp_path)
    except:
        text = ""
    # OCR fallback if text is insufficient
    if len(text.strip()) < 50:
        images = convert_from_bytes(uploaded_file.getvalue())
        for img in images:
            ocr_text = pytesseract.image_to_string(img)
            text += ocr_text + "\n"
    return text

# =========================================================
# DYNAMIC MEDICAL PARAMETER EXTRACTION (AUTO-DETECT ALL)
# =========================================================
def extract_all_parameters(text):
    """
    Automatically finds any line like "Parameter : value unit"
    Returns:
        standard_params (dict) – mapped to common names (Hemoglobin, Glucose, etc.)
        other_params (dict) – rest of the detected values
    """
    text_lower = text.lower()
    
    # ---- Patient details ----
    name = None
    age = None
    gender = None
    
    # Name patterns
    name_patterns = [
        r'Patient\s*Name\s*[:;]?\s*([A-Z][A-Za-z\s\.]+)(?=\s+|\n|$)',
        r'Name\s*[:;]?\s*([A-Z][A-Za-z\s\.]+)',
        r'Mr\.?\s+([A-Z][A-Za-z\s\.]+)',
        r'Mrs\.?\s+([A-Z][A-Za-z\s\.]+)'
    ]
    for pat in name_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            break
    # Fallback: first line that looks like a name
    if not name:
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if len(line.split()) >= 2 and re.match(r'^[A-Za-z\s\.]+$', line):
                if "hospital" not in line.lower() and "lab" not in line.lower():
                    name = line
                    break
    
    # Age
    age_match = re.search(r'Age\s*[:;]?\s*(\d{1,3})', text, re.IGNORECASE)
    if age_match:
        age = int(age_match.group(1))
    
    # Gender
    if re.search(r'\b(female|woman|f/|gender\s*:\s*f)\b', text_lower):
        gender = "Female"
    elif re.search(r'\b(male|man|m/|gender\s*:\s*m)\b', text_lower):
        gender = "Male"
    
    # ---- Dynamic parameter detection ----
    # Pattern: "Parameter : value unit" or "Parameter value"
    param_pattern = r'(?P<name>[A-Za-z\s\(\)]+?)\s*[:;]?\s*(?P<value>\d+\.?\d*)\s*(?P<unit>[A-Za-z/µ%°]+)?'
    raw_matches = re.finditer(param_pattern, text, re.IGNORECASE)
    
    detected = {}
    for m in raw_matches:
        pname = m.group('name').strip().lower()
        val = m.group('value')
        unit = m.group('unit') if m.group('unit') else ''
        # store as number if possible
        try:
            val = float(val) if '.' in val else int(val)
        except:
            val = val
        if pname not in detected:
            detected[pname] = {"value": val, "unit": unit}
    
    # ---- Map common aliases to standard fields ----
    alias_map = {
        "hemoglobin": "Hemoglobin", "hb": "Hemoglobin",
        "rbc": "RBC", "red blood cells": "RBC",
        "wbc": "WBC", "white blood cells": "WBC", "leukocytes": "WBC",
        "platelets": "Platelets", "plt": "Platelets",
        "hba1c": "HbA1c", "a1c": "HbA1c", "glycated hemoglobin": "HbA1c",
        "glucose": "Blood Sugar", "blood sugar": "Blood Sugar", "fasting blood sugar": "Blood Sugar", "fbs": "Blood Sugar",
        "total cholesterol": "Cholesterol", "cholesterol": "Cholesterol",
        "mcv": "MCV", "mean corpuscular volume": "MCV",
        "mch": "MCH", "mean corpuscular hemoglobin": "MCH",
        "mchc": "MCHC", "mean corpuscular hemoglobin concentration": "MCHC",
        "rdw": "RDW", "red cell distribution width": "RDW",
        "pcv": "PCV", "hematocrit": "PCV", "hct": "PCV"
    }
    
    standard = {
        "Patient Name": name, "Age": age, "Gender": gender,
        "Hemoglobin": None, "RBC": None, "WBC": None, "Platelets": None,
        "HbA1c": None, "Blood Sugar": None, "Cholesterol": None,
        "MCV": None, "MCH": None, "MCHC": None, "RDW": None, "PCV": None
    }
    
    other = {}
    
    for pname, data in detected.items():
        value = data["value"]
        unit = data["unit"]
        mapped = None
        for alias, std in alias_map.items():
            if alias in pname:
                mapped = std
                break
        if mapped and mapped in standard:
            standard[mapped] = f"{value} {unit}".strip()
        else:
            # keep original name
            other[pname.title()] = f"{value} {unit}".strip()
    
    # ---- Fallback patterns for missed values ----
    fallback = {
        "Hemoglobin": r'\bHb\s*[:;]?\s*(\d+\.?\d*)',
        "WBC": r'\bWBC\s*[:;]?\s*(\d+\.?\d*)',
        "Platelets": r'\bPlatelets?\s*[:;]?\s*(\d+)',
        "Blood Sugar": r'\bGlucose\s*[:;]?\s*(\d+)'
    }
    for field, pat in fallback.items():
        if standard[field] is None:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                standard[field] = float(m.group(1))
    
    return standard, other

# =========================================================
# AI SUMMARY
# =========================================================
def generate_ai_summary(report_text, params):
    prompt = f"""
You are a medical AI assistant. Analyze the report and extracted values.

Extracted values: {params}

Medical Report Text:
{report_text[:2500]}

Provide:
1. Patient Overview (name, age, gender if found)
2. Important Findings
3. Abnormal Values (compare with normal ranges)
4. Possible Disease Risks
5. Recommendations

Be specific, use only report information.
"""
    try:
        response = ollama.chat(model='llama3.2', messages=[{'role': 'user', 'content': prompt}])
        return response['message']['content']
    except Exception as e:
        return f"⚠️ Error: {str(e)}"

# =========================================================
# CHATBOT
# =========================================================
def ask_chatbot(question, report_text, params):
    prompt = f"""
You are an AI medical assistant.

You can answer in:
- English
- Hindi
- Hinglish

If user asks in Hinglish,
reply in Hinglish.

Your task:
- explain medical report
- explain test values
- tell abnormal findings
- tell risks
- answer medical questions simply

STRICT RULES:
- ONLY use report information
- DO NOT create fake diseases
- DO NOT invent patient history
- If data missing say:
  "Information report me available nahi hai"

Medical Parameters:
{params}

Medical Report:
{report_text[:2500]}

User Question:
{question}

Give short and simple answer.
"""
    try:
        response = ollama.chat(model='llama3.2', messages=[{'role': 'user', 'content': prompt}])
        return response['message']['content']
    except Exception as e:
        return f"⚠️ Error: {str(e)}"

# =========================================================
# HELPER FUNCTION FOR GAUGE CHART
# =========================================================
def create_gauge(value, title, min_val, max_val, normal_low, normal_high):
    """Create a gauge chart with normal range indicator."""
    # Determine color based on value
    if value < normal_low:
        color = "red"
        status = "Low"
    elif value > normal_high:
        color = "orange"
        status = "High"
    else:
        color = "green"
        status = "Normal"
    
    fig = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = value,
        title = {'text': f"{title}<br><span style='font-size:0.8em;color:{color}'>{status}</span>"},
        gauge = {
            'axis': {'range': [min_val, max_val]},
            'bar': {'color': color},
            'steps': [
                {'range': [min_val, normal_low], 'color': "lightgray"},
                {'range': [normal_low, normal_high], 'color': "lightgreen"},
                {'range': [normal_high, max_val], 'color': "lightgray"}
            ],
            'threshold': {
                'line': {'color': "black", 'width': 2},
                'thickness': 0.75,
                'value': value
            }
        }
    ))
    fig.update_layout(height=250, margin=dict(l=20, r=20, t=50, b=20))
    return fig

# =========================================================
# SIDEBAR MENU
# =========================================================
with st.sidebar:
    selected = option_menu(

    menu_title="🩺 Medical AI",

    options=[
        "Dashboard",
        "Upload Report",
        "AI Analysis",
        "Analytics",
        "Chatbot"
    ],

    icons=[
        "house",
        "file-earmark-medical",
        "robot",
        "bar-chart",
        "chat-dots"
    ],

    default_index=0,

    styles={

        "container": {
            "padding": "10px",
            "background-color": "rgba(255,255,255,0.75)",
            "border-radius": "15px"
        },

        "icon": {
            "color": "#2563eb",
            "font-size": "20px"
        },

        "nav-link": {
            "font-size": "18px",
            "text-align": "left",
            "margin": "6px",
            "color": "black",
            "--hover-color": "#dbeafe",
            "border-radius": "10px"
        },

        "nav-link-selected": {
            "background": "linear-gradient(135deg,#60a5fa,#2563eb)",
            "color": "white",
            "font-weight": "bold",
            "border-radius": "10px"
        },
    }
)

# =========================================================
# DASHBOARD
# =========================================================
if selected == "Dashboard":
    st.title("🩺 AI Medical Dashboard")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("<div class='metric-box'><h2>📄 OCR</h2><p>Medical Report Reading</p></div>", unsafe_allow_html=True)
    with col2:
        st.markdown("<div class='metric-box'><h2>🤖 AI Analysis</h2><p>Llama 3.2</p></div>", unsafe_allow_html=True)
    with col3:
        st.markdown("<div class='metric-box'><h2>💬 Chatbot</h2><p>Medical Q/A</p></div>", unsafe_allow_html=True)

# =========================================================
# UPLOAD REPORT
# =========================================================
elif selected == "Upload Report":
    st.title("📄 Upload Medical Report")
    uploaded_file = st.file_uploader("Upload PDF", type=["pdf"])
    if uploaded_file:
        with st.spinner("Reading report (OCR if needed)..."):
            text = extract_report_text(uploaded_file)
            st.session_state.report_text = text
            # Extract all parameters dynamically
            standard, other = extract_all_parameters(text)
            st.session_state.extracted_params = {**standard, **other}
        st.success("✅ Report Processed Successfully")

        # ---- Patient Card ----
        name = standard.get("Patient Name", "Unknown")
        age = standard.get("Age", "N/A")
        gender = standard.get("Gender", "N/A")
        st.markdown(f"""
        <div class='patient-card'>
            <h1>👤 {name}</h1>
            <h3>🎂 Age: {age}</h3>
            <h3>⚧ Gender: {gender}</h3>
        </div>
        """, unsafe_allow_html=True)

        # ---- Standard Parameters ----
        st.subheader("🧪 Standard Medical Parameters")
        std_keys = ["Hemoglobin", "RBC", "WBC", "Platelets", "HbA1c", "Blood Sugar", "Cholesterol", "MCV", "MCH", "MCHC", "RDW", "PCV"]
        cols = st.columns(4)
        for i, key in enumerate(std_keys):
            val = standard.get(key)
            if val:
                with cols[i % 4]:
                    st.metric(key, val)
        
        # ---- Other Detected Parameters ----
        other_items = {k:v for k,v in other.items() if v is not None}
        if other_items:
            st.subheader("🔬 Additional Detected Parameters")
            other_cols = st.columns(4)
            for j, (k, v) in enumerate(other_items.items()):
                with other_cols[j % 4]:
                    st.metric(k, v)
        
        # ---- Raw Text ----
        with st.expander("📄 View Extracted Report Text"):
            st.text_area("Full Text", value=text, height=300)

# =========================================================
# AI ANALYSIS
# =========================================================
elif selected == "AI Analysis":
    st.title("🤖 AI Medical Analysis")
    if st.session_state.report_text:
        with st.spinner("Generating AI Summary..."):
            summary = generate_ai_summary(st.session_state.report_text, st.session_state.extracted_params)
        st.markdown(f"<div class='card'><h2>🧠 AI Summary</h2><p>{summary}</p></div>", unsafe_allow_html=True)
    else:
        st.warning("Upload a report first.")

# =========================================================
# ANALYTICS (ENHANCED WITH MULTIPLE CHARTS)
# =========================================================
elif selected == "Analytics":
    st.title("📊 Medical Analytics Dashboard")
    params = st.session_state.extracted_params
    
    if not params:
        st.info("No data yet. Upload a report first.")
    else:
        # Extract numeric values with their units
        numeric_data = []
        param_info = {}  # store value, unit, normal ranges
        
        for key, val in params.items():
            if key in ["Patient Name", "Age", "Gender"]:
                continue
            num = None
            unit = ""
            if isinstance(val, (int, float)):
                num = val
            elif isinstance(val, str):
                # Extract number and optional unit
                match = re.search(r'(\d+\.?\d*)\s*([A-Za-z/µ%°]+)?', val)
                if match:
                    num = float(match.group(1))
                    unit = match.group(2) if match.group(2) else ""
            if num is not None:
                numeric_data.append({"Parameter": key, "Value": num, "Unit": unit})
                param_info[key] = {"value": num, "unit": unit}
        
        if not numeric_data:
            st.info("No numeric values found for visualization.")
        else:
            df = pd.DataFrame(numeric_data)
            
            # Tabbed interface for different visualizations
            tab1, tab2, tab3 = st.tabs(["📊 Bar Chart", "🎯 Gauge Meters", "📈 Comparison"])
            
            with tab1:
                st.subheader("Parameter Values Comparison")
                fig = px.bar(df, x="Parameter", y="Value", 
                            title="Your Lab Values",
                            color="Value",
                            color_continuous_scale=["#ff6b6b", "#4ecdc4", "#45b7d1"],
                            text="Value")
                fig.update_traces(textposition="outside")
                fig.update_layout(showlegend=False, height=500)
                st.plotly_chart(fig, use_container_width=True)
                
                # Add reference lines for normal ranges (if we know them)
                st.caption("📌 Higher bar doesn't always mean abnormal – compare with normal ranges below.")
            
            with tab2:
                st.subheader("Critical Parameters - Gauge View")
                # Define normal ranges for common tests
                normal_ranges = {
                    "Hemoglobin": (12, 16, 4, 20),      # (normal_low, normal_high, min, max)
                    "Blood Sugar": (70, 100, 50, 200),
                    "Cholesterol": (125, 200, 100, 300),
                    "WBC": (4, 11, 0, 20),
                    "Platelets": (150, 450, 0, 600),
                    "HbA1c": (4, 5.7, 3, 10)
                }
                
                # Show gauges for available parameters that have defined ranges
                cols = st.columns(2)
                idx = 0
                for param, info in param_info.items():
                    if param in normal_ranges:
                        normal_low, normal_high, min_val, max_val = normal_ranges[param]
                        value = info["value"]
                        if min_val <= value <= max_val:  # only show if within reasonable bounds
                            fig = create_gauge(value, param, min_val, max_val, normal_low, normal_high)
                            with cols[idx % 2]:
                                st.plotly_chart(fig, use_container_width=True)
                            idx += 1
                
                if idx == 0:
                    st.info("No critical parameters with defined normal ranges found in this report.")
            
            with tab3:
                st.subheader("Parameter vs. Normal Range")
                # Create a comparison chart with normal range bars
                comparison_data = []
                for param, info in param_info.items():
                    if param in normal_ranges:
                        normal_low, normal_high, _, _ = normal_ranges[param]
                        comparison_data.append({
                            "Parameter": param,
                            "Your Value": info["value"],
                            "Normal Low": normal_low,
                            "Normal High": normal_high
                        })
                if comparison_data:
                    comp_df = pd.DataFrame(comparison_data)
                    fig = go.Figure()
                    # Add bar for patient value
                    fig.add_trace(go.Bar(name="Your Value", x=comp_df["Parameter"], y=comp_df["Your Value"], marker_color="#2563eb"))
                    # Add error bars for normal range (low to high)
                    for i, row in comp_df.iterrows():
                        fig.add_annotation(
                            x=row["Parameter"],
                            y=row["Normal High"] + (row["Normal High"]-row["Normal Low"])*0.2,
                            text=f"Normal: {row['Normal Low']}-{row['Normal High']}",
                            showarrow=False,
                            font=dict(size=10, color="gray")
                        )
                    fig.update_layout(title="Your Values vs Normal Ranges", height=500)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No parameters with defined normal ranges to compare.")
            
            # Additional insight
            st.markdown("---")
            st.subheader("📋 Quick Interpretation")
            for param, info in param_info.items():
                if param in normal_ranges:
                    normal_low, normal_high, _, _ = normal_ranges[param]
                    val = info["value"]
                    if val < normal_low:
                        st.warning(f"⚠️ **{param}** is **LOW** ({val}). Normal range: {normal_low}-{normal_high}.")
                    elif val > normal_high:
                        st.warning(f"⚠️ **{param}** is **HIGH** ({val}). Normal range: {normal_low}-{normal_high}.")
                    else:
                        st.success(f"✅ **{param}** is **NORMAL** ({val}).")

# =========================================================
# CHATBOT
# =========================================================
elif selected == "Chatbot":
    st.title("💬 AI Medical Chatbot")
    if st.session_state.report_text:
        question = st.text_input("Ask your question about the report")
        if question:
            with st.spinner("Thinking..."):
                answer = ask_chatbot(question, st.session_state.report_text, st.session_state.extracted_params)
            st.markdown(f"<div class='card'><h3>🤖 Answer</h3><p>{answer}</p></div>", unsafe_allow_html=True)
    else:
        st.warning("Upload a report first.")

# =========================================================
# FOOTER
# =========================================================
st.markdown("---")
st.caption("© 2026 AI Medical Dashboard | Dynamic Parameter Extraction | Enhanced Analytics")