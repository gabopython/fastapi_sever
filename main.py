import uvicorn
from fastapi import FastAPI, Request, HTTPException
import tweepy
from typing import Dict
import os
import logging
import urllib.parse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")


app = FastAPI()

# In-memory storage for active sessions and OAuth handlers
# In production, replace this with Redis or a database.
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
    """
    Called by the Local Bot to get a login link.
    """
    if api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    oauth2_handler = get_oauth_handler()
    
    # Get the authorization URL - this generates the code_verifier and state internally
    authorization_url = oauth2_handler.get_authorization_url()
    
    # Parse the URL to extract Twitter's generated state
    parsed_url = urllib.parse.urlparse(authorization_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    twitter_state = query_params.get('state', [None])[0]
    
    logger.info(f"User state: {state}")
    logger.info(f"Twitter state: {twitter_state}")
    
    if twitter_state:
        # Map Twitter's state to our user state
        state_mapping[twitter_state] = state
        oauth_handlers[twitter_state] = (oauth2_handler, state)
        logger.info(f"Stored mapping: {twitter_state} -> {state}")
    else:
        logger.error("No state found in authorization URL")
        raise HTTPException(status_code=500, detail="Failed to generate authorization URL")
    
    logger.info(f"Active Twitter states: {list(oauth_handlers.keys())}")
    
    return {"url": authorization_url}

@app.get("/callback")
async def callback(request: Request):
    """
    Twitter redirects here. We exchange the code for a token.
    """
    code = request.query_params.get("code")
    twitter_state = request.query_params.get("state")
    error = request.query_params.get("error")

    logger.info(f"Callback received - Twitter state: {twitter_state}, code: {code[:20] if code else None}...")
    logger.info(f"Available Twitter states: {list(oauth_handlers.keys())}")

    if error:
        return {"error": error}
    
    if not code or not twitter_state:
        return {"error": "Missing code or state"}

    # Retrieve the OAuth handler using Twitter's state
    handler_data = oauth_handlers.get(twitter_state)
    if not handler_data:
        logger.error(f"No handler found for Twitter state: {twitter_state}")
        logger.error(f"Available states: {list(oauth_handlers.keys())}")
        return {"error": f"Session expired or invalid state. Available states: {len(oauth_handlers)}"}

    oauth2_handler, user_state = handler_data

    try:
        logger.info(f"Fetching token for user state: {user_state}")
        
        # Use the same OAuth handler that generated the authorization URL
        access_token = oauth2_handler.fetch_token(str(request.url))
        
        logger.info(f"Token fetched successfully for user state: {user_state}")
        
        # Store the token using the user state (Telegram User ID)
        session_store[user_state] = access_token
        
        # Clean up
        del oauth_handlers[twitter_state]
        del state_mapping[twitter_state]
        
        return {"message": "Login successful! You can close this window and return to the bot."}
    except Exception as e:
        logger.error(f"Error fetching token: {str(e)}")
        # Clean up on error
        if twitter_state in oauth_handlers:
            del oauth_handlers[twitter_state]
        if twitter_state in state_mapping:
            del state_mapping[twitter_state]
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

@app.get("/debug/states")
async def debug_states(api_key: str):
    """Debug endpoint to check active states"""
    if api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    return {
        "oauth_handlers": list(oauth_handlers.keys()),
        "state_mapping": state_mapping,
        "session_store": list(session_store.keys())
    }

if __name__ == "__main__":
    # IMPORTANT: Use only 1 worker to ensure in-memory state is preserved
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)