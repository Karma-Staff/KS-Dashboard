# Restor Dashboard - Deployment Guide

## Quick Deploy to Render.com (Recommended for <10 users)

### Step 1: Create Accounts

1. **GitHub Account** (if you don't have one)
   - Go to https://github.com and sign up
   
2. **Render Account**
   - Go to https://render.com
   - Sign up with your GitHub account (easiest)

---

### Step 2: Push Code to GitHub

1. Create a new repository on GitHub:
   - Go to https://github.com/new
   - Name it `restor-dashboard`
   - Keep it **Private**
   - Click "Create repository"

2. In your terminal, run these commands:
   ```bash
   cd "/Users/tenzinpaljor/Desktop/Personal /Data Analyse with Yang"
   
   # Initialize git
   git init
   
   # Add all files
   git add .
   
   # Commit
   git commit -m "Initial commit - Restor Dashboard"
   
   # Add your GitHub repo (replace YOUR_USERNAME)
   git remote add origin https://github.com/YOUR_USERNAME/restor-dashboard.git
   
   # Push to GitHub
   git branch -M main
   git push -u origin main
   ```

---

### Step 3: Deploy on Render

1. Go to https://dashboard.render.com
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repository
4. Configure:
   - **Name**: `restor-dashboard`
   - **Region**: Oregon (or closest to you)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `cd backend && gunicorn server:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT`

5. Add Environment Variable:
   - Click **"Advanced"** → **"Add Environment Variable"**
   - Key: `GEMINI_API_KEY`
   - Value: (your Gemini API key)

6. Click **"Create Web Service"**

---

### Step 4: Wait for Deployment

- Render will build and deploy your app (2-5 minutes)
- Once done, you'll get a URL like: `https://restor-dashboard.onrender.com`

---

## Your App is Now Live! 🎉

Share the URL with your team. The app includes:
- ✅ HTTPS (secure connection)
- ✅ Auto-restarts if it crashes
- ✅ Logs and monitoring

---

## Cost Breakdown

| Service | Monthly Cost |
|---------|--------------|
| Render Web Service (Starter) | $7/month |
| **Total** | **$7/month** |

*Free tier available but sleeps after 15 min of inactivity*

---

## Upgrading Later

When you grow beyond 10 users:
1. Upgrade Render plan to $25/month (more resources)
2. Or migrate to AWS (I can help with that when ready)

---

## Troubleshooting

**App not starting?**
- Check Render logs in the dashboard
- Verify GEMINI_API_KEY is set correctly

**Database issues?**
- SQLite works fine for <10 users
- For more users, add Render PostgreSQL ($7/month)
