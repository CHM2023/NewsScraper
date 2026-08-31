$ErrorActionPreference = "Stop"
.\.venv\Scripts\python.exe -m uvicorn web.app:app --reload --port 8000
