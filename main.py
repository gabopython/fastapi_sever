import uvicorn
from fastapi import FastAPI, Request, HTTPException
import tweepy
from typing import Dict
import os
import logging

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
oauth_handlers: Dict[str, tuple] = {}  # Store (handler, code_verifier, code_challenge)

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
    
    # Get the authorization URL - this generates the code_verifier internally
    authorization_url = oauth2_handler.get_authorization_url()
    
    # Extract and store the code_verifier and code_challenge
    code_verifier = oauth2_handler._client.code_verifier
    code_challenge = oauth2_handler._client.code_challenge
    
    logger.info(f"Generated auth URL for state: {state}")
    logger.info(f"Code verifier: {code_verifier[:20]}...")
    
    # Store the OAuth handler and PKCE values
    oauth_handlers[state] = (oauth2_handler, code_verifier, code_challenge)
    
    # Append state as a query parameter manually
    authorization_url_with_state = f"{authorization_url}&state={state}"
    
    logger.info(f"Active states: {list(oauth_handlers.keys())}")
    
    return {"url": authorization_url_with_state}

@app.get("/callback")
async def callback(request: Request):
    """
    Twitter redirects here. We exchange the code for a token.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    logger.info(f"Callback received - state: {state}, code: {code[:20] if code else None}...")
    logger.info(f"Available states: {list(oauth_handlers.keys())}")

    if error:
        return {"error": error}
    
    if not code or not state:
        return {"error": "Missing code or state"}

    # Retrieve the OAuth handler that was used to generate the authorization URL
    handler_data = oauth_handlers.get(state)
    if not handler_data:
        logger.error(f"No handler found for state: {state}")
        logger.error(f"Available states: {list(oauth_handlers.keys())}")
        return {"error": f"Session expired or invalid state. Available states: {len(oauth_handlers)}"}

    oauth2_handler, code_verifier, code_challenge = handler_data

    try:
        logger.info(f"Using code_verifier: {code_verifier[:20]}...")
        
        # Use the same OAuth handler that generated the authorization URL
        # This ensures the code_verifier matches
        access_token = oauth2_handler.fetch_token(str(request.url))
        
        logger.info(f"Token fetched successfully for state: {state}")
        
        # Store the token in memory associated with the state (Telegram User ID)
        session_store[state] = access_token
        
        # Clean up the OAuth handler as it's no longer needed
        del oauth_handlers[state]
        
        return {"message": "Login successful! You can close this window and return to the bot."}
    except Exception as e:
        logger.error(f"Error fetching token: {str(e)}")
        # Clean up on error
        if state in oauth_handlers:
            del oauth_handlers[state]
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
        "session_store": list(session_store.keys())
    }

if __name__ == "__main__":
    # IMPORTANT: Use only 1 worker to ensure in-memory state is preserved
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)