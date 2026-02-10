"""
Locust Load Test for Pedkai.
"""
from locust import HttpUser, task, between
import random
import uuid

class PedkaiLoadUser(HttpUser):
    wait_time = between(0.1, 0.5)  # Fast firing

    @task(3)
    def post_alarm(self):
        """Simulate sending alarms."""
        alarm_id = str(uuid.uuid4())
        payload = {
            "sourceSystemId": "load-test-01",
            "specificProblem": random.choice(["LinkFailure", "PowerLoss", "HighBER", "CpuHigh"]),
            "perceivedSeverity": random.choice(["CRITICAL", "MAJOR", "MINOR"]),
            "managedObjectInstance": f"Site-{random.randint(1, 100)}",
            "eventTime": "2023-10-27T12:00:00Z",
            "externalCorrelationId": alarm_id
        }
        
        self.client.post("/tmf-api/alarmManagement/v4/alarm", json=payload, headers={"X-Correlation-ID": alarm_id})

    @task(1)
    def check_health(self):
        """Check system health."""
        self.client.get("/tmf-api/alarmManagement/v4/alarm")
