import os
import pandas as pd
from typing import List, Dict, Any, Optional
from backend.app.core.config import get_settings
from data_fabric.dataset_loaders import UniversalLoader

class KaggleLoader:
    """
    Loader for Kaggle datasets. Downloads CSV files and converts them
    to Pedkai DecisionTrace format.
    """
    
    _api = None
    
    @classmethod
    def _get_api(cls):
        """Initialize and authenticate Kaggle API."""
        if cls._api is None:
            settings = get_settings()
            
            # Set environment variables for Kaggle API
            if settings.kaggle_username:
                os.environ['KAGGLE_USERNAME'] = settings.kaggle_username
                print(f"🔑 Kaggle Username set: {settings.kaggle_username}")
            if settings.kaggle_key:
                os.environ['KAGGLE_KEY'] = settings.kaggle_key
                print(f"🔑 Kaggle Key set (starts with: {settings.kaggle_key[:8]}...)")
                
            if not os.environ.get('KAGGLE_USERNAME') or not os.environ.get('KAGGLE_KEY'):
                print("⚠️  MISSING KAGGLE CREDENTIALS in environment!")
                
            from kaggle.api.kaggle_api_extended import KaggleApi
            cls._api = KaggleApi()
            cls._api.authenticate()
        return cls._api
    
    @classmethod
    async def load_dataset(cls, dataset_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Downloads a Kaggle dataset and returns a list of samples.
        """
        api = cls._get_api()
        
        # Create a temporary directory for downloads
        download_path = f"/tmp/kaggle_{dataset_id.replace('/', '_')}"
        os.makedirs(download_path, exist_ok=True)
        
        print(f"📥 Downloading Kaggle dataset: {dataset_id} to {download_path}...")
        api.dataset_download_files(dataset_id, path=download_path, unzip=True)
        
        # Find the first CSV file in the directory
        csv_files = [f for f in os.listdir(download_path) if f.endswith('.csv')]
        if not csv_files:
            raise FileNotFoundError(f"No CSV files found in Kaggle dataset {dataset_id}")
            
        csv_file = os.path.join(download_path, csv_files[0])
        print(f"📊 Loading data from {csv_file}...")
        
        # Load CSV into pandas
        df = pd.read_csv(csv_file)
        
        # Convert to list of dicts and apply limit
        samples = df.head(limit).to_dict('records')
        
        # Clean up
        # Note: In a real production app we'd be more careful about cleanup, 
        # but for this script we'll leave it for now or delete later.
        
        return samples

    @classmethod
    def to_decision_traces(cls, samples: List[Dict[str, Any]], dataset_id: str) -> List[Dict[str, Any]]:
        """
        Converts a list of raw Kaggle samples to DecisionTrace format via UniversalLoader.
        """
        traces = []
        for sample in samples:
            # We use the existing UniversalLoader heuristics to map fields
            trace = UniversalLoader.to_decision_trace(sample, dataset_id=dataset_id)
            
            # Regional tagging based on common Kaggle telecom dataset metadata
            # (In a real app, we'd pass the region explicitly)
            traces.append(trace)
            
        return traces
