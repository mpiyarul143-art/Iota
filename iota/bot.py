"""
╔══════════════════════════════════════════╗
║     IOTA BOT  —  @Boobies_00            ║
║  MongoDB + Dual AI + Full Features      ║
╚══════════════════════════════════════════╝
"""
import logging, asyncio
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, CallbackQueryHandler, PreCheckoutQueryHandler
)
from config import BOT_TOKEN
from utils.mongo_db import create_indexes
from utils.ai_provider import load_model_config_db

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # ── Imports ───────────────────────────────────────────────────────
    from handlers.start        import start_cmd, help_cmd, menu_callback
    from handlers.economy      import (
        daily_cmd, bal_cmd, rob_cmd, kill_cmd, revive_cmd, protect_cmd,
        give_cmd, toprich_cmd, topkill_cmd, wallet_cmd, rank_cmd, pfp_cmd,
        gems_cmd, claim_cmd, coupons_cmd, create_coupon_cmd, coupon_cmd,
        del_coupon_cmd, coupon_status_cmd, economy_cmd, eco_callback,
        gbal_cmd, gkill_cmd, grob_cmd, grevive_cmd, gprotect_cmd,
        gcheck_cmd, granks_cmd, auto_delete_handler, daily_remind_callback,
        auto_daily_job
    )
    from handlers.premium      import (
        pay_cmd, fpay_cmd, fgems_cmd, setemoji_cmd, check_cmd,
        pay_callback, precheckout_callback, successful_payment_handler
    )
    from handlers.games        import (
        game_menu_cmd, open_cmd, close_cmd, leaders_cmd,
        card_cmd, bet_cmd, flip_cmd, card_callback,
        bomb_cmd, bomb_callback, bluff_cmd, bluff_callback,
        hack_cmd, hack_callback, ludo_cmd, wordgame_cmd,
        wordgame_letter_handler, game_list_callback
    )
    from handlers.extra_games  import (
        tictactoe_cmd, ttt_callback, rps_cmd, rps_callback,
        hangman_cmd, hangman_handler, quiz_cmd, quiz_callback,
        ship_cmd, compliment_cmd, roast_cmd, horoscope_cmd,
        shayari_cmd, meme_cmd, work_cmd, profile_cmd, shop_cmd,
        story_cmd, whatif_cmd, settitle_cmd, top_cmd, ocr_cmd,
        remindme_cmd, stash_cmd, mystash_cmd
    )
    from handlers.fun          import (
        couples_cmd, crush_cmd, love_cmd, look_cmd, brain_cmd,
        stupid_meter_cmd, murder_cmd, slap_cmd, punch_cmd, bite_cmd,
        kiss_cmd, hug_cmd, truth_cmd, dare_cmd, puzzle_cmd,
        valentine_cmd, valentine_cancel_cmd, valentine_stats_cmd,
        valentine_delete_cmd, valentine_message_handler
    )
    from handlers.items        import items_cmd, item_cmd, gift_cmd
    from handlers.village_war  import (
        collect_cmd, storage_cmd, vault_cmd, mines_cmd,
        build_cmd, build_callback, walls_cmd, defense_cmd,
        train_cmd, troops_cmd, kingdom_cmd, spy_cmd,
        attack_cmd, emperors_cmd, settle_cmd, convert_cmd, guide_cmd
    )
    from handlers.utility      import (
        translate_cmd, voice_cmd, id_cmd, detail_cmd, owner_cmd,
        admins_cmd, own_cmd, setgroup_cmd, topgroups_cmd,
        last_seen_cmd, promoter_cmd, ref_stats_cmd
    )
    from handlers.intro        import (
        set_intro_cmd, intro_cmd, del_intro_cmd
    )
    from handlers.group_tools  import (
        settag_cmd, deltag_cmd, mytag_cmd, tag_cmd,
        link_cmd, del_link_cmd, chathistory_cmd,
        welcome_back_handler
    )
    from handlers.admin        import dot_admin_handler
    from handlers.welcome      import (
        new_member_handler, left_member_handler, setwelcome_cmd
    )
    from handlers.protection   import (
        protection_handler, anti_raid_handler, anti_bot_handler,
        report_cmd, reports_cmd, prot_cmd, report_callback,
        addword_cmd, removeword_cmd, badwords_cmd
    )
    from handlers.advanced_admin import (
        lock_cmd, unlock_cmd, locks_cmd, lock_enforcement_handler,
        setflood_cmd, floodmode_cmd, flood_check_handler,
        rules_cmd, setrules_cmd, clearrules_cmd,
        setwarnlimit_cmd, setwarnmode_cmd, warnlimit_cmd,
        resetallwarns_cmd, warnings_cmd,
        save_cmd, get_note_handler, notes_cmd, clear_note_cmd,
        setlogchannel_cmd, nolog_cmd,
        cleanservice_cmd, clean_service_handler,
        antichannelpin_cmd, channel_pin_handler,
        disable_cmd, enable_cmd, disabled_cmd,
        silentactions_cmd, admincache_cmd,
        setgoodbye_cmd, captcha_cmd,
        captcha_new_member_handler, captcha_callback,
        announce_cmd, setlang_cmd,
        approve_cmd, unapprove_cmd, approved_cmd
    )
    from handlers.ai_chat      import (
        ai_cmd, dm_message_handler, group_mention_handler,
        clear_my_memory_cmd
    )
    from handlers.owner_panel  import (
        owner_panel_cmd, addcoins_cmd, removecoins_cmd, addgems_cmd,
        addpremium_cmd, removepremium_cmd, broadcast_cmd,
        addcoupon_cmd, ban_user_cmd, unban_user_cmd_owner, stats_cmd,
        stars_stats_cmd, setmodel_cmd, listmodels_cmd,
        scan_cmd, resetuser_cmd, giveall_cmd, maintenance_cmd,
        announce_cmd as owner_announce_cmd
    )
    from handlers.alerts       import protection_alert_job

    # ── /start /help ──────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",  start_cmd))
    app.add_handler(CommandHandler("help",   help_cmd))

    # ── Economy ───────────────────────────────────────────────────────
    for c, f in [
        ("daily",daily_cmd),("bal",bal_cmd),("rob",rob_cmd),
        ("kill",kill_cmd),("revive",revive_cmd),("protect",protect_cmd),
        ("give",give_cmd),("toprich",toprich_cmd),("topkill",topkill_cmd),
        ("wallet",wallet_cmd),("rank",rank_cmd),("pfp",pfp_cmd),
        ("gems",gems_cmd),("claim",claim_cmd),("coupons",coupons_cmd),
        ("coupon",coupon_cmd),("create_coupon",create_coupon_cmd),
        ("del_coupon",del_coupon_cmd),("status",coupon_status_cmd),
        ("economy",economy_cmd),
        ("gbal",gbal_cmd),("gkill",gkill_cmd),("grob",grob_cmd),
        ("grevive",grevive_cmd),("gprotect",gprotect_cmd),
        ("gcheck",gcheck_cmd),("granks",granks_cmd),
    ]:
        app.add_handler(CommandHandler(c, f))

    # ── Premium ───────────────────────────────────────────────────────
    for c, f in [
        ("pay",pay_cmd),("fpay",fpay_cmd),("fgems",fgems_cmd),
        ("setemoji",setemoji_cmd),("check",check_cmd),
    ]:
        app.add_handler(CommandHandler(c, f))

    # ── Games ─────────────────────────────────────────────────────────
    for c, f in [
        ("game",game_menu_cmd),("open",open_cmd),("close",close_cmd),
        ("card",card_cmd),("bet",bet_cmd),("flip",flip_cmd),
        ("bomb",bomb_cmd),("bluff",bluff_cmd),("hack",hack_cmd),
        ("ludo",ludo_cmd),("wordgame",wordgame_cmd),("leaders",leaders_cmd),
        ("tictactoe",tictactoe_cmd),("rps",rps_cmd),
        ("hangman",hangman_cmd),("quiz",quiz_cmd),
    ]:
        app.add_handler(CommandHandler(c, f))

    # ── Fun / Social ──────────────────────────────────────────────────
    for c, f in [
        ("ship",ship_cmd),("compliment",compliment_cmd),("roast",roast_cmd),
        ("horoscope",horoscope_cmd),("shayari",shayari_cmd),("meme",meme_cmd),
        ("work",work_cmd),("profile",profile_cmd),("shop",shop_cmd),
        ("story",story_cmd),("whatif",whatif_cmd),("settitle",settitle_cmd),
        ("top",top_cmd),("ocr",ocr_cmd),("remindme",remindme_cmd),
        ("stash",stash_cmd),("mystash",mystash_cmd),
        ("couples",couples_cmd),("crush",crush_cmd),("love",love_cmd),
        ("look",look_cmd),("brain",brain_cmd),("stupid_meter",stupid_meter_cmd),
        ("murder",murder_cmd),("slap",slap_cmd),("punch",punch_cmd),
        ("bite",bite_cmd),("kiss",kiss_cmd),("hug",hug_cmd),
        ("truth",truth_cmd),("dare",dare_cmd),("puzzle",puzzle_cmd),
        ("valentine",valentine_cmd),("valentine_cancel",valentine_cancel_cmd),
        ("valentine_stats",valentine_stats_cmd),
        ("valentine_delete",valentine_delete_cmd),
    ]:
        app.add_handler(CommandHandler(c, f))

    # ── Items ─────────────────────────────────────────────────────────
    for c, f in [("items",items_cmd),("item",item_cmd),("gift",gift_cmd)]:
        app.add_handler(CommandHandler(c, f))

    # ── Village / War ─────────────────────────────────────────────────
    for c, f in [
        ("collect",collect_cmd),("storage",storage_cmd),("vault",vault_cmd),
        ("mines",mines_cmd),("build",build_cmd),("walls",walls_cmd),
        ("defense",defense_cmd),("train",train_cmd),("troops",troops_cmd),
        ("kingdom",kingdom_cmd),("spy",spy_cmd),("attack",attack_cmd),
        ("emperors",emperors_cmd),("settle",settle_cmd),
        ("convert",convert_cmd),("guide",guide_cmd),
    ]:
        app.add_handler(CommandHandler(c, f))

    # ── Utility ───────────────────────────────────────────────────────
    for c, f in [
        ("tr",translate_cmd),("voice",voice_cmd),("id",id_cmd),
        ("detail",detail_cmd),("owner",owner_cmd),("admins",admins_cmd),
        ("own",own_cmd),("setgroup",setgroup_cmd),("topgroups",topgroups_cmd),
        ("last_seen",last_seen_cmd),("promoter",promoter_cmd),
        ("ref_stats",ref_stats_cmd),
        ("ai",ai_cmd),("ask",ai_cmd),("clearmemory",clear_my_memory_cmd),
    ]:
        app.add_handler(CommandHandler(c, f))

    # ── Intro ─────────────────────────────────────────────────────────
    for c, f in [
        ("set_intro",set_intro_cmd),("intro",intro_cmd),
        ("del_intro",del_intro_cmd),
    ]:
        app.add_handler(CommandHandler(c, f))

    # ── Group Tools ───────────────────────────────────────────────────
    for c, f in [
        ("settag",settag_cmd),("deltag",deltag_cmd),
        ("mytag",mytag_cmd),("tag",tag_cmd),
        ("link",link_cmd),("del_link",del_link_cmd),
        ("chathistory",chathistory_cmd),
    ]:
        app.add_handler(CommandHandler(c, f))

    # ── Welcome & Protection ──────────────────────────────────────────
    for c, f in [
        ("setwelcome",setwelcome_cmd),("prot",prot_cmd),
        ("report",report_cmd),("reports",reports_cmd),
        ("addword",addword_cmd),("removeword",removeword_cmd),
        ("badwords",badwords_cmd),
    ]:
        app.add_handler(CommandHandler(c, f))

    # ── Advanced Admin ────────────────────────────────────────────────
    for c, f in [
        ("lock",lock_cmd),("unlock",unlock_cmd),("locks",locks_cmd),
        ("setflood",setflood_cmd),("floodmode",floodmode_cmd),
        ("rules",rules_cmd),("setrules",setrules_cmd),
        ("clearrules",clearrules_cmd),
        ("setwarnlimit",setwarnlimit_cmd),("setwarnmode",setwarnmode_cmd),
        ("warnlimit",warnlimit_cmd),("resetallwarns",resetallwarns_cmd),
        ("warnings",warnings_cmd),
        ("save",save_cmd),("notes",notes_cmd),("clear",clear_note_cmd),
        ("logchannel",setlogchannel_cmd),("nolog",nolog_cmd),
        ("cleanservice",cleanservice_cmd),
        ("antichannelpin",antichannelpin_cmd),
        ("disable",disable_cmd),("enable",enable_cmd),
        ("disabled",disabled_cmd),("silentactions",silentactions_cmd),
        ("admincache",admincache_cmd),("setgoodbye",setgoodbye_cmd),
        ("captcha",captcha_cmd),("setlang",setlang_cmd),
        ("approve",approve_cmd),("unapprove",unapprove_cmd),
        ("approved",approved_cmd),
        ("announce",owner_announce_cmd),
    ]:
        app.add_handler(CommandHandler(c, f))

    # ── Owner Panel ───────────────────────────────────────────────────
    for c, f in [
        ("panel",owner_panel_cmd),("addcoins",addcoins_cmd),
        ("removecoins",removecoins_cmd),("addgems",addgems_cmd),
        ("addpremium",addpremium_cmd),("removepremium",removepremium_cmd),
        ("broadcast",broadcast_cmd),("addcoupon",addcoupon_cmd),
        ("banuser",ban_user_cmd),("unbanuser",unban_user_cmd_owner),
        ("botstats",stats_cmd),("starsstats",stars_stats_cmd),
        ("setmodel",setmodel_cmd),("listmodels",listmodels_cmd),
        ("scan",scan_cmd),("resetuser",resetuser_cmd),
        ("giveall",giveall_cmd),("maintenance",maintenance_cmd),
    ]:
        app.add_handler(CommandHandler(c, f))

    # ── Dot/Bang Admin prefix ─────────────────────────────────────────
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(
            r"^[.!](warn|unwarn|warns|mute|imute|dmute|unmute|ban|dban|"
            r"unban|kick|promote|demote|demote_all|add|remove|title|"
            r"pin|unpin|d|help)\b"
        ),
        dot_admin_handler
    ))

    # ── Inline Callbacks ──────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(menu_callback,         pattern=r"^menu_"))
    app.add_handler(CallbackQueryHandler(eco_callback,          pattern=r"^eco_"))
    app.add_handler(CallbackQueryHandler(pay_callback,          pattern=r"^buy_premium_"))
    app.add_handler(CallbackQueryHandler(daily_remind_callback, pattern=r"^remind_daily_"))
    app.add_handler(CallbackQueryHandler(card_callback,         pattern=r"^card_"))
    app.add_handler(CallbackQueryHandler(bomb_callback,         pattern=r"^bomb_"))
    app.add_handler(CallbackQueryHandler(bluff_callback,        pattern=r"^bluff_"))
    app.add_handler(CallbackQueryHandler(hack_callback,         pattern=r"^hack_"))
    app.add_handler(CallbackQueryHandler(game_list_callback,    pattern=r"^game_"))
    app.add_handler(CallbackQueryHandler(report_callback,       pattern=r"^rep_"))
    app.add_handler(CallbackQueryHandler(ttt_callback,          pattern=r"^ttt_"))
    app.add_handler(CallbackQueryHandler(rps_callback,          pattern=r"^rps_"))
    app.add_handler(CallbackQueryHandler(quiz_callback,         pattern=r"^quiz_"))
    app.add_handler(CallbackQueryHandler(build_callback,        pattern=r"^build_"))
    app.add_handler(CallbackQueryHandler(captcha_callback,      pattern=r"^captcha_"))

    # ── Payments ──────────────────────────────────────────────────────
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(
        filters.SUCCESSFUL_PAYMENT, successful_payment_handler
    ))

    # ── Member events ──────────────────────────────────────────────────
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_handler
    ))
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS, anti_bot_handler
    ))
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS, anti_raid_handler
    ))
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS, captcha_new_member_handler
    ))
    app.add_handler(MessageHandler(
        filters.StatusUpdate.LEFT_CHAT_MEMBER, left_member_handler
    ))
    app.add_handler(MessageHandler(
        filters.StatusUpdate.LEFT_CHAT_MEMBER, clean_service_handler
    ))
    app.add_handler(MessageHandler(
        filters.StatusUpdate.PINNED_MESSAGE, channel_pin_handler
    ))

    # ── Group message handlers (priority order) ───────────────────────

    # 1. Lock enforcement
    app.add_handler(MessageHandler(
        ~filters.COMMAND & filters.ChatType.GROUPS,
        lock_enforcement_handler
    ), group=1)

    # 2. Flood check
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND,
        flood_check_handler
    ), group=2)

    # 3. Protection (spam/link)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND,
        protection_handler
    ), group=3)

    # 4. Welcome back after dead
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND,
        welcome_back_handler
    ), group=4)

    # 5. Iota name detection in groups (reply without @mention)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND,
        _iota_name_handler
    ), group=5)

    # 6. @mention AI in groups
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND,
        group_mention_handler
    ), group=6)

    # 7. Note getter (#notename)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        get_note_handler
    ), group=7)

    # 8. Hangman letter
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        hangman_handler
    ), group=8)

    # 9. Word game letter
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        wordgame_letter_handler
    ), group=9)

    # 10. Valentine form (DM)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
        valentine_message_handler
    ), group=10)

    # 11. DM AI auto-reply (lowest priority)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
        dm_message_handler
    ), group=11)

    # ── Post-init ─────────────────────────────────────────────────────
    async def post_init(application):
        await create_indexes()
        await load_model_config_db()
        # Background jobs
        asyncio.create_task(protection_alert_job(application.bot))
        asyncio.create_task(auto_daily_job(application.bot))
        asyncio.create_task(_memory_cleanup_job())
        asyncio.create_task(_premium_expiry_job(application.bot))
        logger.info("🤖 Iota Bot LIVE! Owner: @Boobies_00")

    app.post_init = post_init
    app.run_polling(drop_pending_updates=True)


