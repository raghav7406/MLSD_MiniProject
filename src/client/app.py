import time

import requests
import streamlit as st


st.title("Health Insurance Pre-Authorisation")
base_url = st.sidebar.text_input("API URL", "http://localhost:8000")
with st.form("preauth"):
    member_id = st.text_input("Member ID")
    policy_number = st.text_input("Policy number")
    policy_name = st.text_input("Policy name", "Care Supreme")
    diagnosis = st.text_input("Diagnosis", "Cataract")
    procedure = st.text_input("Procedure", "Phacoemulsification")
    admission_type = st.selectbox("Admission type", ["PLANNED", "EMERGENCY", "DAYCARE"])
    tenure = st.number_input("Policy tenure (months)", min_value=0, max_value=120, value=24)
    cost = st.number_input("Estimated cost", min_value=1.0, value=50000.0)
    submitted = st.form_submit_button("Submit")

if submitted:
    payload = {
        "member_id": member_id,
        "policy_number": policy_number,
        "policy_name": policy_name,
        "diagnosis_name": diagnosis,
        "procedure_name": procedure,
        "admission_type": admission_type,
        "policy_tenure_months": tenure,
        "estimated_cost": cost,
    }
    response = requests.post(f"{base_url}/api/v1/preauth", json=payload, timeout=10)
    if response.ok:
        task_id = response.json()["task_id"]
        with st.spinner("Processing..."):
            for _ in range(30):
                result = requests.get(f"{base_url}/api/v1/preauth/{task_id}", timeout=10).json()
                if result["status"] != "PENDING":
                    break
                time.sleep(1)
        if result["status"] == "SUCCESS":
            output = result["result"]
            st.subheader(output["recommendation"])
            st.write(output["reason"])
            st.metric("Indicative limit", output["indicative_limit"])
            st.json(output["citations"])
        else:
            st.error("The request is still processing.")
    else:
        st.error(response.text)
