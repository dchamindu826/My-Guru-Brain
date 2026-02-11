from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
from supabase import create_client
import google.generativeai as genai
import os
import re
import time
import json
from dotenv import load_dotenv
from typing import Optional

# Load Env
load_dotenv()

app = FastAPI(title="My Guru AI API")

# --- CONFIG ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

# --- DATA MODELS ---
class ChatRequest(BaseModel):
    question: str
    subject: str
    medium: str

# --- HELPER FUNCTIONS (From your original code) ---
def safe_google_api_call(prompt):
    try:
        return model.generate_content(prompt).text
    except Exception as e:
        return None

def search_database(keywords, subject, medium):
    all_hits = []
    seen = set()
    for kw in keywords:
        query = supabase.table("documents").select("content").eq("metadata->>subject", subject).eq("metadata->>medium", medium).ilike("content", f"%{kw}%").limit(5)
        results = query.execute()
        for item in results.data:
            if item['content'] not in seen:
                all_hits.append(item['content'])
                seen.add(item['content'])
    return all_hits

def get_image(fig_id, subject, medium):
    if not fig_id: return None
    try:
        res = supabase.table("content_library").select("image_url, description").eq("subject", subject).eq("medium", medium).ilike("description", f"%Figure {fig_id}%").limit(1).execute()
        return res.data[0] if res.data else None
    except:
        return None

# --- API KEY VALIDATION ---
async def verify_api_key(x_api_key: str = Header(...)):
    # 1. Check if key exists and is active
    res = supabase.table("api_keys").select("*").eq("key_string", x_api_key).eq("is_active", True).execute()
    
    if not res.data:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    key_data = res.data[0]
    
    # 2. Check Expiry
    if key_data['expires_at'] and key_data['expires_at'] < time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()):
        raise HTTPException(status_code=403, detail="API Key Expired")

    # 3. Check Credits
    if not key_data['is_unlimited'] and key_data['credits'] <= 0:
        raise HTTPException(status_code=402, detail="Insufficient Credits")

    return key_data

# --- MAIN CHAT ENDPOINT ---
@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest, key_data: dict = Depends(verify_api_key)):
    
    # 1. Intent Analysis (Transliteration)
    prompt_intent = f"""
    Transliterate Singlish to Sinhala. Output JSON: {{ "interpreted_question": "...", "keywords": [...] }}
    Input: {request.question}, Subject: {request.subject}
    """
    intent_res = safe_google_api_call(prompt_intent)
    try:
        # Clean JSON
        cleaned_json = intent_res.replace("```json", "").replace("```", "").strip()
        decoded = json.loads(cleaned_json)
        q_sinhala = decoded.get("interpreted_question", request.question)
        keywords = decoded.get("keywords", [])
    except:
        q_sinhala = request.question
        keywords = [request.question]

    # 2. Search Context
    context_hits = search_database(keywords, request.subject, request.medium)
    context_text = "\n".join(context_hits)

    if not context_hits:
        return {"answer": "සමාවෙන්න, මට ඒ ගැන කරුණු හමු නොවුණා.", "image": None, "credits_left": key_data['credits']}

    # 3. Generate Answer
    final_prompt = f"""
    Role: O/L Tutor. Subject: {request.subject}. Medium: {request.medium}.
    Context: {context_text}
    Question: {q_sinhala}
    Answer in {request.medium}. If you mention a Figure ID (e.g. 8.1), use EXACT ID.
    """
    answer = safe_google_api_call(final_prompt)

    # 4. Find Image ID
    fig_match = re.search(r"(\d+\.\d+)", answer)
    image_data = None
    if fig_match:
        image_data = get_image(fig_match.group(1), request.subject, request.medium)

    # 5. DEDUCT CREDIT (If not unlimited)
    if not key_data['is_unlimited']:
        new_credits = key_data['credits'] - 1
        supabase.table("api_keys").update({"credits": new_credits}).eq("id", key_data['id']).execute()
        credits_left = new_credits
    else:
        credits_left = "Unlimited"

    return {
        "question_interpreted": q_sinhala,
        "answer": answer,
        "image": image_data,
        "credits_left": credits_left
    }