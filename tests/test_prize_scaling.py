import json
import math

import pytest

import prize_scaling


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _exact_points(alpha=-8.0, beta=0.5, bits=(24, 28, 32, 36)):
    return [{"bits": size, "seconds": 2.0 ** (alpha + beta * size)} for size in bits]


def _records(tmp_path, problem="ecc_prize"):
    _write_json(
        tmp_path / "problems" / problem / "records.json",
        [
            {"name": "ecdlp-p24-dev", "bits": 24, "reference": {"baseline_seconds": 0.5}},
            {"name": "ecdlp-p28-dev", "bits": 28, "reference": {"baseline_seconds": 2.0}},
            {"name": "ecdlp-p32-dev", "bits": 32, "reference": {"baseline_seconds": 8.0}},
            {"name": "ecdlp-p36-dev", "bits": 36, "reference": {"baseline_seconds": 32.0}},
        ],
    )


def _evidence(tmp_path, run_id, problem, rows):
    _write_json(
        tmp_path / "runs" / "research" / run_id / problem / "evidence.json",
        {"run_id": run_id, "problem": problem, "development": {"incumbent": rows}},
    )


def test_fit_recovers_a_clean_power_law():
    fit = prize_scaling.fit_scaling(_exact_points())
    assert fit["model"] == prize_scaling.MODEL
    assert fit["alpha"] == pytest.approx(-8.0, abs=1e-6)
    assert fit["beta"] == pytest.approx(0.5, abs=1e-6)
    assert fit["r2"] == pytest.approx(1.0, abs=1e-9)
    assert fit["n_points"] == 4
    assert fit["residual_sd"] == pytest.approx(0.0, abs=1e-9)
    assert fit["beta_vs_theory"]["theory_beta"] == 0.5
    assert fit["beta_vs_theory"]["ratio"] == pytest.approx(1.0, abs=1e-6)


def test_fit_reports_a_beta_above_theory():
    fit = prize_scaling.fit_scaling(_exact_points(beta=0.62))
    assert fit["beta"] == pytest.approx(0.62, abs=1e-6)
    assert fit["beta_vs_theory"]["ratio"] > 1.0


def test_fit_refuses_a_ladder_it_cannot_support():
    with pytest.raises(prize_scaling.ScalingError):
        prize_scaling.fit_scaling([{"bits": 24, "seconds": 1.0}, {"bits": 28, "seconds": 2.0}])
    with pytest.raises(prize_scaling.ScalingError):
        prize_scaling.fit_scaling([{"bits": 24, "seconds": 1.0}] * 3)
    with pytest.raises(prize_scaling.ScalingError):
        prize_scaling.fit_scaling([{"bits": 24, "seconds": 0.0}, {"bits": 28, "seconds": -1}, {"bits": 32}])


def test_extrapolation_to_a_prize_sized_instance_says_infeasible():
    fit = prize_scaling.fit_scaling(_exact_points())
    projection = prize_scaling.extrapolate(fit, 131)
    json.dumps(projection, allow_nan=False)
    assert projection["target_bits"] == 131
    assert projection["verdict"] == "infeasible"
    assert "infeasible" in projection["summary"]
    assert "change of economics" in projection["summary"]
    assert projection["cpu_years"]["mid"] > prize_scaling.INFEASIBLE_CPU_YEARS
    # Bands are stored at six significant figures on purpose: no fake precision.
    assert projection["seconds"]["mid"] == pytest.approx(2.0**57.5, rel=1e-5)
    assert projection["gpu_years"] is None
    assert any("per core-hour" in note for note in projection["assumptions"])


def test_extrapolation_band_is_ordered_and_widens_with_noise():
    # Noise that steepens the fit: a beta below theory collapses the low band onto the theory floor
    # (see test_bands_never_promise_less_work_than_the_theory_bound), which has nothing to say about ordering.
    noisy = _exact_points()
    noisy[1]["seconds"] /= 1.7
    noisy[2]["seconds"] *= 1.4
    fit = prize_scaling.fit_scaling(noisy)
    assert fit["residual_sd"] > 0
    assert fit["beta"] > prize_scaling.THEORY_BETA
    projection = prize_scaling.extrapolate(fit, 64)
    assert projection["seconds"]["low"] < projection["seconds"]["mid"] < projection["seconds"]["high"]
    assert projection["usd"]["low"] < projection["usd"]["high"]


