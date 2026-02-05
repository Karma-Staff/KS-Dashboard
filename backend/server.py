import os
import io
# Version 3.0 - Multi-Dashboard System with SQLite
import json
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from google import genai
from typing import Dict, Any, List, Optional
import pandas as pd
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi import Depends

# Local imports
import database as db
from analyze_data import analyze_data
from quickbooks_converter import get_conversion_preview, finalize_conversion

load_dotenv()

app = FastAPI()

# Enable CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-12345") # In production, use a strong random secret
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.get_user_by_username(username)
    if user is None:
        raise credentials_exception
    return user


def get_client():
    """Get the Gemini client, ensuring the API key is read from the environment."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)

client = get_client()

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

class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    is_admin: bool = False


class QuickBooksFinalizeRequest(BaseModel):
    raw_ai_result: Dict[str, Any]
    adjustments: Dict[str, Any]


# ============= Static File Serving =============

@app.get("/")
async def root():
    """Serve the homepage."""
    return FileResponse(os.path.join(FRONTEND_DIR, "home.html"))


@app.get("/login")
async def login_page():
    """Serve the login page."""
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))


@app.get("/dashboard")
async def dashboard_page():
    """Serve the dashboard page."""
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/health")
async def health_check():
    """Health check endpoint for Render."""
    return {"status": "healthy", "database": db.DB_PATH, "version": "3.1.0"}


# Mount static files (CSS, JS, etc.)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
# Explicitly mount assets for logo and other media
app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")

# Custom exception handler to ensure JSON responses on errors
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}", "type": str(type(exc).__name__)}
    )

from fastapi.responses import JSONResponse


# ============= Auth API Endpoints =============

@app.post("/api/auth/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticate user and return JWT token."""
    user = db.get_user_by_username(form_data.username)
    if not user or not db.verify_password(form_data.password, user['password_hash']):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(data={"sub": user['username']})
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "user": {
            "username": user['username'],
            "full_name": user['full_name'],
            "is_admin": bool(user['is_admin'])
        }
    }


@app.get("/api/auth/me")
async def read_users_me(current_user: dict = Depends(get_current_user)):
    """Get current user information."""
    return {
        "username": current_user['username'],
        "full_name": current_user['full_name'],
        "is_admin": bool(current_user['is_admin'])
    }


# ============= Admin User Management Endpoints =============

@app.get("/api/admin/users")
async def list_users(current_user: dict = Depends(get_current_user)):
    """List all users (admin only)."""
    if not current_user['is_admin']:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    users = db.get_all_users()
    return {"users": users}


@app.post("/api/admin/users")
async def create_new_user(user: UserCreate, current_user: dict = Depends(get_current_user)):
    """Create a new user (admin only)."""
    if not current_user['is_admin']:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    user_id = db.create_user(
        username=user.username,
        password=user.password,
        full_name=user.full_name,
        is_admin=user.is_admin
    )
    
    if user_id == -1:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    return {"id": user_id, "message": "User created successfully"}


@app.delete("/api/admin/users/{user_id}")
async def delete_user(user_id: int, current_user: dict = Depends(get_current_user)):
    """Delete a user (admin only)."""
    if not current_user['is_admin']:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Optional: Prevent self-deletion
    if user_id == current_user['id']:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
        
    success = db.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=44, detail="User not found")
        
    return {"message": "User deleted successfully"}


# ============= Dashboard API Endpoints =============

@app.get("/api/dashboards")
async def list_dashboards(current_user: dict = Depends(get_current_user)):
    """Get all dashboards (filtered by user or all for admin)."""
    dashboards = db.get_all_dashboards(
        user_id=current_user['id'], 
        is_admin=bool(current_user['is_admin'])
    )
    return {"dashboards": dashboards}


