import os
import requests

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
DEFAULT_MODEL = "mistral-small-latest"


def mistral_chat(messages, model=None, temperature=0.3, timeout=60):
    """
    messages: [{role: "system"|"user"|"assistant", content: "..."}]
    """
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise ValueError("Falta MISTRAL_API_KEY en las variables de entorno")

    model = model or os.getenv("MISTRAL_MODEL", DEFAULT_MODEL)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    r = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    content = data["choices"][0]["message"]["content"]
    return {
        "assistant_message": content.strip(),
        "raw": data,
        "model": model,
    }
