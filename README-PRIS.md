# 📘 Projet Madachat – Backend - chatbot-service

## 🚀 Description
Backend en **FastAPI + PostgreSQL** permettant de gérer et rechercher des **articles juridiques**.  

### Fonctionnalités principales
- 📑 **Lister tous les articles** → `/articles/`  
- 🔎 **Rechercher un article par numéro** → `/articles/{numero}`  
- 🧠 **Recherche dynamique par mots-clés (full-text search PostgreSQL)** → `/articles/search/?q=mot1 mot2`  

---
### 1 Cloner le projet
git clone https://github.com/PrisquinMG/chatbot-service.git

### 2 Executer le fichier pour importer le donneee dans le postgres
python import_articles.py


# URLs de production
# VITE_TUNE_API_URL=https://madaTuneApi.onirtech.com
# VITE_CHAT_API_URL=https://madaChatApi.onirtech.com
# VITE_FRONT_URL=https://madachat.onirtech.com

# Frontend local (pointant vers ton backend local)
VITE_TUNE_API_URL=http://localhost:8000
VITE_CHAT_API_URL=http://localhost:8000
VITE_FRONT_URL=http://localhost:5173  # ou le port React de dev

# Supabase (toujours en ligne)
VITE_SUPABASE_URL=https://meqlbwxqcyeqkvaregpq.supabase.co