@app.post("/api/dashboards")
async def create_dashboard(
    file: UploadFile = File(...), 
    current_user: dict = Depends(get_current_user)
):
    """Upload an Excel/CSV/PDF file and create a new dashboard."""
    
    # Validate file type
    filename = file.filename.lower()
    if not (filename.endswith('.xlsx') or filename.endswith('.xls') or filename.endswith('.csv') or filename.endswith('.pdf')):
        raise HTTPException(
            status_code=400, 
            detail="Invalid file type. Please upload .xlsx, .xls, .csv, or .pdf files."
        )
    
    try:
        # Read file content
        content = await file.read()
        
        # Check if it's potentially a QuickBooks file
        is_quickbooks = False
        if filename.endswith('.pdf'):
            is_quickbooks = True
        elif filename.endswith('.xlsx') or filename.endswith('.xls') or filename.endswith('.csv'):
            try:
                # Basic check for QB keywords in the first few rows
                if filename.endswith('.csv'):
                    check_df = pd.read_csv(io.BytesIO(content), nrows=10, header=None)
                else:
                    check_df = pd.read_excel(io.BytesIO(content), nrows=10, header=None)
                
                header_text = check_df.to_string().lower()
                if "profit & loss" in header_text or "profit and loss" in header_text or ("income" in header_text and "expenses" in header_text) or ("revenue" in header_text and "expense" in header_text):
                    is_quickbooks = True
            except:
                pass

        # Handle QuickBooks reports (PDF/Excel/CSV)
        if is_quickbooks:
            from quickbooks_converter import convert_quickbooks_file
            
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise HTTPException(status_code=500, detail="Gemini API Key (GEMINI_API_KEY) not found in environment.")
                
            # Convert QB report to flat DataFrame using AI
            df = convert_quickbooks_file(content, filename, api_key)
            
            # Save the flat data to a temporary CSV for analysis
            # Use /tmp on Linux/Render for guaranteed writability if possible
            temp_dir = "/tmp" if os.name != 'nt' and os.path.exists("/tmp") else DATA_DIR
            temp_csv_path = os.path.join(temp_dir, f"temp_qb_{os.getpid()}.csv")
            try:
                df.to_csv(temp_csv_path, index=False)
                # Process data for dashboard visualizations
                data = analyze_data(temp_csv_path)
            finally:
                if os.path.exists(temp_csv_path):
                    os.remove(temp_csv_path)
            
            # Get company name from data or default to filename
            company_name = df['Company'].iloc[0] if not df.empty else "QuickBooks Dashboard"
            name = company_name if company_name != "Unknown Company" else db.get_next_untitled_name()
            
            # Save to database
            dashboard_id = db.create_dashboard(name, data, current_user['id'])
            
            return {
                "id": dashboard_id,
                "name": name,
                "message": "QuickBooks report processed and dashboard created successfully"
            }

        # Standard dashboard creation for flat files (CSV/Excel)
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))
        
        # Save temporarily to process with existing analyze_data function
        temp_dir = "/tmp" if os.name != 'nt' and os.path.exists("/tmp") else DATA_DIR
        temp_csv_path = os.path.join(temp_dir, f"temp_{os.getpid()}.csv")
        try:
            df.to_csv(temp_csv_path, index=False)
            data = analyze_data(temp_csv_path)
        finally:
            if os.path.exists(temp_csv_path):
                os.remove(temp_csv_path)
        
        # Get next untitled name
        name = db.get_next_untitled_name()
        
        # Save to database
        dashboard_id = db.create_dashboard(name, data, current_user['id'])
        
        return {
            "id": dashboard_id,
            "name": name,
            "message": "Dashboard created successfully"
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


async def process_file_to_dataframe(file: UploadFile) -> pd.DataFrame:
    """
    Process a single uploaded file (CSV, Excel, or QuickBooks PDF) into a DataFrame.
    Returns a standardized DataFrame with columns: Company, Month, Year, Category, Account, Amount
    """
    filename = file.filename.lower()
    content = await file.read()
    
    # Check if it's a QuickBooks file
    is_quickbooks = False
    if filename.endswith('.pdf'):
        is_quickbooks = True
    elif filename.endswith('.xlsx') or filename.endswith('.xls') or filename.endswith('.csv'):
        try:
            if filename.endswith('.csv'):
                check_df = pd.read_csv(io.BytesIO(content), nrows=10, header=None)
            else:
                check_df = pd.read_excel(io.BytesIO(content), nrows=10, header=None)
            
            header_text = check_df.to_string().lower()
            if "profit & loss" in header_text or "profit and loss" in header_text or \
               ("income" in header_text and "expenses" in header_text) or \
               ("revenue" in header_text and "expense" in header_text):
                is_quickbooks = True
        except:
            pass
    
    if is_quickbooks:
        from quickbooks_converter import convert_quickbooks_file
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="Gemini API Key not found")
        df = convert_quickbooks_file(content, file.filename, api_key)
    else:
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))
    
    return df


