import uvicorn
from fastapi import FastAPI, Request, HTTPException
import tweepy
from typing import Dict
import os
from fastapi.responses import HTMLResponse
import urllib.parse

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

app = FastAPI()

# In-memory storage
session_store: Dict[str, dict] = {}
oauth_handlers: Dict[str, tuple] = {}  # Store (handler, user_state)
state_mapping: Dict[str, str] = {}  # Map Twitter's state to our user state


def get_oauth_handler():
    return tweepy.OAuth2UserHandler(
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        scope=["tweet.read", "tweet.write", "users.read", "offline.access"],
        client_secret=CLIENT_SECRET,
    )


@app.get("/")
async def root():
    return {"status": "running"}


@app.get("/generate_url")
async def generate_auth_url(state: str, api_key: str):
    if api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    oauth2_handler = get_oauth_handler()
    authorization_url = oauth2_handler.get_authorization_url()

    # Extract Twitter's state
    parsed_url = urllib.parse.urlparse(authorization_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    twitter_state = query_params.get("state", [None])[0]

    if not twitter_state:
        raise HTTPException(status_code=500, detail="Failed to generate authorization URL")

    state_mapping[twitter_state] = state
    oauth_handlers[twitter_state] = (oauth2_handler, state)

    return {"url": authorization_url}


@app.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    twitter_state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        return {"error": error}

    if not code or not twitter_state:
        return {"error": "Missing code or state"}

    handler_data = oauth_handlers.get(twitter_state)
    if not handler_data:
        return {"error": "Session expired or invalid state"}

    oauth2_handler, user_state = handler_data

    try:
        access_token = oauth2_handler.fetch_token(str(request.url))
        session_store[user_state] = access_token

        del oauth_handlers[twitter_state]
        del state_mapping[twitter_state]

        html_content = """<!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Login Successful</title>
                <style>
                body {
                    background-color: #000000;
                    color: #FFFFFF;
                    font-family: Arial, sans-serif;
                    text-align: center;
                    padding: 50px;
                }
                .container {
                    background: linear-gradient(135deg, #71A58D, #3B7393);
                    border-radius: 15px;
                    padding: 30px;
                    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
                }
                h1 {
                    color: #FFFFFF;
                }
                p {
                    color: #FFFFFF;
                    font-size: 18px;
                }
                </style>
            </head>
            <body>
                <div class="container">
                <h1>✅ Login Successful!</h1>
                <p>You can close this window and return to Telegram.</p>
                </div>
            </body>
            </html>"""

        return HTMLResponse(content=html_content, status_code=200, media_type="text/html")


    except Exception as e:
        if twitter_state in oauth_handlers:
            del oauth_handlers[twitter_state]
        if twitter_state in state_mapping:
            del state_mapping[twitter_state]
        return {"error": str(e)}


@app.get("/get_session")
async def get_session(state: str, api_key: str):
    if api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")

    token_data = session_store.get(state)
    if not token_data:
        return {"status": "pending"}

    return {"status": "ready", "token": token_data}


@app.get("/delete_session")
async def delete_session(state: str, api_key: str):
    if api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")

    if state in session_store:
        del session_store[state]

    return {"status": "deleted"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)
