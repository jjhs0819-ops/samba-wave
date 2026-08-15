import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kream_ebay_sync as k

orders = k.fetch_kream_orders()
today_delivered = [(no, info) for no, info in orders.items()
                    if info["status"] == "배송완료" and info["date"].startswith("26/08/15")]

with open("C:/tmp/today_delivered.txt", "w", encoding="utf-8") as f:
    for no, info in sorted(today_delivered, key=lambda x: x[1]["date"]):
        f.write(f"{no}\t{info['date']}\t{info['status']}\n")
print("count", len(today_delivered))
