"""Run the local TokenHarbor proxy with automatic 17-key rotation."""
import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

from kaggle_engine_worker import run_cline_proxy_server

if __name__ == "__main__":
    print("=" * 60)
    print("TokenHarbor 17-Key Rotating Proxy")
    print("Base URL for Cline: http://127.0.0.1:8080/v1")
    print("Model ID:           deepseek-v4.1-flash:free")
    print("API Key:            tokenharbor-local-proxy (or any text)")
    print("=" * 60)
    print("Listening on http://127.0.0.1:8080 ... (Press Ctrl+C to stop)")
    run_cline_proxy_server()
