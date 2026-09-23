from datetime import date

import pytest

from energy.ingest_grid import apply_grid_profile


def csv_profile(node_id: str, *, hours=range(24), value=12.5):
    rows = ["grid_node_id,hour,headroom_kw"]
    rows += [f"{node_id},{hour},{value}" for hour in hours]
    return ("\n".join(rows) + "\n").encode()


def import_profile(small_input, csv_bytes):
    return apply_grid_profile(small_input, csv_bytes, source="Письмо сетевой организации, № 123",
                              profile_date=date(2026, 9, 1), time_zone="Europe/Moscow", kind="observed")


def test_grid_profile_replaces_only_headroom_with_provenance(small_input):
    node_id = small_input.grid_nodes[0].id
    original = small_input.grid_nodes[0].headroom_kw[:]
    raw = csv_profile(node_id)
    result = import_profile(small_input, raw)
    assert result.grid_nodes[0].headroom_kw == [12.5] * 24
    assert small_input.grid_nodes[0].headroom_kw == original
    assert result.grid_nodes[0].provenance.kind == "observed"
    assert result.datasets[0].role == "grid"
    assert len(result.datasets[0].sha256) == 64
    assert "2026-09-01" in result.datasets[0].source


@pytest.mark.parametrize("raw,reason", [
    (csv_profile("bad-node"), "unknown grid_node_id"),
    (csv_profile("NODE", hours=range(23)), "missing grid hours"),
    (csv_profile("NODE", hours=[*range(24), 1]), "duplicate"),
    (csv_profile("NODE", value=-1), "nonnegative"),
    (csv_profile("NODE", value="NaN"), "finite"),
    (csv_profile("NODE", hours=[*range(23), 24]), "hour must"),
    (b"grid_node_id,hour\n", "requires"),
])
def test_rejects_incomplete_or_invalid_grid_profile(small_input, raw, reason):
    node_id = small_input.grid_nodes[0].id
    with pytest.raises(ValueError, match=reason):
        import_profile(small_input, raw.replace(b"NODE", node_id.encode()))


def test_missing_second_node_is_not_assumed_zero(small_input):
    second = small_input.grid_nodes[0].model_copy(deep=True)
    second.id = "another-grid-node"
    small_input.grid_nodes.append(second)
    with pytest.raises(ValueError, match="another-grid-node"):
        import_profile(small_input, csv_profile(small_input.grid_nodes[0].id))


def test_invalid_time_zone_is_rejected(small_input):
    with pytest.raises(ValueError, match="unknown IANA"):
        apply_grid_profile(small_input, csv_profile(small_input.grid_nodes[0].id),
                           source="source", profile_date=date(2026, 9, 1), time_zone="Wrong/Timezone")


def test_scenario_grid_profile_stays_assumed(small_input):
    result = apply_grid_profile(small_input, csv_profile(small_input.grid_nodes[0].id),
                                source="Синтетический тест", profile_date=date(2026, 9, 1),
                                time_zone="Europe/Moscow", kind="assumed")
    assert result.grid_nodes[0].provenance.kind == "assumed"
    assert result.datasets[0].kind == "assumed"
