import os
# Version 2.0 - With Gemini 2.0 Flash and Rules
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from google import genai

load_dotenv()

app = FastAPI()

# Enable CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

api_key = os.getenv("GEMINI_API_KEY")
client = None
if api_key:
    client = genai.Client(api_key=api_key)

@app.get("/")
async def root():
    return {"message": "Financial Data AI Server is running!"}

class ChatRequest(BaseModel):
    message: str
    context: dict

@app.post("/chat")
async def chat(request: ChatRequest):
    if not client:
        raise HTTPException(status_code=500, detail="Gemini API Key not configured in .env")

    try:
        # Prepare the system context with the user's rules
        system_rules = """
        Role: You are an Expert Financial Advisor for a restoration business.
        
        Rules for your response:
        1. Financial Advice: Your primary goal is to provide actionable financial advice, cost-cutting recommendations, and growth strategies based on the provided data.
        2. Direct & Actionable: Give clear, direct advice. If you see a problem (like high expenses in a specific area), point it out and suggest a solution.
        3. No Markdown Bolding: Do not use bold text (**) in your responses.
        4. Simple Language: Use plain English that is easy for anyone to understand.
        5. Data Accuracy: Analyze the numbers accurately. Format all dollar amounts as currency (e.g., $1,200.00).
        6. Summarization: When asked for a summary, conclude with one "Top Financial Tip" for the business owner.
        """

        prompt = f"""
        {system_rules}

        Dashboard Data for Analysis:
        {json.dumps(request.context, indent=2)}
        
        User Question/Request: {request.message}
        """

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )

        return {"reply": response.text}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
