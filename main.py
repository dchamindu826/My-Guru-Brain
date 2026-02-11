from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
from supabase import create_client, Client
from google import genai # 🔥 අලුත් Library එක
from dotenv import load_dotenv
import os
import re
import time
import json

# --- SETUP ---
load_dotenv()
app = FastAPI(title="My Guru Brain API")

# --- CONFIGURATION CHECK ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip() # Strip spaces
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY or not GOOGLE_API_KEY:
    print("❌ Critical Error: Keys missing in .env file")

# Initialize Clients
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    # 🔥 Streamlit Code එකේ තිබ්බ විදියටම Client හදනවා
    client = genai.Client(api_key=GOOGLE_API_KEY)
except Exception as e:
    print(f"❌ Initialization Error: {e}")

# --- DATA MODELS ---
class ChatRequest(BaseModel):
    question: str
    subject: str
    medium: str

# ==========================================
# 👇 CORE LOGIC (From Streamlit Code)
# ==========================================

def clean_json_text(text):
    text = text.strip()
    if text.startswith("```json"): text = text[7:]
    if text.startswith("```"): text = text[3:]
    if text.endswith("```"): text = text[:-3]
    return text.strip()

def safe_google_api_call(contents, config=None, retries=3):
    for attempt in range(retries):
        try:
            # 🔥 Streamlit Code එකේ Logic එකමයි (gemini-2.0-flash)
            if config:
                return client.models.generate_content(model='gemini-2.0-flash', contents=contents, config=config)
            else:
                return client.models.generate_content(model='gemini-2.0-flash', contents=contents)
        except Exception as e:
            if "429" in str(e):
                time.sleep((attempt + 1) * 2)
                continue
            print(f"Gemini Error: {e}")
            return None
    return None

def identify_best_figure_id(context_items, user_question, ai_answer):
    # 1. Fast Regex Check on Answer
    if ai_answer:
        match = re.search(r"(\d+\.\d+)", ai_answer)
        if match:
            return match.group(1)

    if not context_items: return None

    context_text = "\n".join([item['content'] for item in context_items[:4]]) 

    prompt = f"""
    Analyze the CONTEXT, USER QUESTION, and AI ANSWER to find the most relevant Figure ID.
    
    USER QUESTION: "{user_question}"
    AI ANSWER: "{ai_answer}"
    CONTEXT: {context_text}
    
    TASK:
    - The AI advised the student to look at a chart/figure/graph in the answer. Which ID is it? (e.g. "1.1", "8.3").
    - If the answer mentions "Chart 1.1", output "1.1".
    - If NO specific figure is mentioned, return "NONE".
    
    OUTPUT FORMAT: Just the ID (e.g. 8.3) or NONE. Do not add any other text.
    """
    
    try:
        res = safe_google_api_call(prompt)
        if res and res.text:
            fig_id = res.text.strip()
            match = re.search(r"(\d+\.\d+)", fig_id)
            if match:
                return match.group(1)
    except:
        pass
    return None

def fetch_image_with_retry(fig_id, subject, medium, max_retries=4, delay=5):
    if not fig_id: return None

    for attempt in range(max_retries):
        try:
            response = supabase.table("content_library") \
                .select("image_url, description, page_number") \
                .eq("subject", subject) \
                .eq("medium", medium) \
                .ilike("description", f"%Figure {fig_id}%") \
                .limit(1) \
                .execute()
            
            if response.data:
                return response.data[0] 
            break 
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                print(f"Failed to fetch image {fig_id}: {e}")
    return None

def process_user_query(user_input, subject, medium):
    prompt = f"""
    ROLE: Transliteration Engine.
    INPUT: "{user_input}"
    CONTEXT: Subject={subject}, Medium={medium}
    INSTRUCTIONS: 
    1. Transliterate Singlish to Sinhala phonetically.
    2. Identify intent.
    OUTPUT JSON ONLY: {{ "interpreted_question": "...", "search_keywords": [...] }}
    """
    try:
        res = safe_google_api_call(prompt, config={'response_mime_type': 'application/json'})
        if res and res.text:
            return json.loads(clean_json_text(res.text))
        return None
    except: return None

