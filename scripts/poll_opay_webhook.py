"""
Poll Nomba's event-logs (sub-account + parent) for the OPay NGN 100
to VA 3783622764 to arrive.

Runs for up to 5 minutes, checking every 20 seconds.
"""
import asyncio
import os
import sys
import json
import time
import requests as http_requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from app.services.nomba_client import nomba_client


async def main():
    await nomba_client._issue_token()
    headers = await nomba_client._headers()

    sub_id = os.environ.get("NOMBA_SUB_ACCOUNT_ID", "282e5b9b-d14f-4e43-840d-43ddfd90a071")
    parent_id = os.environ.get("NOMBA_PARENT_ACCOUNT_ID", "f666ef9b-888e-4799-85ce-acb505b28023")

    seen = set()
    print("=" * 70)
    print(f"Polling for OPay GHS 100 to VA 3783622764 (sub-account)")
    print(f"  Sub-account:   {sub_id}")
    print(f"  Parent:        {parent_id}")
    print("=" * 70)

    end = time.strftime("%Y-%m-%d")
    start = "2026-07-02"

    for attempt in range(15):  # 15 * 20s = 5 minutes
        for label, uid in [("SUB", sub_id), ("PARENT", parent_id)]:
            payload = {
                "coreUserId": uid,
                "limit": 20,
                "eventType": "payment_success",
                "startDateTime": start,
                "endDateTime": end,
            }
            try:
                resp = http_requests.post(
                    f"{nomba_client.base_url}/webhooks/event-logs",
                    headers=headers,
                    json=payload,
                    timeout=15,
                )
                body = resp.json()
                events = body.get("data", {}).get("list", [])
                for e in events:
                    key = (label, e.get("hookRequestId"))
                    if key not in seen:
                        seen.add(key)
                        rp = e.get("responsePayload", "")
                        try:
                            inner = json.loads(rp)
                            data_field = inner.get("data", "")
                            if isinstance(data_field, str):
                                try:
                                    data_field = json.loads(data_field)
                                except Exception:
                                    pass
                            amt = data_field.get("amount") if isinstance(data_field, dict) else "?"
                            txn = data_field.get("transaction_id") if isinstance(data_field, dict) else "?"
                            desc = inner.get("description", "?")
                        except Exception:
                            amt, txn, desc = "?", "?", "?"
                        print(f"\n[{label}] NEW EVENT:")
                        print(f"  hookRequestId: {e.get('hookRequestId')}")
                        print(f"  desc:          {desc}")
                        print(f"  amount:        {amt}")
                        print(f"  txn:           {txn}")
                        if "100" in str(amt) or "VACT_TRA-56742" in str(txn):
                            print("\n  >>> POSSIBLE OPAY PAYMENT DETECTED <<<")
            except Exception as exc:
                print(f"  [{label}] error: {exc}")

        elapsed = (attempt + 1) * 20
        print(f"[{elapsed:3d}s] total events seen: {len(seen)} (sub={sum(1 for k in seen if k[0]=='SUB')}, parent={sum(1 for k in seen if k[0]=='PARENT')})", end="\r")
        await asyncio.sleep(20)

    print()
    print()
    print("=" * 70)
    print(f"Done. Total events found across 5 minutes: {len(seen)}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
