@echo off
title PG Accountant — WhatsApp Setup Guide (Meta Cloud API)
color 0A

echo.
echo ============================================================
echo   PG Accountant — WhatsApp Setup (Meta Cloud API — FREE)
echo ============================================================
echo.
echo  Follow these steps ONE TIME to connect WhatsApp.
echo  No Twilio account needed. Meta gives 1,000 free messages/month.
echo.
echo ============================================================
echo   STEP 1 — Create a Meta Developer App
echo ============================================================
echo.
echo  1. Go to: https://developers.facebook.com
echo  2. Click "My Apps" ^> "Create App"
echo  3. Choose "Business" type ^> give it any name
echo  4. Add the "WhatsApp" product to your app
echo.
pause

echo.
echo ============================================================
echo   STEP 2 — Get Your Credentials
echo ============================================================
echo.
echo  In your Meta App ^> WhatsApp ^> API Setup:
echo.
echo  a) WHATSAPP_TOKEN:
echo     Copy the "Temporary access token" shown on the page.
echo     (For permanent token, create a System User in Business Settings)
echo.
echo  b) WHATSAPP_PHONE_NUMBER_ID:
echo     Copy the "Phone number ID" shown below the token.
echo.
echo  Paste both values into your .env file.
echo.
pause

echo.
echo ============================================================
echo   STEP 3 — Start the API + expose with ngrok
echo ============================================================
echo.
echo  Open TWO terminal windows:
echo.
echo  Terminal 1 — Start FastAPI:
echo    START_API.bat
echo.
echo  Terminal 2 — Install and run ngrok:
echo    Download ngrok from https://ngrok.com/download
echo    Then run:  ngrok http 8000
echo    Copy the "Forwarding" URL (looks like https://xxxx.ngrok.io)
echo.
pause

echo.
echo ============================================================
echo   STEP 4 — Register Webhook in Meta Dashboard
echo ============================================================
echo.
echo  In your Meta App ^> WhatsApp ^> Configuration:
echo.
echo  1. Click "Edit" next to Webhook
echo  2. Callback URL : https://YOUR-NGROK-URL/webhook/whatsapp
echo  3. Verify Token : pg-accountant-verify
echo     (or whatever you set as WHATSAPP_VERIFY_TOKEN in .env)
echo  4. Click "Verify and Save"
echo  5. Subscribe to the "messages" webhook field
echo.
pause

echo.
echo ============================================================
echo   STEP 5 — Test It!
echo ============================================================
echo.
echo  Send a WhatsApp message to the test number shown in
echo  Meta ^> WhatsApp ^> API Setup.
echo.
echo  Try sending:  "Add rent 8000 from Rahul"
echo  You should get a reply from the bot!
echo.
echo ============================================================
echo   ALL DONE!
echo ============================================================
echo.
echo  To run the full interactive setup:
echo    python -m cli.configure_workflow
echo.
pause