@app.post("/api/dashboards/multi")
async def create_consolidated_dashboard(
    files: List[UploadFile] = File(...),
    name: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """Upload multiple files and merge them into a single consolidated dashboard."""
    
    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided")
    
    # Validate all file types
    for file in files:
        filename = file.filename.lower()
        if not (filename.endswith('.xlsx') or filename.endswith('.xls') or 
                filename.endswith('.csv') or filename.endswith('.pdf')):
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid file type: {file.filename}. Supported: .xlsx, .xls, .csv, .pdf"
            )
    
    try:
        all_dataframes = []
        processed_files = []
        
        for file in files:
            try:
                df = await process_file_to_dataframe(file)
                all_dataframes.append(df)
                processed_files.append(file.filename)
            except Exception as e:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Error processing {file.filename}: {str(e)}"
                )
        
        # Merge all DataFrames
        merged_df = pd.concat(all_dataframes, ignore_index=True)
        
        # Process merged data using analyze_data with DataFrame
        data = analyze_data(df=merged_df)
        
        # Generate dashboard name if not provided
        dashboard_name = name if name else f"Consolidated Dashboard ({len(files)} files)"
        
        # Save to database
        dashboard_id = db.create_dashboard(dashboard_name, data, current_user['id'])
        
        return {
            "id": dashboard_id,
            "name": dashboard_name,
            "files_merged": len(processed_files),
            "files": processed_files,
            "message": "Consolidated dashboard created successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error creating consolidated dashboard: {str(e)}")


