import os
from dotenv import load_dotenv
load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY", "")
DB = dict(host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", 3306)),
          user=os.getenv("DB_USER", ""), password=os.getenv("DB_PASSWORD", ""),
          database=os.getenv("DB_NAME", "smart_ambulance"))
MAPS_SERVER_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
MAPS_BROWSER_KEY = os.getenv("GOOGLE_MAPS_BROWSER_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5000").split(",")
