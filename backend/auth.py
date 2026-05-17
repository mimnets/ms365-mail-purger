import msal
import os
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TENANT_ID = os.getenv("TENANT_ID")
REDIRECT_URI = os.getenv("REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]

def get_confidential_client():
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
    )

def get_app_token() -> str:
    app = get_confidential_client()
    result = app.acquire_token_silent(GRAPH_SCOPE, account=None)

    if not result:
        result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)

    if "access_token" not in result:
        raise RuntimeError(
            f"Failed to acquire token: {result.get('error_description', 'Unknown error')}"
        )

    return result["access_token"]

def get_auth_url() -> str:
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    return app.get_authorization_request_url(
        scopes=["openid", "profile", "email"],
        redirect_uri=REDIRECT_URI,
        state="login"
    )

def exchange_code_for_token(code: str) -> dict:
    app = get_confidential_client()
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=["openid", "profile", "email"],
        redirect_uri=REDIRECT_URI,
    )
    return result
