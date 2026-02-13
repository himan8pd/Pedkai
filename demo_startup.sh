# Activate the correct Python environment
source venv/bin/activate 

# set up local variables for demo
export DATABASE_URL="sqlite+aiosqlite:///./pedkai_demo.db"
export PEDKAI_POLICY_PATH="$(pwd)/backend/app/policies/global_policies.yaml"
export SECRET_KEY="demo-secret-key"

# start back end
python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

# start front end
./run_frontend.sh
