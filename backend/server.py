import os
import io
# Version 3.0 - Multi-Dashboard System with SQLite
import json
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from google import genai
import pandas as pd

# Local imports
import database as db
from analyze_data import analyze_data

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

# Get paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
DATA_DIR = os.path.join(FRONTEND_DIR, "data")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)


# ============= Pydantic Models =============

class ChatRequest(BaseModel):
    message: str
    dashboard_id: int
    context: dict


class DashboardRename(BaseModel):
    name: str


# ============= Static File Serving =============

@app.get("/")
async def root():
    """Serve the homepage."""
    return FileResponse(os.path.join(FRONTEND_DIR, "home.html"))


@app.get("/dashboard")
async def dashboard_page():
    """Serve the dashboard page."""
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# Mount static files (CSS, JS, etc.)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ============= Dashboard API Endpoints =============

@app.get("/api/dashboards")
async def list_dashboards():
    """Get all dashboards."""
    dashboards = db.get_all_dashboards()
    return {"dashboards": dashboards}


@app.post("/api/dashboards")
async def create_dashboard(file: UploadFile = File(...)):
    """Upload an Excel/CSV file and create a new dashboard."""
    
    # Validate file type
    filename = file.filename.lower()
    if not (filename.endswith('.xlsx') or filename.endswith('.xls') or filename.endswith('.csv')):
        raise HTTPException(
            status_code=400, 
            detail="Invalid file type. Please upload .xlsx, .xls, or .csv files."
        )
    
    try:
        # Read file content
        content = await file.read()
        
        # Parse based on file type
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))
        
        # Save temporarily to process with existing analyze_data function
        temp_csv_path = os.path.join(DATA_DIR, "temp_upload.csv")
        df.to_csv(temp_csv_path, index=False)
        
        # Process data using existing analyze_data function
        data = analyze_data(temp_csv_path)
        
        # Clean up temp file
        os.remove(temp_csv_path)
        
        # Get next untitled name
        name = db.get_next_untitled_name()
        
        # Save to database
        dashboard_id = db.create_dashboard(name, data)
        
        return {
            "id": dashboard_id,
            "name": name,
            "message": "Dashboard created successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@app.get("/api/dashboards/{dashboard_id}")
async def get_dashboard(dashboard_id: int):
    """Get a single dashboard with its data."""
    dashboard = db.get_dashboard(dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return dashboard


@app.put("/api/dashboards/{dashboard_id}")
async def rename_dashboard(dashboard_id: int, body: DashboardRename):
    """Rename a dashboard."""
    success = db.update_dashboard_name(dashboard_id, body.name)
    if not success:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return {"message": "Dashboard renamed successfully"}


@app.delete("/api/dashboards/{dashboard_id}")
async def delete_dashboard(dashboard_id: int):
    """Delete a dashboard."""
    success = db.delete_dashboard(dashboard_id)
    if not success:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return {"message": "Dashboard deleted successfully"}


# ============= Conversation API Endpoints =============

@app.get("/api/dashboards/{dashboard_id}/conversations")
async def get_conversations(dashboard_id: int):
    """Get all conversations for a dashboard."""
    # Verify dashboard exists
    dashboard = db.get_dashboard(dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    
    conversations = db.get_conversations(dashboard_id)
    return {"conversations": conversations}


@app.delete("/api/dashboards/{dashboard_id}/conversations")
async def clear_conversations(dashboard_id: int):
    """Clear all conversations for a dashboard."""
    # Verify dashboard exists
    dashboard = db.get_dashboard(dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    
    db.clear_conversations(dashboard_id)
    return {"message": "Conversations cleared"}


# ============= Chat Endpoint =============

@app.post("/chat")
async def chat(request: ChatRequest):
    """Handle chat messages and save to database."""
    if not client:
        raise HTTPException(status_code=500, detail="Gemini API Key not configured in .env")

    # Verify dashboard exists
    dashboard = db.get_dashboard(request.dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    try:
        # Fetch conversation history for context
        conversation_history = db.get_conversations(request.dashboard_id)
        
        # Build conversation history string (limit to last 10 exchanges to avoid token limits)
        history_text = ""
        recent_conversations = conversation_history[-10:] if len(conversation_history) > 10 else conversation_history
        
        if recent_conversations:
            history_text = "\n\nPrevious Conversation History (for context):\n"
            for conv in recent_conversations:
                history_text += f"User: {conv['user_message']}\n"
                history_text += f"Assistant: {conv['ai_response']}\n\n"
        
        # Prepare the system context with the user's rules
        system_rules = """
        Role: You are Restor AI, an Expert Financial Analyst specializing in restoration businesses.
        
        About You: You are a sophisticated AI assistant created by Karma Staff, designed specifically to help restoration business owners understand their financial data and make better decisions.
        
        Rules for your response:
        1. Financial Expertise: Provide actionable financial advice, cost-cutting recommendations, and growth strategies based on the restoration industry.
        2. Direct & Actionable: Give clear, direct advice. If you see a problem (like high expenses), point it out and suggest a solution.
        3. Clean Formatting: Do not use bold text (**) or markdown formatting in your responses.
        4. Simple Language: Use plain English that is easy for anyone to understand.
        5. Data Accuracy: Analyze the numbers accurately. Format all dollar amounts as currency (e.g., $1,200.00).
        6. Summarization: When asked for a summary, conclude with one "Top Financial Tip" for the business owner.
        7. Conversation Memory: Use the conversation history to understand the user's patterns and provide more relevant, contextual answers.
        8. Industry Context: Apply restoration industry benchmarks (15-25% net margin for healthy businesses, 40%+ for mitigation, 10-15% for reconstruction).
        """

        prompt = f"""
        {system_rules}

        Dashboard Data for Analysis:
        {json.dumps(request.context, indent=2)}
        {history_text}
        Current User Question/Request: {request.message}
        """

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )

        ai_reply = response.text
        
        # Save conversation to database
        db.save_conversation(request.dashboard_id, request.message, ai_reply)

        return {"reply": ai_reply}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
