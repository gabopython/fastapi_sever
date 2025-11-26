import uvicorn
from fastapi import FastAPI, Request, HTTPException
import tweepy
from typing import Dict
import os

# Ensure these are set in your environment
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

app = FastAPI()

# Session store structure:
# {
#   "telegram_user_id": {
#       "verifier": "pkce_verifier_string",
#       "token": "access_token_data",
#       "status": "pending" | "ready"
#   }
# }
session_store: Dict[str, dict] = {}

def get_oauth_handler():
    """
    Creates a new Tweepy OAuth2UserHandler instance.
    """
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
    """
    Called by the Local Bot to get a login link.
    """
    if api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    oauth2_handler = get_oauth_handler()
    # We pass 'state' to Twitter so it comes back in the callback
    # This links the Telegram user to the Twitter login
    authorization_url = oauth2_handler.get_authorization_url(state=state)
    return {"url": authorization_url}

@app.get("/callback")
async def callback(request: Request):
    """
    Twitter redirects here. We exchange the code for a token.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        return {"error": error}
    
    if not code or not state:
        return {"error": "Missing code or state"}

    # Retrieve the session to get the stored verifier
    session_data = session_store.get(state)
    
    if not session_data or "verifier" not in session_data:
        return {"error": "Session expired or invalid state"}

    try:
        oauth2_handler = get_oauth_handler()
        
        # FIX 3: Manually fetch token with stored verifier
        # We cannot use oauth2_handler.fetch_token() directly because 
        # this new handler instance doesn't know the original verifier.
        # We use the underlying .oauth object and pass the stored verifier.
        access_token = oauth2_handler.oauth.fetch_token(
            token_url="https://api.twitter.com/2/oauth2/token",
            authorization_response=str(request.url),
            client_secret=CLIENT_SECRET,
            code_verifier=session_data["verifier"]
        )
        
        # Update session with the token
        session_store[state]["token"] = access_token
        session_store[state]["status"] = "ready"
        
        # Clean up the verifier as it is no longer needed
        del session_store[state]["verifier"]
        
        return {"message": "Login successful! You can close this window and return to the bot."}
    except Exception as e:
        return {"error": str(e)}

@app.get("/get_session")
async def get_session(state: str, api_key: str):
    """
    Called by Local Bot to retrieve the stored token.
    """
    if api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    session_data = session_store.get(state)
    
    if not session_data:
        return {"status": "not_found"}

    if session_data.get("status") == "ready":
        token = session_data.get("token")
        # Cleanup memory after successful retrieval
        del session_store[state]
        return {"status": "ready", "token": token}
    
    return {"status": "pending"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)