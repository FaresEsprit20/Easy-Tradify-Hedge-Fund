# test.py
import requests
import json
from datetime import datetime

# Updated to port 5000
url = "http://192.168.100.3:5001/webhook/trade"

test_data = {
    "event": "CLOSE",
    "close_reason": "MANUAL",
    "symbol": "EURGBP",
    "ticket": 1807556246,
    "volume": 0.2,
    "price_open": 1.33800,
    "price_close": 1.33900,
    "profit": 20.00,
    "sl": 1.33700,
    "tp": 1.34000,
    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
}

print("=" * 50)
print("TESTING WEBHOOK ON PORT 5001")
print("=" * 50)
print(f"URL: {url}")
print(f"Data: {json.dumps(test_data, indent=2)}")
print("=" * 50)

try:
    response = requests.post(url, json=test_data, timeout=5)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
    
    if response.status_code == 200:
        print("✅ Webhook test SUCCESSFUL!")
    else:
        print(f"❌ Webhook test FAILED with status {response.status_code}")
        
except requests.exceptions.ConnectionError:
    print("❌ Connection Error: Make sure Flask server is running on port 5001")
    print("   Check: python api/hybrid_monitor.py")
except requests.exceptions.Timeout:
    print("❌ Timeout: Server took too long to respond")
except Exception as e:
    print(f"❌ Error: {e}")