def test_bands_never_promise_less_work_than_the_theory_bound():
    # A shallow ladder fit (beta below 0.5) would otherwise extrapolate to less work than a generic
    # rho / birthday search; every band is floored at alpha + 0.5*bits and the floor is declared.
    fit = prize_scaling.fit_scaling(_exact_points(beta=0.35))
    assert fit["beta"] < prize_scaling.THEORY_BETA
    projection = prize_scaling.extrapolate(fit, 131)
    floor = 2.0 ** (fit["alpha"] + prize_scaling.THEORY_BETA * 131)

    assert projection["seconds"]["mid"] == pytest.approx(floor, rel=1e-5)
    for band in ("low", "mid", "high"):
        assert projection["seconds"][band] >= floor * (1 - 1e-6)
    assert any("theory bound" in note for note in projection["assumptions"])

    # A fit at or above theory is left alone: nothing is floored and no assumption is added.
    at_theory = prize_scaling.extrapolate(prize_scaling.fit_scaling(_exact_points(beta=0.6)), 131)
    assert not any("theory bound" in note for note in at_theory["assumptions"])


def test_small_target_is_feasible_and_gpu_figures_are_labelled_as_assumed():
    fit = prize_scaling.fit_scaling(_exact_points())
    projection = prize_scaling.extrapolate(fit, 40, gpu_speedup=100.0)
    assert projection["verdict"] == "feasible"
    assert projection["gpu_years"]["mid"] == pytest.approx(projection["cpu_years"]["mid"] / 100.0, rel=1e-6)
    assert projection["gpu_usd"] is not None
    assert any("assumed speedup" in note for note in projection["assumptions"])


def test_extrapolation_stays_json_safe_at_absurd_sizes():
    fit = prize_scaling.fit_scaling(_exact_points(beta=3.0))
    projection = prize_scaling.extrapolate(fit, 4096)
    json.dumps(projection, allow_nan=False)
    assert math.isfinite(projection["seconds"]["high"])
    assert projection["verdict"] == "infeasible"
    assert any("beyond estimation" in note for note in projection["assumptions"])


def test_ladder_points_fall_back_to_the_committed_reference_baselines(tmp_path):
    _records(tmp_path)
    points = prize_scaling.ladder_points(tmp_path, "ecc_prize")
    assert [point["bits"] for point in points] == [24, 28, 32, 36]
    assert {point["source"] for point in points} == {"baseline_reference"}
    assert points[0]["seconds"] == 0.5


def test_ladder_points_prefer_measured_runs_and_the_newest_run_wins(tmp_path):
    _records(tmp_path)
    _evidence(
        tmp_path,
        "2026-09-18",
        "ecc_prize",
        [
            {"target": "ecdlp-p24-dev", "secs": 1.0, "failed": False},
            {"target": "ecdlp-p28-dev", "secs": 4.0, "failed": False},
        ],
    )
    _evidence(
        tmp_path,
        "2026-09-19",
        "ecc_prize",
        [
            {"target": "ecdlp-p24-dev", "secs": 0.25, "failed": False},
            {"target": "ecdlp-p32-dev", "secs": 4.0, "failed": False},
            {"target": "ecdlp-p36-dev", "secs": 0.0, "failed": True},
            {"target": "not-in-records", "secs": 9.0, "failed": False},
        ],
    )
    points = prize_scaling.ladder_points(tmp_path, "ecc_prize")
    by_target = {point["target"]: point for point in points}
    assert set(by_target) == {"ecdlp-p24-dev", "ecdlp-p28-dev", "ecdlp-p32-dev"}
    assert by_target["ecdlp-p24-dev"]["seconds"] == 0.25
    assert by_target["ecdlp-p24-dev"]["run_id"] == "2026-09-19"
    assert by_target["ecdlp-p28-dev"]["run_id"] == "2026-09-18"
    assert {point["source"] for point in points} == {"measured"}


def test_ladder_points_are_empty_without_records_or_runs(tmp_path):
    assert prize_scaling.ladder_points(tmp_path, "ecc_prize") == []


class _Plugin:
    PRIZE_TARGET_METADATA = {"certicom-eccp-131": {"bits": 131, "note": "metadata only; never a target"}}


def test_analysis_joins_the_ladder_to_the_real_target(tmp_path):
    _records(tmp_path)
    prize = {"id": "certicom-eccp-131", "plugin": "ecc_prize", "real_target": "ECCp-131"}
    result = prize_scaling.analysis(tmp_path, prize, _Plugin)
    json.dumps(result, allow_nan=False)
    assert result["supported"] is True
    assert result["target_bits"] == 131
    assert result["fit"]["n_points"] == 4
    assert result["extrapolation"]["verdict"] == "infeasible"
    assert result["summary"] == result["extrapolation"]["summary"]


