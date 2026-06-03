@echo off
REM ---------------------------------------------------------------------------
REM tunnel.bat - expose the Analyst App publicly via a Cloudflare quick tunnel.
REM
REM PREREQUISITES:
REM   1. The analyst app is running (python app.py) so the site is up on port 5051.
REM   2. cloudflared is installed:
REM          winget install --id Cloudflare.cloudflared
REM      or download from:
REM          https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
REM
REM This uses a "quick tunnel" (no Cloudflare account needed). Cloudflare assigns
REM a RANDOM https://<words>.trycloudflare.com URL that changes every run.
REM The URL is highlighted in GREEN below - share it with analysts or the boss.
REM
REM For a PERMANENT URL with login-gating (recommended for analyst access):
REM   Set up a Named Tunnel + Cloudflare Access in your Cloudflare dashboard.
REM ---------------------------------------------------------------------------

echo Starting Cloudflare quick tunnel to http://localhost:5051 ...
echo Look for the GREEN https://*.trycloudflare.com line below - that is your URL.
echo (Ctrl+C to stop the tunnel.)
echo.

powershell -NoProfile -Command "& cloudflared tunnel --url http://localhost:5051 2>&1 | ForEach-Object { if ($_ -match 'trycloudflare\.com') { Write-Host $_ -ForegroundColor Green } else { Write-Host $_ } }"
