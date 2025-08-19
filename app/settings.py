from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    GOOGLE_API_KEY: str
    GEMINI_MODEL: str = "gemini-1.5-pro"
    TZ: str = "Asia/Kolkata"

settings = Settings()  # loads from env/.env
