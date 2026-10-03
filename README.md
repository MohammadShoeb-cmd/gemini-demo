# Gemini Python demo

This demo uses Python 3 and the Google Gen AI SDK. It reads your API key from the GEMINI_API_KEY environment variable.

Save your key once in PowerShell (replace YOUR_API_KEY with your key):

```powershell
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "YOUR_API_KEY", "User")
```

Open a new PowerShell window afterward. To use it immediately in the current window too:

```powershell
$env:GEMINI_API_KEY = [Environment]::GetEnvironmentVariable("GEMINI_API_KEY", "User")
```

Run in PowerShell from this directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

The program uses the environment variable automatically; no API key prompt is shown.
The virtual environment is already set up on this computer, so you can skip the first two commands.

Try a different prompt:

```powershell
.\.venv\Scripts\python.exe main.py "Explain Python in one sentence"
```

Documentation: https://ai.google.dev/gemini-api/docs/interactions-overview
