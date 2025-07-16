from fastapi import FastAPI, Request, HTTPException, Header, Depends
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from slowapi import Limiter
from slowapi.util import get_remote_address
import logging

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv
import os

load_dotenv()

# ----------- Logging Setup -----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------- FastAPI + Rate Limiter -----------
limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter

# ----------- CORS (optional) -----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ----------- Request/Response Models -----------
class ScrapeRequest(BaseModel):
    url: str

class ScrapeResult(BaseModel):
    videos: list[str]
    images: list[str]

API_KEY = os.getenv("API_KEY")

def verify_api_key(x_api_key: str = Header(...)):
    
    logger.info(f"Received API Key: {x_api_key}")
    logger.info(f"System api key: {API_KEY}")
    if x_api_key != API_KEY:
        logger.warning("Unauthorized access attempt with key: %s", x_api_key)
        raise HTTPException(status_code=401, detail="Invalid or missing API Key")


# ----------- Core Scraper Function -----------
def scrape_media(url: str) -> dict:
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(20)

    media_urls = {"videos": [], "images": []}

    try:
        logger.info(f"Opening URL: {url}")
        driver.get(url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "x1xmf6yo"))
        )

        divs = driver.find_elements(By.CSS_SELECTOR, "div.x1xmf6yo")

        for div in divs:
            videos = div.find_elements(By.TAG_NAME, "video")
            imgs = div.find_elements(By.TAG_NAME, "img")

            if videos or imgs:
                for video in videos:
                    src = video.get_attribute("src")
                    if src:
                        media_urls["videos"].append(src)
                    else:
                        for source in video.find_elements(By.TAG_NAME, "source"):
                            src = source.get_attribute("src")
                            if src:
                                media_urls["videos"].append(src)

                for img in imgs:
                    src = img.get_attribute("src")
                    if src:
                        media_urls["images"].append(src)

                break  # Stop after first valid div

    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        driver.quit()

    return media_urls

# ----------- API Endpoint -----------
@app.post("/scrape", response_model=ScrapeResult)
@limiter.limit("5/minute")  # Limit requests per IP
async def scrape(request: Request, body: ScrapeRequest, _: str = Depends(verify_api_key)):
    logger.info(f"Received request to scrape: {body.url}")
    result = await run_in_threadpool(scrape_media, body.url)
    return JSONResponse(content=result)
