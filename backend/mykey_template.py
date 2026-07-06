"""
GenericAgent local key configuration template.

Usage:
  1. Copy this file to mykey.py.
  2. Fill in your own API keys and optional SMTP settings.
  3. Keep mykey.py local. It is gitignored and must not be committed.

Notes:
  - Leave unused key slots blank or delete them from your local mykey.py.
  - The React/Electron frontend reads the active backend state; model keys are
    configured here, not through a browser form.
"""

# Optional SMTP email config for the legacy mobile/email login flow.
# For QQ mail, smtp_password should be the SMTP authorization code, not the
# normal account password.
smtp_email = ""
smtp_password = ""
smtp_server = "smtp.qq.com"
smtp_port = 465
allowed_email = ""
streamlit_password = ""


# Key1: primary DeepSeek OpenAI-compatible model.
key1_native_oai_config = {
    "name": "deepseek-v4-pro",
    "apikey": "",
    "apibase": "https://api.deepseek.com",
    "model": "deepseek-v4-pro",
    "stream": True,
    "max_retries": 1,
    "connect_timeout": 10,
    "read_timeout": 300,
}


# Key2: optional secondary DeepSeek model.
key2_native_oai_config = {
    "name": "deepseek-v4-flash",
    "apikey": "",
    "apibase": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",
    "stream": True,
    "max_retries": 1,
    "connect_timeout": 10,
    "read_timeout": 300,
}


# Key3: optional custom OpenAI-compatible endpoint.
key3_native_oai_config = {
    "name": "custom-openai-compatible",
    "apikey": "",
    "apibase": "",
    "model": "",
    "stream": True,
    "max_retries": 1,
    "connect_timeout": 10,
    "read_timeout": 300,
}
