import os
from google import genai

# Setup Client - ensure your API key is correct
client = genai.Client(api_key='', http_options={'api_version': 'v1beta'})

def check_available_models():
    print("--- Scanning for Video/Veo Models ---")
    try:
        # Fetching the list from the API
        model_list = client.models.list()
        
        found = False
        for model in model_list:
            # We check both name and display_name for 'veo' or 'video'
            if 'veo' in model.name.lower() or 'video' in model.name.lower():
                # Note: 'supported_actions' is the correct attribute for this SDK version
                print(f"ID: {model.name}")
                print(f"   Actions: {model.supported_actions}")
                print(f"   Display: {model.display_name}")
                print("-" * 30)
                found = True
        
        if not found:
            print("No Veo/Video models found. Printing all available models instead:")
            for model in model_list:
                print(f"ID: {model.name}")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    check_available_models()
