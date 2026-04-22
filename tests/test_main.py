from mtg_bot.__main__ import main


def test_main_runs_and_prints_result(capsys):
    main()
    out = capsys.readouterr().out
    assert "Turns played:" in out
    assert "Final life:" in out
    assert "Final battlefield:" in out
    # Either a draw or someone wins — one of these strings must appear.
    assert ("Result: DRAW" in out) or ("wins!" in out)
