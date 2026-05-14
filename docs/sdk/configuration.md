# Configuration

The AP3 SDK requires minimal configuration to get started. Most settings are optional and have sensible defaults.

## Google AI Studio API Key

For agents using Google's Gemini models, you'll need an API key.

**1. Obtain an API Key:**

Visit [Google AI Studio](https://aistudio.google.com/app/apikey) and create a new API key.

**2. Configure the Key:**

Create a `.env` file in your project root:

```bash
cp .env.example .env
```

Add your key to the `.env` file:

```bash
GOOGLE_API_KEY="your-api-key-here"
```

**3. Load in Your Application:**

```python
from dotenv import load_dotenv
import os

load_dotenv()
api_key = os.getenv('GOOGLE_API_KEY')
```


## LLM configurations

### LLM Model Selection

```bash
# .env file
# Example :
MODEL_NAME="gemini-2.5-flash"  # Default
# MODEL_NAME="gemini-2.5-flash"
# MODEL_NAME="gemini-1.5-pro"
```

### Logging

```python
import logging

logging.basicConfig(level=logging.INFO)   # Default
logging.basicConfig(level=logging.DEBUG)  # Verbose debugging
```

## Project Structure

A typical project layout:

```
your-project/
├── .env                 # Environment variables (gitignored)
├── .env.example        
├── agents/
│   └── my_agent.py
└── main.py
```

## Next Steps

1. [Run the Quick Start](../codelab-privacy-agent.md) - Test your setup
2. [Explore Examples](https://github.com/lfdt-ap3/ap3/tree/main/examples) - Learn from working code
