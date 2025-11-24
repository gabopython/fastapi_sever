import uvicorn
from fastapi import FastAPI, Request, HTTPException
import tweepy
from typing import Dict
import os

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")


app = FastAPI()

# In-memory storage for active sessions. 
# In production, replace this with Redis or a database.
session_store: Dict[str, dict] = {}

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

    try:
        oauth2_handler = get_oauth_handler()
        # The fetch_token method automatically uses the url in the request to validate
        access_token = oauth2_handler.fetch_token(str(request.url))
        
        # Store the token in memory associated with the state (Telegram User ID)
        session_store[state] = access_token
        
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
    
    token_data = session_store.get(state)
    if not token_data:
        return {"status": "pending"}
    
    # Optional: Clear from memory after retrieval to keep it stateless
    # del session_store[state] 
    
    return {"status": "ready", "token": token_data}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)