@app.get("/api/dashboards/{dashboard_id}")
async def get_dashboard(dashboard_id: int, current_user: dict = Depends(get_current_user)):
    """Get a single dashboard with its data."""
    dashboard = db.get_dashboard(dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    
    # Check permissions
    if not current_user['is_admin'] and dashboard.get('user_id') != current_user['id']:
        raise HTTPException(status_code=403, detail="Not authorized to access this dashboard")
        
    return dashboard


@app.put("/api/dashboards/{dashboard_id}")
async def rename_dashboard(
    dashboard_id: int, 
    body: DashboardRename,
    current_user: dict = Depends(get_current_user)
):
    """Rename a dashboard."""
    # Verify ownership or admin
    dashboard = db.get_dashboard(dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
        
    if not current_user['is_admin'] and dashboard.get('user_id') != current_user['id']:
        raise HTTPException(status_code=403, detail="Not authorized to rename this dashboard")
        
    success = db.update_dashboard_name(dashboard_id, body.name)
    return {"message": "Dashboard renamed successfully"}


@app.delete("/api/dashboards/{dashboard_id}")
async def delete_dashboard(dashboard_id: int, current_user: dict = Depends(get_current_user)):
    """Delete a dashboard."""
    # Verify ownership or admin
    dashboard = db.get_dashboard(dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
        
    if not current_user['is_admin'] and dashboard.get('user_id') != current_user['id']:
        raise HTTPException(status_code=403, detail="Not authorized to delete this dashboard")
        
    success = db.delete_dashboard(dashboard_id)
    return {"message": "Dashboard deleted successfully"}


# ============= Conversation API Endpoints =============

@app.get("/api/dashboards/{dashboard_id}/conversations")
async def get_conversations(dashboard_id: int, current_user: dict = Depends(get_current_user)):
    """Get all conversations for a dashboard."""
    # Verify access
    dashboard = db.get_dashboard(dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    
    if not current_user['is_admin'] and dashboard.get('user_id') != current_user['id']:
        raise HTTPException(status_code=403, detail="Not authorized to access these conversations")
    
    conversations = db.get_conversations(dashboard_id)
    return {"conversations": conversations}


@app.delete("/api/dashboards/{dashboard_id}/conversations")
async def clear_conversations(dashboard_id: int, current_user: dict = Depends(get_current_user)):
    """Clear all conversations for a dashboard."""
    # Verify access
    dashboard = db.get_dashboard(dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    
    if not current_user['is_admin'] and dashboard.get('user_id') != current_user['id']:
        raise HTTPException(status_code=403, detail="Not authorized to clear these conversations")
    
    db.clear_conversations(dashboard_id)
    return {"message": "Conversations cleared"}


# ============= Chat Endpoint =============

@app.post("/chat")
async def chat(request: ChatRequest, current_user: dict = Depends(get_current_user)):
    """Handle chat messages and save to database."""
    global client
    if not client:
        client = get_client()
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


class AnalyzeRequest(BaseModel):
    dashboard_id: int
    context: dict


@app.post("/analyze")
async def analyze(request: AnalyzeRequest, current_user: dict = Depends(get_current_user)):
    """Generate AI analysis and recommendations for the dashboard data."""
    global client
    if not client:
        client = get_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini API Key not configured in .env")

    # Verify dashboard exists
    dashboard = db.get_dashboard(request.dashboard_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    try:
        # Pre-defined analysis prompt
        analysis_prompt = """
        Role: You are Restor AI, an Expert Financial Analyst specializing in restoration businesses.
        
        Task: Analyze the provided financial dashboard data and provide a comprehensive analysis with actionable recommendations.
        
        Your analysis should include:
        1. **Financial Health Overview**: A brief assessment of the overall financial health based on the data.
        2. **Key Observations**: 2-3 important findings from the data (trends, anomalies, opportunities).
        3. **Actionable Recommendations**: 2-3 specific, actionable steps the business owner can take to improve performance.
        
        CRITICAL FORMATTING RULES:
        - ALWAYS express costs/expenses as BOTH dollar amounts AND percentage of revenue.
        - ALWAYS compare each metric against industry standards.
        - Example format: "Trash expense is $200,000 (10% of revenue), which is above the industry standard of 8%."
        
        INDUSTRY BENCHMARKS FOR RESTORATION BUSINESSES:
        - Net Profit Margin: 15-25% (healthy), <15% (needs improvement), >25% (excellent)
        - COGS (Cost of Goods Sold): typically 30-40% of revenue
        - Labor/Payroll: typically 20-30% of revenue
        - Marketing/Advertising: typically 3-5% of revenue
        - Administrative/Overhead: typically 8-12% of revenue
        - Equipment/Supplies: typically 5-10% of revenue
        - Insurance: typically 2-4% of revenue
        - Rent/Utilities: typically 3-6% of revenue
        
        Additional Rules:
        - Be direct and specific. Reference actual numbers from the data.
        - For every expense category, state: amount, percentage of revenue, and how it compares to industry standard.
        - Format dollar amounts as currency (e.g., $1,200.00).
        - Keep the response concise but insightful - no more than 350 words.
        - Do not use markdown formatting like ** or headers. Use plain text with line breaks.
        - Separate sections with a blank line for readability.
        """

        prompt = f"""
        {analysis_prompt}

        Dashboard Data for Analysis:
        {json.dumps(request.context, indent=2)}
        """

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )

        return {"analysis": response.text}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
