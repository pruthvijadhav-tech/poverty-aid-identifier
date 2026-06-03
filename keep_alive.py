import requests
import time
import threading

def keep_alive(url):
    while True:
        try:
            requests.get(url)
            print(f"Pinged {url}")
        except:
            pass
        time.sleep(840)  # ping every 14 minutes

def start(url):
    t = threading.Thread(target=keep_alive, args=(url,))
    t.daemon = True
    t.start()