# Create the virtualenv and install pinned dependencies.
$ErrorActionPreference = "Stop"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Write-Host "Done. Copy .env.example to .env and fill it in."