def search_database(keywords, filters):
    all_hits = []
    seen_content = set()
    for kw in keywords:
        query = supabase.table("documents").select("content, metadata")
        if filters.get('subject'): query = query.eq("metadata->>subject", filters['subject'])
        if filters.get('medium'): query = query.eq("metadata->>medium", filters['medium'])
        query = query.ilike("content", f"%{kw}%").limit(8)
        results = query.execute()
        for item in results.data: 
            if item['content'] not in seen_content:
                all_hits.append(item)
                seen_content.add(item['content'])
    return all_hits

def generate_final_answer(context_items, user_question, subject, medium):
    if not context_items:
        return "⚠️ මට ඒ ගැන කරුණු සොයාගැනීමට නොහැකි විය. (No notes found)"
    
    context_text = "\n---\n".join([item['content'] for item in context_items])
    
    prompt = f"""
    You are an expert Sri Lankan O/L Tutor.
    SETTINGS: Subject: {subject}, Medium: {medium}
    CONTEXT DATA: {context_text}
    USER QUESTION: {user_question}
    
    CRITICAL INSTRUCTIONS FOR FIGURE IDS:
    1. Look for Figure IDs in the context (e.g., "8.9 රූපය", "Figure 10.2").
    2. When mentioning a figure, YOU MUST USE THE EXACT ID from the context.
    3. DO NOT simplify "8.9" to "9". Write "8.9" exactly.
    4. If the context says "Figure 8.9", your answer MUST say "8.9 රූපය බලන්න".
    
    GENERAL INSTRUCTIONS:
    1. Be friendly (Address as "Puthe").
    2. Explain concepts clearly with bullet points.
    3. Answer in {medium} ONLY.
    """
    res = safe_google_api_call(prompt)
    return res.text if res else "System busy. Please try again."

# ==========================================
# 🚀 API ENDPOINTS
# ==========================================

async def verify_api_key(x_api_key: str = Header(...)):
    # 1. Key Check
    res = supabase.table("api_keys").select("*").eq("key_string", x_api_key).eq("is_active", True).execute()
    if not res.data:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    key_data = res.data[0]
    
    # 2. Expiry Check
    if key_data['expires_at'] and key_data['expires_at'] < time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()):
        raise HTTPException(status_code=403, detail="API Key Expired")

    # 3. Credit Check
    if not key_data['is_unlimited'] and key_data['credits'] <= 0:
        raise HTTPException(status_code=402, detail="Insufficient Credits")

    return key_data

@app.post("/chat")
async def chat_endpoint(request: ChatRequest, key_data: dict = Depends(verify_api_key)):
    
    # 1. Process Query
    decoded = process_user_query(request.question, request.subject, request.medium)
    
    if decoded:
        interpreted_q = decoded['interpreted_question']
        keywords = decoded['search_keywords']
        
        # 2. Search Database
        context_items = search_database(keywords, {'subject': request.subject, 'medium': request.medium})
        
        if context_items:
            # 3. Generate Answer
            answer = generate_final_answer(context_items, interpreted_q, request.subject, request.medium)
            
            # 4. Image Logic
            best_fig_id = identify_best_figure_id(context_items, interpreted_q, answer)
            image_data = None
            if best_fig_id:
                image_data = fetch_image_with_retry(best_fig_id, request.subject, request.medium)

            # 5. DEDUCT CREDIT (Backend Logic)
            if not key_data['is_unlimited']:
                supabase.table("api_keys").update({"credits": key_data['credits'] - 1}).eq("id", key_data['id']).execute()
                credits_left = key_data['credits'] - 1
            else:
                credits_left = "Unlimited"

            return {
                "question_interpreted": interpreted_q,
                "answer": answer,
                "image": image_data,
                "credits_left": credits_left
            }
        else:
            return {"answer": "සමාවෙන්න, මට ඒ ගැන කරුණු හමු නොවුණා.", "image": None}
    else:
        return {"answer": "System busy or Error.", "image": None}