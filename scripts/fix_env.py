import os
from pathlib import Path

def load_env_manual():
    """
    Manually loads .env file from project root into os.environ.
    This bypasses potential issues with pydantic-settings or python-dotenv availability.
    """
    # Assuming script is run from project root or scripts/ subdir
    # Try to find .env by looking up
    
    candidates = [
        Path(".env"),
        Path("../.env"),
        Path("../../.env"),
        Path("Pedkai/.env")
    ]
    
    env_path = None
    for p in candidates:
        if p.exists():
            env_path = p
            break
            
    if not env_path:
        print("⚠️ fix_env: Could not find .env file!")
        return

    print(f"✅ fix_env: Loading .env from {env_path.absolute()}")
    
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                    
                # Force overwrite
                os.environ[key] = value
                # print(f"   Set {key}")
