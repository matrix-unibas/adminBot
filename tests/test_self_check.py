"""Startup self-check: the bot marks its own account as a bot (exempt from user_consent)."""
from unittest.mock import AsyncMock


def mock_synapse(bot, set_user_type: AsyncMock) -> None:
    bot.synapse.is_server_admin = AsyncMock(return_value=True)
    bot.synapse.override_ratelimit = AsyncMock()
    bot.synapse.set_user_type = set_user_type
    bot.audit.report_check = AsyncMock()


async def test_self_check_marks_own_account_as_bot(bot):
    mock_synapse(bot, AsyncMock())
    await bot.self_check()
    bot.synapse.set_user_type.assert_awaited_once_with(bot.client.mxid, "bot")
    assert "bot_type" not in bot.failed_checks


async def test_failing_bot_type_is_a_warning_not_fatal(bot):
    mock_synapse(bot, AsyncMock(side_effect=RuntimeError("synapse down")))
    await bot.self_check()
    assert "bot_type" not in bot.failed_checks
    bot.audit.report_check.assert_any_await("bot_type", False, "synapse down")