# ── Iota name detection ────────────────────────────────────────────────────────

async def _iota_name_handler(update, context):
    """Detect 'iota' mentioned by name (without @tag) and reply."""
    msg  = update.effective_message
    text = (msg.text or "").lower()
    u    = update.effective_user

    if "iota" not in text:
        return

    # Already handled by @mention handler → skip double reply
    try:
        me = await context.bot.get_me()
        if f"@{me.username}".lower() in text:
            return
    except Exception:
        return

    from handlers.ai_chat import _respond, _safe
    from utils.mongo_db import ensure_user, get_user, update_last_seen

    await ensure_user(u.id, u.username or "", u.full_name)
    await update_last_seen(u.id, u.username or "", u.full_name)
    d = await get_user(u.id)

    try:
        reply = await _respond(
            u.id, msg.text, d.get("is_premium", False),
            True, update.effective_chat.title or "", 100
        )
        await msg.reply_html(_safe(reply))
    except Exception:
        pass


# ── Background jobs ────────────────────────────────────────────────────────────

async def _memory_cleanup_job():
    """Delete AI memories older than 30 days — runs daily."""
    while True:
        try:
            await asyncio.sleep(86400)  # once a day
            from utils.ai_memory import cleanup_old_memories
            deleted = await cleanup_old_memories()
            logger.info(f"🗑️ Memory cleanup: {deleted} old memories deleted")
        except Exception:
            pass


