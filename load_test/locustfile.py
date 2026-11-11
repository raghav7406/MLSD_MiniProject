"""Load testing script covering the full request lifecycle."""
import time
import random
from locust import HttpUser, between, task, constant_throughput

VALID_PAYLOADS = [
    {
        "member_id": "M-1001", "policy_number": "P-2001", "policy_name": "Care Supreme",
        "diagnosis_name": "Cataract", "procedure_name": "Phacoemulsification",
        "admission_type": "PLANNED", "policy_tenure_months": 24, "estimated_cost": 35000,
    },
    {
        "member_id": "M-1002", "policy_number": "P-2002", "policy_name": "Care Supreme",
        "diagnosis_name": "Acute appendicitis", "procedure_name": "Emergency hospitalisation",
        "admission_type": "EMERGENCY", "policy_tenure_months": 6, "estimated_cost": 80000,
    },
    {
        "member_id": "M-1003", "policy_number": "P-2003", "policy_name": "Care Supreme",
        "diagnosis_name": "Chronic kidney disease", "procedure_name": "Haemodialysis",
        "admission_type": "DAYCARE", "policy_tenure_months": 12, "estimated_cost": 15000,
    },
    {
        "member_id": "M-1004", "policy_number": "P-2004", "policy_name": "Care Supreme",
        "diagnosis_name": "Pneumonia", "procedure_name": "Hospitalisation",
        "admission_type": "PLANNED", "policy_tenure_months": 18, "estimated_cost": 40000,
    },
]

INVALID_PAYLOAD = {"member_id": ""}


class PreAuthUser(HttpUser):
    wait_time = between(1, 3)

    @task(8)
    def full_lifecycle(self):
        """Submit + poll the complete request lifecycle."""
        payload = random.choice(VALID_PAYLOADS)
        payload_copy = dict(payload)
        payload_copy["member_id"] = f"{payload['member_id']}-{random.randint(1000, 9999)}"

        with self.client.post(
            "/api/v1/preauth",
            json=payload_copy,
            name="/api/v1/preauth [submit]",
            catch_response=True,
        ) as submit_resp:
            if not submit_resp.ok:
                submit_resp.failure(f"Submit failed: {submit_resp.status_code}")
                return
            task_id = submit_resp.json().get("task_id")
            if not task_id:
                submit_resp.failure("No task_id in response")
                return

        # Poll up to 10 times
        for _ in range(10):
            time.sleep(0.5)
            with self.client.get(
                f"/api/v1/preauth/{task_id}",
                name="/api/v1/preauth/{task_id} [poll]",
                catch_response=True,
            ) as poll_resp:
                if not poll_resp.ok:
                    poll_resp.failure(f"Poll failed: {poll_resp.status_code}")
                    break
                data = poll_resp.json()
                if data.get("status") != "PENDING":
                    break

    @task(1)
    def invalid_submission(self):
        """Submit invalid payload – should return 422."""
        with self.client.post(
            "/api/v1/preauth",
            json=INVALID_PAYLOAD,
            name="/api/v1/preauth [invalid]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 422:
                resp.success()
            else:
                resp.failure(f"Expected 422, got {resp.status_code}")

    @task(2)
    def health_check(self):
        self.client.get("/health", name="/health")

    @task(1)
    def metrics_check(self):
        self.client.get("/metrics", name="/metrics")
