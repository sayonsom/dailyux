from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    GOOGLE_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-2.5-pro"
    TZ: str = "Asia/Kolkata"
    # Explicit control over where LLM calls are executed.
    # "client" = never call LLMs on the server, return prompts/fallbacks instead
    # "server" = call the configured LLM from the backend (for local/dev only)
    LLM_MODE: str = "client"

settings = Settings()  # loads from env/.env
