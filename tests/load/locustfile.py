"""
Locust Load Test for Pedkai.
"""
from locust import HttpUser, task, between
import random
import uuid

class PedkaiLoadUser(HttpUser):
    wait_time = between(0.1, 0.5)  # Fast firing

    token = None

    def on_start(self):
        """Get a JWT token for the user."""
        response = self.client.post(
            "/api/v1/auth/token",
            data={"username": "operator", "password": "operator"}
        )
        if response.status_code == 200:
            self.token = response.json().get("access_token")
        else:
            print(f"Failed to get token: {response.text}")

    @task(3)
    def post_alarm(self):
        """Simulate sending alarms via TMF642 Ingress."""
        if not self.token:
            return
            
        alarm_id = str(uuid.uuid4())
        payload = {
            "id": alarm_id,
            "alarmType": "communicationsAlarm",
            "perceivedSeverity": random.choice(["critical", "major", "minor"]),
            "probableCause": random.choice(["cableCut", "powerLoss", "highBitErrorRate"]),
            "specificProblem": f"Test alarm {random.randint(1000, 9999)}",
            "state": "raised",
            "ackState": "unacknowledged",
            "eventTime": "2023-10-27T12:00:00Z",
            "raisedTime": "2023-10-27T12:00:00Z",
            "alarmedObject": {
                "id": f"Site-{random.randint(1, 100)}",
                "name": "Managed Asset"
            },
            "onap_type": "Alarm"
        }
        
        self.client.post(
            "/tmf-api/alarmManagement/v4/alarm", 
            json=payload, 
            headers={
                "X-Correlation-ID": alarm_id,
                "Authorization": f"Bearer {self.token}"
            }
        )

    @task(1)
    def check_health(self):
        """Check system health."""
        if not self.token:
            return
        
        self.client.get(
            "/tmf-api/alarmManagement/v4/alarm",
            headers={"Authorization": f"Bearer {self.token}"}
        )
