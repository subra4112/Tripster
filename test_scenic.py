import json
import requests

def main():
    url = "http://127.0.0.1:8000/scenic"
    payload = {
        "origin": "Phoenix, AZ",
        "destination": "Sedona, AZ",
        # Uncomment to test personalization:
        # "scenicMode": "nature",  # nature|water|desert|city|balanced
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        print("Status:", resp.status_code)
        try:
            data = resp.json()
            print(json.dumps(data, indent=2)[:4000])
        except Exception:
            print("Non-JSON response:", resp.text[:1000])
    except Exception as e:
        print("Request failed:", e)

if __name__ == "__main__":
    main()

