from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    GOOGLE_API_KEY: str | None = None
    GOOGLE_MAPS_API_KEY: str | None = None  # Optional separate key for Maps/Places
    GEMINI_MODEL: str = "gemini-2.5-pro"
    TZ: str = "Asia/Kolkata"
    # Explicit control over where LLM calls are executed.
    # "client" = never call LLMs on the server, return prompts/fallbacks instead
    # "server" = call the configured LLM from the backend (for local/dev only)
    LLM_MODE: str = "server"

    def maps_key(self) -> str | None:
        return self.GOOGLE_MAPS_API_KEY or self.GOOGLE_API_KEY

settings = Settings()  # loads from env/.env
