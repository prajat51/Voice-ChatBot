
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from utils import handle_customer_id, process_user_audio,log_conversation
import uuid
from state import session_state

import datetime
import os

#session_state = defaultdict(dict)
 
app = FastAPI()
 
# Enable CORS if required
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 

 
#app = FastAPI()
class CustomerRequest(BaseModel):
    customer_id: str
 
@app.post("/start-conversation/")
def start_conversation(req: CustomerRequest):
    print('req',req.customer_id)
    customer_id=str(req.customer_id)
    if customer_id not in session_state:
        session_state[customer_id] = {}
    if "log_file_path" not in session_state[customer_id]:
        os.makedirs("logs", exist_ok=True)
        timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_path= os.path.join("logs", f"session_{customer_id}_{timestamp_str}.jsonl")
        session_state[customer_id]["log_file_path"] =log_path
        print('he',session_state[customer_id]["log_file_path"])
        print('hello',log_path)
    session_state[customer_id]["last_customer_id"] = customer_id
    response_text, audio_path = handle_customer_id(customer_id)
    log_conversation(
        customer_id=customer_id,
        user_text="",
        bot_text=response_text,
        user_audio_path=None,
        bot_audio_path=audio_path,
    )
    return  {
        "bot_text": response_text,
        "bot_audio_path": audio_path
    }

 
@app.post("/user-response/")
async def user_response(audio: UploadFile = File(...), customer_id: str = Form(...)):
    customer_id=str(customer_id)
    transcript,bot_text, bot_audio_path = process_user_audio(audio.file, customer_id)
    print('tran',transcript)
    print("Customer ID received in user-response:", customer_id)
    print("Current session_state keys:", session_state.keys())
    print("session_state for customer:", session_state.get(customer_id, {}))

    log_conversation(
        customer_id=customer_id,
        user_text=transcript,
        bot_text=bot_text,
        user_audio_path=None,  # You can optionally log the uploaded path if needed
        bot_audio_path=bot_audio_path,
    )
    return {
        #"transcript": transcript,
        "bot_text": bot_text,
        "bot_audio_path": bot_audio_path
    }