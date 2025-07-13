
import os, json, uuid, datetime, tempfile, pandas as pd, re
from langchain_openai import AzureChatOpenAI
import requests, boto3
from typing import Tuple
from state import session_state

 
# === Azure + AWS setup ===
BASE_URL = "https://chatgpt-nlpteam-dev.openai.azure.com/"
API_KEY = "c9b45fca1ad64622bdb26a44afeb2450"
DEPLOYMENT_NAME = "gpt-4o"
 
SPEECH_ENDPOINT = "https://openai-whisper-genai.openai.azure.com/"
SPEECH_KEY = "579464e821824b59b6824bd7f91fac69"
WHISPER_DEPLOYMENT_NAME = "genai-whisper"
WHISPER_API_VERSION = "2023-09-01-preview"
 
polly_client = boto3.client("polly", region_name="us-east-1", aws_access_key_id="AKIAUZE2WFS3G7TW2FHR", aws_secret_access_key="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")
 
llm = AzureChatOpenAI(
    azure_endpoint=BASE_URL,
    openai_api_version="2023-03-15-preview",
    deployment_name=DEPLOYMENT_NAME,
    openai_api_key=API_KEY,
    openai_api_type="azure",
    temperature=0.0
)
 
df = pd.read_csv("premium_reminder_dummy_data_updated.csv")
audio_folder = "audio"
os.makedirs(audio_folder, exist_ok=True)

def log_conversation(customer_id, user_text, bot_text, user_audio_path=None, bot_audio_path=None):
    if not session_state[customer_id].get("log_file_path"):
        # Try to reuse an existing log file
        existing_logs = sorted([
            f for f in os.listdir("logs")
            if f.startswith(f"session_{customer_id}_") and f.endswith(".jsonl")
        ])
        if existing_logs:
            session_state[customer_id]["log_file_path"] = os.path.join("logs", existing_logs[-1])
        else:
            # Create a new one
            os.makedirs("logs", exist_ok=True)
            timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            session_state[customer_id]["log_file_path"] = os.path.join(
                "logs", f"session_{customer_id}_{timestamp_str}.jsonl"
            )
 
    log_file = session_state[customer_id]["log_file_path"]
 
    log_entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "customer_id": customer_id,
        "user_text": user_text,
        "bot_text": bot_text,
        "user_audio_path": user_audio_path,
        "bot_audio_path": bot_audio_path,
    }
 
    with open(log_file, "a") as f:
        f.write(json.dumps(log_entry) + "\n")


# === Load & handle customer ===
def handle_customer_id(customer_id: str) -> Tuple[str, str]:
    print('cus',df.customer_id.dtypes)
    customer = df[df["customer_id"] == int(customer_id)].iloc[0].to_dict()
    honorific = "Mr." if customer["gender"] == "Male" else "Ms."
    name = customer["name"].split()[0]
    greeting = f"Greetings from Allianz PNB Life. May I speak to {honorific} {name}, please?"
    audio_path = speak_text(greeting)
    return greeting, audio_path
 
# === TTS ===
def speak_text(text: str) -> str:
    response = polly_client.synthesize_speech(Text=text, OutputFormat="mp3", VoiceId="Joanna", Engine="generative")
    path = os.path.join(audio_folder, f"bot_{uuid.uuid4().hex}.mp3")
    with open(path, "wb") as file:
        file.write(response["AudioStream"].read())
    return path
 
# === STT ===
def transcribe_audio(audio_file) -> str:
    url = f"{SPEECH_ENDPOINT}openai/deployments/{WHISPER_DEPLOYMENT_NAME}/audio/transcriptions?api-version={WHISPER_API_VERSION}"
    headers = {"api-key": SPEECH_KEY}
    files = {"file": ("audio.mp3", audio_file, "audio/mpeg")}
    data = {"response_format": "json"}
    response = requests.post(url, headers=headers, files=files, data=data)
    return response.json().get("text", "") if response.status_code == 200 else ""
 
# === Classify ===
def classify_customer_response(response_text: str) -> dict:
    prompt = f"""
You are an AI assistant helping with insurance premium reminders.
Classify this customer response: "{response_text}"
 
Respond ONLY in this format:
{{"scenario": 1, "sub_scenario": "not_available", "intent": "Customer confirmed they are available to talk"}}
"""
    try:
        response = llm.invoke([{"role": "user", "content": prompt}])
        return json.loads(response.content.strip())
    except:
        return {"scenario": 0, "intent": "unclear"}
 
# === Scenario Handler ===
def handle_scenario(scenario_data, customer) -> str:
    honorific = "Mr." if customer["gender"] == "Male" else "Ms."
    name = customer["name"].split()[0]
    due_date = datetime.datetime.strptime(customer["due_date"], "%m/%d/%Y").date()
    today = datetime.datetime.today().date()
 
    if scenario_data["scenario"] == 1:
        if due_date <= today:
            return f"Hi {honorific} {name}... you have missed your payment of {customer['amount_due']} {customer['currency']} due last {customer['due_date']}..."
        else:
            return f"Hi {honorific} {name}... Kindly pay your premium of {customer['amount_due']} {customer['currency']} on or before {customer['due_date']}..."
 
    if scenario_data["scenario"] == 2:
        if scenario_data.get("sub_scenario") == "wait":
            return f"Thank you. I will stay on the line. \n\nIs this {honorific} {name}?"
        elif scenario_data.get("sub_scenario") == "not_available":
            return "Thank you for that information. We will call again some other time."
        elif scenario_data.get("sub_scenario") == "wrong_number":
            return "Thank you for that information. Have a great day ahead."
        else:
            return "Thank you for your response. Have a good day!"
 
    default_messages = {
        3: "This is noted and we will monitor accordingly to ensure that it will reflect on your account timely.",
        4: "Thank you for the information. Kindly disregard this reminder...",
        5: "Thank you for taking my call. For other concerns, feel free to reach out..."
    }
 
    return default_messages.get(scenario_data["scenario"], "Thank you for your response.")
 
# === Full Audio Flow ===
def process_user_audio(audio_file, customer_id: str) -> Tuple[str, str, str]:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp:
        temp.write(audio_file.read())
        temp.flush()
        with open(temp.name, "rb") as f:
            transcript = transcribe_audio(f)
 
    transcript = re.sub(r"[^a-zA-Z0-9.,!?\"' ]+", "", transcript).strip()
    scenario_data = classify_customer_response(transcript)
    customer = df[df["customer_id"] == int(customer_id)].iloc[0].to_dict()
    bot_reply = handle_scenario(scenario_data, customer)
    audio_path = speak_text(bot_reply)
    return  transcript,bot_reply, audio_path