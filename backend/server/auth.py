from fastapi import Header, HTTPException


async def require_uid(x_api_key: str = Header(...)) -> str: 
    from vazhi.config import settings
    if x_api_key != settings.dev_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return settings.dev_uid