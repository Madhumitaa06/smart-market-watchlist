"""
The assistant. The refusal path is tested first because it matters most: a
regression that let it answer "should I buy X" would be a regulatory problem,
not a bug.
"""

import cache
import database
import assistant


def test_it_declines_investment_advice():
    for question in ["Should I buy TCS?",
                     "Is RELIANCE a good investment?",
                     "Will INFY go up tomorrow?",
                     "Predict the price of SBIN",
                     "Which stock should I buy?"]:
        result = assistant.answer(question, user_id=1)
        assert result["kind"] == "declined", f"answered: {question}"


def test_advice_is_declined_even_when_it_names_a_watched_stock(steady_history):
    """Order matters: the advice check runs before ticker lookup, so a
    question containing a ticker isn't answered as a price query."""
    database.add_stock(1, "RELIANCE.NS")
    cache.put_history("RELIANCE.NS", steady_history)
    result = assistant.answer("Should I buy RELIANCE?", user_id=1)
    assert result["kind"] == "declined"


def test_it_answers_a_movement_question(steady_history):
    cache.put_history("RELIANCE.NS", steady_history)
    result = assistant.answer("How much did RELIANCE move last month?", user_id=1)
    assert result["kind"] == "movement"
    assert "%" in result["answer"]


def test_it_reports_the_watchlist():
    database.add_stock(1, "TCS.NS")
    database.add_stock(1, "INFY.NS")
    result = assistant.answer("What's in my watchlist?", user_id=1)
    assert "TCS" in result["answer"] and "INFY" in result["answer"]


def test_it_asks_which_stock_when_none_is_named():
    result = assistant.answer("How much did it move last week?", user_id=1)
    assert result["kind"] == "clarify"


def test_an_unrecognised_question_offers_its_capabilities():
    result = assistant.answer("What's the weather in Hyderabad?", user_id=1)
    assert result["kind"] in ("unknown", "clarify")
