import os
import secrets

import uvicorn

if __name__ == "__main__":
    # Electron pasa su propio token; si se arranca a mano, se genera
    # uno aquí (antes de uvicorn, para que no cambie en cada recarga).
    if not os.environ.get("JD_API_TOKEN"):
        os.environ["JD_API_TOKEN"] = secrets.token_urlsafe(32)
        print(f"Token de la API: {os.environ['JD_API_TOKEN']}", flush=True)

    uvicorn.run("backend.api.main:app", host="127.0.0.1", port=8642, reload=True)
