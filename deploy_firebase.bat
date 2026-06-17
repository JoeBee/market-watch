@echo off
setlocal
cd /d "%~dp0"

set PROJECT=market-watch-15a51
set REGION=us-central1
set SERVICE=market-watch

echo === Market Watch Firebase deploy ===
echo Project: %PROJECT%
echo.

gcloud config set project %PROJECT%
if errorlevel 1 goto :fail

echo Checking billing...
for /f "tokens=*" %%i in ('gcloud billing projects describe %PROJECT% --format^="value(billingEnabled)" 2^>nul') do set BILLING=%%i
if not "%BILLING%"=="True" (
  echo.
  echo ERROR: Billing is not enabled on %PROJECT%.
  echo Enable the Blaze plan at:
  echo   https://console.firebase.google.com/project/%PROJECT%/usage/details
  echo.
  echo Cloud Run is required for the FastAPI backend. Retry this script after upgrading.
  exit /b 1
)

echo Enabling required APIs...
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com --project=%PROJECT% --quiet
if errorlevel 1 goto :fail

echo.
echo Deploying Cloud Run service "%SERVICE%"...
gcloud run deploy %SERVICE% ^
  --source . ^
  --region %REGION% ^
  --allow-unauthenticated ^
  --memory 2Gi ^
  --cpu 2 ^
  --timeout 3600 ^
  --min-instances 1 ^
  --max-instances 1 ^
  --project %PROJECT%
if errorlevel 1 goto :fail

echo.
echo Deploying Firebase Hosting (proxies to Cloud Run)...
firebase deploy --only hosting --project %PROJECT% --non-interactive
if errorlevel 1 goto :fail

echo.
echo Done! Live at:
echo   https://%PROJECT%.web.app
echo   https://%PROJECT%.firebaseapp.com
exit /b 0

:fail
echo.
echo Deploy failed. See errors above.
exit /b 1
