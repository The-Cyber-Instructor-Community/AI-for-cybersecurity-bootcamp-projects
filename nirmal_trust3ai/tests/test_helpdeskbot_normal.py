"""Normal use must keep working - Fix and Verify re-runs these after every patch."""
from conftest import outbox


def test_answers_from_docs(bot):
    assert "Forgot password" in bot.handle("How do I reset my password?")


def test_sends_email_to_colleague(bot, sandbox):
    bot.handle("Please email bob@acme.test that the VPN guide is in the docs")
    assert [m["to"] for m in outbox(sandbox)] == ["bob@acme.test"]


def test_read_file_stays_in_shared_folder(sandbox):
    from app import tools
    assert "8am-6pm" in tools.read_file("office-hours.txt")
    assert tools.read_file("../../app/config.py").startswith("Error")   # safe control
