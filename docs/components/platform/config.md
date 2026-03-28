# Configuration — Environment-Driven Settings

**What:** All config from environment variables. No hardcoding.

**Where:** `platform/config/settings.py`

---

## Access Settings

```python
from platform.config import get_settings

settings = get_settings()
model = settings.llm_model  # Read from LLM_MODEL env var
threshold = settings.classification_confidence_threshold
```

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```bash
# LLM
LLM_MODEL=claude-3-5-sonnet-20241022
LLM_TEMPERATURE=0.0
LLM_MAX_RETRIES=3
LLM_MAX_TOKENS=2048

# Database
POSTGRES_DSN=postgresql://user:pass@localhost:5432/enterprise_ai

# Cache & Pub/Sub
REDIS_URL=redis://localhost:6379

# Vector Store
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=requirements

# Guardrails
MAX_FILE_SIZE_MB=50
INJECTION_DETECTION_THRESHOLD=0.5

# Phase Thresholds
CLASSIFICATION_CONFIDENCE_THRESHOLD=0.75
SANITY_GATE_CONFIDENCE_THRESHOLD=0.85
```

## Adding a New Setting

1. **Add env var:**
   ```bash
   echo "MY_NEW_SETTING=value" >> .env
   ```

2. **Add to Pydantic Settings:**
   ```python
   # platform/config/settings.py
   class Settings(BaseSettings):
       my_new_setting: str = Field(default="default_value")
   ```

3. **Use in code:**
   ```python
   settings = get_settings()
   value = settings.my_new_setting
   ```

## Per-Environment Config

```bash
# .env.local (for local development)
LLM_MODEL=claude-3-5-sonnet-20241022
POSTGRES_DSN=postgresql://localhost:5432/dev

# .env.test (for testing)
LLM_MODEL=claude-3-5-sonnet-20241022
POSTGRES_DSN=postgresql://localhost:5432/test
```

Load in code:
```python
from platform.config import get_settings
settings = get_settings(_env_file=".env.local")  # If needed
```

## Override in Tests

```python
@pytest.fixture
def test_settings():
    return Settings(
        llm_max_retries=1,  # Faster tests
        postgres_dsn="sqlite:///:memory:",  # No DB
        qdrant_url="http://localhost:6333"  # Real Qdrant for integration tests
    )

async def test_phase1_with_custom_settings(test_settings):
    # Use test_settings instead of get_settings()
    result = await phase1_node(input_data, config=test_settings)
```

## Validation

All settings are Pydantic v2 models. Invalid env vars raise errors on startup:

```python
# If POSTGRES_DSN is missing or malformed
# → pydantic.ValidationError on app start
```

## Secrets (Not in .env)

For production, use a secrets manager:

- **AWS Secrets Manager** — `get_secret("llm-api-key")`
- **HashiCorp Vault** — `vault.read("secret/llm-key")`
- **Kubernetes Secrets** — Mounted as env vars

See `platform/config/secrets.py` for integration.

## See Also

- `.env.example` — Template
- `platform/config/settings.py` — Full Settings class
- [PATTERNS.md](../../guides/PATTERNS.md) — How to use in phase nodes
