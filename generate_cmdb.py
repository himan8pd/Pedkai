import os
import zipfile
import csv
import io
import json
import urllib.request
import urllib.parse
from urllib.error import HTTPError

# Configurable settings
DATAGERRY_URL = os.getenv("DATAGERRY_URL", "http://localhost:4000/rest")
DATAGERRY_USER = os.getenv("DATAGERRY_USER", "admin")
DATAGERRY_PASS = os.getenv("DATAGERRY_PASS", "admin")
CASINOLIMIT_ZIP = "/Volumes/Projects/Pedkai Data Store/COMIDDS/CasinoLimit/output.zip"

class DataGerryClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.token = None

    def _request(self, endpoint, method="GET", payload=None):
        # We now expect endpoint to ALREADY HAVE correct slashes
        url = f"{self.base_url}{endpoint}"
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f"Bearer {self.token}"

        data = None
        if payload is not None:
            data = json.dumps(payload).encode('utf-8')

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode())
        except HTTPError as e:
            if e.code != 409: # Ignore conflict/exists errors
                print(f"HTTPError on {url}: {e.code} {e.reason}")
                try:
                    error_data = e.read().decode()
                    print(f"Error Response: {error_data}")
                except:
                    pass
            return None
        except Exception as e:
            print(f"Error connecting to DataGerry at {url}: {e}")
            return None

    def login(self):
        # NO trailing slash for login
        print(f"Attempting login to {self.base_url}/auth/login...")
        res = self._request("/auth/login", "POST", {"user_name": self.username, "password": self.password})
        if res and 'token' in res:
            self.token = res['token']
            print("Login successful.")
        else:
            print("Login failed. Check DATAGERRY_USER and DATAGERRY_PASS.")

    def create_type(self, type_def):
        print(f"Ensuring Schema Type: {type_def['name']}")
        # Ensure author_id and version are set
        if 'author_id' not in type_def:
            type_def['author_id'] = 1
        if 'version' not in type_def:
            type_def['version'] = "1.0.0"

        # Trailing slash REQUIRED for types
        res = self._request("/types/", "POST", type_def)
        if not res:
            # Check if it already exists
            types = self._request("/types/", "GET")
            if types and 'results' in types:
                for t in types['results']:
                    if t['name'] == type_def['name']:
                        print(f"  Type {type_def['name']} already exists (ID: {t['public_id']})")
                        return {"result_id": t['public_id']}
        return res

    def create_object(self, type_id, data_dict):
        # Transform flat dict to DataGerry fields array
        fields = []
        for k, v in data_dict.items():
            fields.append({"name": k, "value": v})
        
        obj_def = {
            "type_id": type_id,
            "fields": fields,
            "active": True
        }
        # Trailing slash REQUIRED for objects
        res = self._request("/objects/", "POST", obj_def)
        return res

def parse_casinolimit_instances():
    """Extract instances from steps.csv inside the CasinoLimit dataset."""
    instances = []
    print(f"Extracting instances from {CASINOLIMIT_ZIP}...")
    try:
        with zipfile.ZipFile(CASINOLIMIT_ZIP, 'r') as z:
            target_file = None
            for name in z.namelist():
                if name.endswith('steps.csv'):
                    target_file = name
                    break
            
            if target_file:
                with z.open(target_file) as f:
                    content = f.read().decode('utf-8')
                    reader = csv.DictReader(io.StringIO(content))
                    for row in reader:
                        instances.append(row['instance'])
                print(f"Found {len(instances)} unique instances.")
            else:
                print("steps.csv not found in output.zip")
    except Exception as e:
        print(f"Failed to parse dataset: {e}")
    return instances

def main():
    print("Starting Automated Baseline CMDB Generation...")

    instances = parse_casinolimit_instances()
    if not instances:
        print("No instances found. Aborting.")
        return

    # Initialize client
    client = DataGerryClient(DATAGERRY_URL, DATAGERRY_USER, DATAGERRY_PASS)
    client.login()

    if not client.token:
        print("Aborting due to authentication failure.")
        return

    # Define the GameInstance Configuration Item Type
    instance_type = {
        "name": "GameInstance",
        "label": "Game Instance",
        "author_id": 1,
        "version": "1.0.0",
        "fields": [
            {"name": "instance_name", "label": "Instance Name", "type": "text", "required": True},
            {"name": "status", "label": "Status", "type": "text", "required": False}
        ],
        "render_meta": {
            "icon": "fa fa-cube",
            "sections": [{
                "type": "section",
                "name": "info",
                "label": "Information",
                "fields": ["instance_name", "status"]
            }],
            "summary": { "fields": ["instance_name"] }
        },
        "active": True
    }
    res_inst = client.create_type(instance_type)
    instance_type_id = res_inst.get("result_id") if res_inst else None

    # Define the NetworkZone (Machine) Configuration Item Type
    zone_type = {
        "name": "NetworkZone",
        "label": "Network Zone",
        "author_id": 1,
        "version": "1.0.0",
        "fields": [
            {"name": "hostname", "label": "Hostname", "type": "text", "required": True},
            {"name": "instance_ref", "label": "Instance Reference", "type": "text", "required": True},
            {"name": "role", "label": "Role", "type": "text", "required": True}
        ],
        "render_meta": {
            "icon": "fas fa-network-wired",
            "sections": [{
                "type": "section",
                "name": "info",
                "label": "Information",
                "fields": ["hostname", "instance_ref", "role"]
            }],
            "summary": { "fields": ["hostname"] }
        },
        "active": True
    }
    res_zone = client.create_type(zone_type)
    zone_type_id = res_zone.get("result_id") if res_zone else None

    if not instance_type_id or not zone_type_id:
        print("Failed to ensure schema types. Aborting object generation.")
        return

    print("\n--- Generating CMDB Objects ---")
    zones = ["start", "bastion", "meetingcam", "intranet"]
    
    total = len(instances)
    success_count = 0
    error_count = 0

    for i, inst in enumerate(instances):
        if (i+1) % 10 == 0:
            print(f"  Progress: {i+1}/{total} instances...")
            
        # Create GameInstance object
        res = client.create_object(instance_type_id, {
            "instance_name": inst,
            "status": "active"
        })
        if res: success_count += 1
        else: error_count += 1

        for zone in zones:
            res = client.create_object(zone_type_id, {
                "hostname": f"{zone}.{inst}.local",
                "instance_ref": inst,
                "role": zone
            })
            if res: success_count += 1
            else: error_count += 1
            
    print(f"\n[✔] Baseline CMDB Generation Finished.")
    print(f"Summary: {success_count} succeeded, {error_count} failed.")

if __name__ == "__main__":
    main()
