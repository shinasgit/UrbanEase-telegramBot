import sys
import ollama

# Ensure UTF-8 output encoding for terminal on Windows
if sys.platform == "win32":
    try:
        if sys.stdout and sys.stdout.encoding != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and sys.stderr.encoding != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Model configuration
MODEL_NAME = "llama3.2:3b"

# System prompt defining the UrbanEase AI role
SYSTEM_PROMPT = (
    "You are the AI assistant for UrbanEase, a comprehensive smart platform for "
    "home rentals (houses, flats, PGs, hostels), rental appliances and furniture, "
    "rental vehicles, and local helper services (electricians, plumbers, etc.). "
    "Respond in a helpful, friendly, and concise manner."
)


def test_ai() -> None:
    """
    Sends a test message to the local Ollama Llama 3.2 model to verify communication.
    Prints the AI response clearly in the terminal or shows a helpful error message.
    """
    print(f"🔄 Connecting to Ollama AI model: {MODEL_NAME}...")

    try:
        # Send chat message to Ollama
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": "Hello! Please confirm that the UrbanEase AI connection is working successfully.",
                },
            ],
        )

        # Retrieve AI response text
        content = (
            response.message.content
            if hasattr(response, "message")
            else response["message"]["content"]
        )

        print("\n🤖 AI Response:")
        print(content.strip())
        print("\n✅ UrbanEase AI connection test completed successfully!")

    except Exception as exc:
        print("\n❌ Failed to connect to Ollama AI model!")
        print(f"Error details: {exc}")
        print("\n💡 Troubleshooting Tips:")
        print("  1. Ensure the Ollama desktop app or service is running on your computer.")
        print(f"  2. Verify that '{MODEL_NAME}' is installed by running: ollama list")
        print(f"  3. If missing, download it using: ollama pull {MODEL_NAME}")


if __name__ == "__main__":
    test_ai()