async def _premium_expiry_job(bot):
    """Check premium expirations every hour — notify and downgrade."""
    import time
    while True:
        try:
            await asyncio.sleep(3600)
            now = int(time.time())
            from utils.mongo_db import get_db
            db = get_db()
            # Find users whose premium expired
            expired = await db.users.find(
                {"is_premium": True,
                 "premium_until": {"$gt": 0, "$lt": now}}
            ).to_list(10000)
            for u in expired:
                await db.users.update_one(
                    {"_id": u["_id"]},
                    {"$set": {"is_premium": False}}
                )
                try:
                    await bot.send_message(
                        u["_id"],
                        "💓 Your Iota Premium has expired!\n"
                        "Renew with /pay or /fpay to keep all benefits 🌟",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            # Warn users expiring in 24h
            warn_before = now + 86400
            expiring = await db.users.find(
                {"is_premium": True,
                 "premium_until": {"$gt": now, "$lt": warn_before}}
            ).to_list(10000)
            for u in expiring:
                try:
                    rem = u["premium_until"] - now
                    await bot.send_message(
                        u["_id"],
                        f"⚠️ Your Premium expires in "
                        f"<b>{rem//3600}h {(rem%3600)//60}m</b>!\n"
                        f"Renew: /pay or /fpay",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
        except Exception:
            pass


if __name__ == "__main__":
    main()
