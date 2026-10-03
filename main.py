import os
import sys

from google import genai

def main():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Set the GEMINI_API_KEY environment variable before running this program.")
    prompt = " ".join(sys.argv[1:]) or "Explain how AI works in a few words"
    try:
        with genai.Client(api_key=api_key) as client:
            interaction = client.interactions.create(
                model="gemini-3.8-flash",
                input=prompt,
            )
            print(interaction.output_text)
    except Exception as exc:
        # Redact the key if it appears in an SDK error.
        raise SystemExit(str(exc).replace(api_key, "[REDACTED]")) from None


if __name__ == "__main__":
    main()
