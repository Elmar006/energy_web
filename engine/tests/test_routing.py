import json
from urllib.parse import parse_qs, urlsplit

import pytest

from energy.routing import derive_road_edges


def matrix(durations):
    return json.dumps({"code": "Ok", "durations": durations,
                       "sources": [{"distance": 15}], "destinations": [{"distance": 12}]}).encode()


def test_osrm_durations_replace_static_edges_without_fallback(small_input):
    captured = []

    def fake_fetch(url):
        captured.append(url)
        return matrix([[480.0]])

    result = derive_road_edges(small_input, osrm_url="http://osrm:5000", routing_dataset="road-graph-v1",
                               routing_license="ODbL 1.0; © OpenStreetMap contributors", fetch=fake_fetch)
    assert result.travel_edges[0].minutes == 8
    assert small_input.travel_edges[0].minutes == 5
    parsed = urlsplit(captured[0])
    assert parsed.path.startswith("/table/v1/driving/37.0000000,55.0000000;")
    assert parse_qs(parsed.query)["sources"] == ["0"]
    assert parse_qs(parsed.query)["destinations"] == ["1"]
    assert "fallback_speed" not in parsed.query
    assert result.datasets[0].role == "routing"
    assert "OpenStreetMap" in result.datasets[0].license


def test_unreachable_route_is_not_invented(small_input):
    result = derive_road_edges(small_input, osrm_url="http://osrm:5000", routing_dataset="graph",
                               fetch=lambda _: matrix([[None]]))
    assert result.travel_edges == []


def test_travel_limit_is_applied_to_road_duration(small_input):
    result = derive_road_edges(small_input, osrm_url="http://osrm:5000", routing_dataset="graph",
                               fetch=lambda _: matrix([[1260]]))
    assert result.travel_edges == []


@pytest.mark.parametrize("response", [
    b'{"code":"NoTable","durations":[]}',
    matrix([[1, 2]]),
    matrix([[-5]]),
    matrix([["NaN"]]),
    b'[]',
    b'{"code":"Ok","durations":[[5]]}',
])
def test_malformed_osrm_matrix_is_rejected(small_input, response):
    with pytest.raises(ValueError):
        derive_road_edges(small_input, osrm_url="http://osrm:5000", routing_dataset="graph",
                          fetch=lambda _: response)


def test_embedded_url_credentials_are_rejected(small_input):
    with pytest.raises(ValueError, match="without credentials"):
        derive_road_edges(small_input, osrm_url="https://user:pass@example.com", routing_dataset="graph")


def test_distant_road_snapping_is_rejected(small_input):
    response = json.dumps({"code": "Ok", "durations": [[10]],
                           "sources": [{"distance": 1500}], "destinations": [{"distance": 5}]}).encode()
    with pytest.raises(ValueError, match="too far"):
        derive_road_edges(small_input, osrm_url="http://osrm:5000", routing_dataset="graph",
                          fetch=lambda _: response)
