"""Checks for the meal plan's week navigation: "This week" returns from any
other week (it called shift_week(0), which moved nowhere).

    ./.venv/bin/python test_meal_plan.py
"""
from ledger_app.pages.recipes import RecipeState              # noqa: E402


def test_this_week_returns_from_any_week():
    st = RecipeState(_reflex_internal_init=True)
    st.shift_week(3)
    st.this_week()
    assert st.week_offset == 0, st.week_offset


if __name__ == "__main__":
    for fn in (test_this_week_returns_from_any_week,):
        fn()
        print(f"  ok  {fn.__name__}")
    print("meal plan checks passed")
