"""
Iota Protection Alert System
- Sends DM alerts when protection is about to expire (2h, 30min)
- Sends DM alerts when dead status is about to expire
- Background job running continuously
"""
import asyncio
import time
from utils.mongo_db import get_db
from utils.fonts import sc, ALERT

_alerted: dict = {}   # user_id -> {type: last_alert_ts}


async def protection_alert_job(bot):
    """Run continuously, check users' protection status and send alerts."""
    while True:
        try:
            now = int(time.time())
            db = get_db()
            # Find users whose protection expires in next 2h or 30min
            users = await db.users.find(
                {"protected_until": {"$gt": now}},
                {"_id": 1, "protected_until": 1}
            ).to_list(10000)

            for u in users:
                uid   = u["_id"]
                until = u["protected_until"]
                rem   = until - now

                user_alerts = _alerted.setdefault(uid, {})

                # 2 hour alert
                if 7100 <= rem <= 7200 and "2h" not in user_alerts:
                    user_alerts["2h"] = now
                    try:
                        await bot.send_message(
                            uid,
                            f"{ALERT}\n\n"
                            f"{sc('Your Protection Will End In Exactly 2 Hours.')}\n"
                            f"👉 {sc('Use')} /protect {sc('To Stay Safe.')}",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

                # 30 minute alert
                elif 1750 <= rem <= 1850 and "30m" not in user_alerts:
                    user_alerts["30m"] = now
                    try:
                        await bot.send_message(
                            uid,
                            f"{ALERT}\n\n"
                            f"{sc('Your Protection Will End In Exactly 30 Minutes.')}\n"
                            f"👉 {sc('Use')} /protect {sc('To Stay Safe.')}",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

                # 6 hour alert  
                elif 21500 <= rem <= 21700 and "6h" not in user_alerts:
                    user_alerts["6h"] = now
                    try:
                        await bot.send_message(
                            uid,
                            f"{ALERT}\n\n"
                            f"{sc('Your Protection Will End In Exactly 6 Hours.')}\n"
                            f"👉 {sc('Use')} /protect {sc('To Stay Safe.')}",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

                # Clean old alerts
                if rem <= 0:
                    _alerted.pop(uid, None)

        except Exception:
            pass

        await asyncio.sleep(60)   # check every minute
