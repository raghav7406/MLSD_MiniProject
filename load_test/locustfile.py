from locust import HttpUser, between, task


class PreAuthUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def submit_request(self):
        response = self.client.post("/api/v1/preauth", json={
            "member_id": "load-test-member", "policy_number": "LOAD-1",
            "policy_name": "Care Supreme", "diagnosis_name": "Cataract",
            "procedure_name": "Phacoemulsification", "admission_type": "PLANNED",
            "policy_tenure_months": 24, "estimated_cost": 50000,
        })
        if response.ok:
            task_id = response.json()["task_id"]
            self.client.get(f"/api/v1/preauth/{task_id}")
