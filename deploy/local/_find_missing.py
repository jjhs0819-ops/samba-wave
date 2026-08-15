import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kream_ebay_sync as k
import gspread

orders = k.fetch_kream_orders()
delivered = {no: info for no, info in orders.items()
             if info["status"] == "배송완료" and info["date"] >= k.AUTO_MATCH_MIN_DATE}

gc = gspread.service_account(filename=k.CREDS_PATH)
sh = gc.open_by_key(k.SHEET_ID)
ws = sh.worksheet(k.TAB_NAME)

d_col = {v for v in ws.col_values(4) if v.strip()}  # D열 크림주문번호

missing = [(no, info) for no, info in delivered.items() if no not in d_col]

with open("C:/tmp/missing_delivered.txt", "w", encoding="utf-8") as f:
    f.write(f"8/1이후 배송완료 총 {len(delivered)}건, D열 미기록 {len(missing)}건\n\n")
    for no, info in sorted(missing, key=lambda x: x[1]["date"]):
        f.write(f"{no}\t{info['date']}\t{info['status']}\n")
print(f"delivered={len(delivered)} missing={len(missing)}")