def test_analysis_degrades_instead_of_raising(tmp_path):
    unbound = prize_scaling.analysis(tmp_path, {"id": "hutter-prize", "plugin": None}, None)
    assert unbound["supported"] is False and "no bound plugin" in unbound["reason"]

    unknown_size = prize_scaling.analysis(tmp_path, {"id": "x", "plugin": "ecc_prize"}, None)
    assert unknown_size["supported"] is False and "bits" in unknown_size["reason"]

    _records(tmp_path)
    short = prize_scaling.analysis(tmp_path, {"id": "x", "plugin": "ecc_prize", "target_bits": 131}, None)
    assert short["supported"] is True

    empty = prize_scaling.analysis(tmp_path, {"id": "x", "plugin": "missing_plugin", "target_bits": 64}, None)
    assert empty["supported"] is False and "at least" in empty["reason"]


def _hash_records(tmp_path):
    """The hash ladder's own records.json shape, with the two cost families and the reduced-round rung."""
    _write_json(
        tmp_path / "problems" / "hash_collision_prize" / "records.json",
        {
            "schema_version": 1,
            "targets": {
                "sha256-t28-dev": {"function": "sha256", "bits": 28, "reference": {"baseline_seconds": 0.005}},
                "sha256-t32-dev": {"function": "sha256", "bits": 32, "reference": {"baseline_seconds": 0.086}},
                "sha256-t36-dev": {"function": "sha256", "bits": 36, "reference": {"baseline_seconds": 0.336}},
                "ripemd160-t32-dev": {"function": "ripemd160", "bits": 32, "reference": {"baseline_seconds": 0.182}},
                "ripemd160-t36-large": {"function": "ripemd160", "bits": 36, "reference": {"baseline_seconds": 0.438}},
                "ripemd160-t40-large": {"function": "ripemd160", "bits": 40, "reference": {"baseline_seconds": 1.447}},
                "sha256r24-t32-hold": {
                    "function": "sha256-reduced",
                    "rounds": 24,
                    "bits": 32,
                    "reference": {"baseline_seconds": 2.021},
                },
            },
        },
    )


class _HashPlugin:
    # The plugin labels a bounty by its definition, not by a bare function name.
    PRIZE_TARGET_METADATA = {
        "bounties": {
            "todd-hash160-collision": {"bits": 160, "function": "HASH160 = RIPEMD-160(SHA-256(x))"},
            "todd-hash256-collision": {"bits": 256, "function": "HASH256 = SHA-256(SHA-256(x))"},
        }
    }


def test_family_reduces_a_prose_label_to_its_leading_token():
    assert prize_scaling._family("HASH160 = RIPEMD-160(SHA-256(x))") == "ripemd160"
    assert prize_scaling._family("HASH256 = SHA-256(SHA-256(x))") == "sha256"
    assert prize_scaling._family("SHA-256") == "sha256"
    assert prize_scaling._family("RIPEMD-160") == "ripemd160"
    assert prize_scaling._family("sha256-reduced") == "sha256-reduced"
    assert prize_scaling._family("") is None
    assert prize_scaling._family(None) is None


@pytest.mark.parametrize(
    "prize_id, family, bits",
    [("todd-hash160-collision", "ripemd160", 160), ("todd-hash256-collision", "sha256", 256)],
)
def test_prose_labelled_bounties_still_find_their_ladder_family(tmp_path, prize_id, family, bits):
    _hash_records(tmp_path)
    prize = {"id": prize_id, "plugin": "hash_collision_prize"}
    result = prize_scaling.analysis(tmp_path, prize, _HashPlugin)
    json.dumps(result, allow_nan=False)

    assert result["ladder_family"] == family
    assert result["target_bits"] == bits
    assert len(result["points"]) >= prize_scaling.MIN_POINTS
    assert result["supported"] is True
    assert result["extrapolation"]["verdict"] == "infeasible"
    # The reduced-round rung is its own cost family and never joins a full-digest extrapolation.
    assert "sha256r24-t32-hold" not in {point["target"] for point in result["points"]}


def test_board_scaling_cell_carries_the_assumptions(tmp_path):
    import prize_report

    _records(tmp_path)
    cell = prize_report._scaling(tmp_path, {"id": "certicom-eccp-131", "plugin": "ecc_prize"}, _Plugin)
    json.dumps(cell, allow_nan=False)
    assert cell["supported"] is True
    assert isinstance(cell["assumptions"], list)
    assert any("per core-hour" in note for note in cell["assumptions"])

    shallow = tmp_path / "shallow"
    _write_json(
        shallow / "problems" / "ecc_prize" / "records.json",
        [
            {"name": f"ecdlp-p{size}-dev", "bits": size, "reference": {"baseline_seconds": 2.0 ** (-8 + 0.35 * size)}}
            for size in (24, 28, 32, 36)
        ],
    )
    floored = prize_report._scaling(shallow, {"id": "certicom-eccp-131", "plugin": "ecc_prize"}, _Plugin)
    assert any("theory bound" in note for note in floored["assumptions"])
