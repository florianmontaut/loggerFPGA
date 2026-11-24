"""Fichier projet (model/project.py) : format, chemins, balises."""
import json
import os

import pytest

from model.project import EXTENSION, Bookmark, Project, ProjectError, is_project_file


def _project(folder):
    records = [str(folder / "essais" / "A.h5"), str(folder / "essais" / "B.h5")]
    for path in records:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
    return Project(records=records, current=records[1], view=[-1e-3, 2e-3],
                   axis_mode="channel",
                   channels={"CH1": {"y": [-650.0, 650.0], "visible": True},
                             "I gate": {"y": [-0.2, 15.5], "visible": False}},
                   highlighted="I gate",
                   math_channels=[{"name": "P", "formula": "[CH1]*[CH2]", "unit": "W",
                                   "enabled": True}],
                   bookmarks=[Bookmark("Commutation", [1.2e-4, 1.6e-4],
                                       {"CH1": [-50.0, 700.0]}, "iVBOR")])


def test_round_trip(tmp_path):
    project = _project(tmp_path)
    path = tmp_path / ("essai" + EXTENSION)
    project.save(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == "loggerfpga_project" and data["version"] == 1
    assert [r["path"] for r in data["records"]] == ["essais/A.h5", "essais/B.h5"]
    assert data["current"] == 1
    back = Project.load(str(path))
    assert back.records == project.records and back.current == project.records[1]
    assert back.channels == project.channels and back.highlighted == "I gate"
    assert back.view == [-1e-3, 2e-3] and back.axis_mode == "channel"
    assert back.math_channels == project.math_channels
    assert back.bookmarks == project.bookmarks
    assert is_project_file(str(path)) and not is_project_file("A.h5")


def test_moved_folder_and_absolute_fallback(tmp_path):
    project = _project(tmp_path)
    project.save(str(tmp_path / "p.lfproj"))
    moved = tmp_path / "copie"
    os.rename(tmp_path / "essais", tmp_path / "x")
    (moved / "essais").mkdir(parents=True)
    os.rename(tmp_path / "x" / "A.h5", moved / "essais" / "A.h5")
    os.rename(tmp_path / "p.lfproj", moved / "p.lfproj")
    back = Project.load(str(moved / "p.lfproj"))
    # A suit le projet (chemin relatif) ; B, absent à côté, garde son chemin absolu
    assert back.records[0] == str(moved / "essais" / "A.h5")
    assert back.records[1] == os.path.normpath(str(tmp_path / "essais" / "B.h5"))


def test_records_added_once(tmp_path):
    project = Project()
    assert project.add_record(str(tmp_path / "A.h5"))
    assert not project.add_record(str(tmp_path / "." / "A.h5"))
    project.remove_record(str(tmp_path / "A.h5"))
    assert project.records == []


def test_merge_keeps_other_records_channels():
    project = Project(channels={"CH1": {"y": [0, 1]}, "CH3": {"y": [2, 3]}})
    project.merge_channels({"CH1": {"y": [5, 6], "visible": False}})
    assert project.channels == {"CH1": {"y": [5, 6], "visible": False},
                                "CH3": {"y": [2, 3]}}


def test_bookmark_zoom_and_position():
    bookmark = Bookmark("B", [0.204, 0.208])
    assert bookmark.zoom(0.2) == pytest.approx(50)
    assert bookmark.position(0.165, 0.2) == pytest.approx(0.205)


@pytest.mark.parametrize("content, message", [
    ("{", "JSON"),
    ('{"format": "autre"}', "pas un projet"),
    ('{"format": "loggerfpga_project", "version": 99}', "version 99"),
    ('{"format": "loggerfpga_project", "version": 1, "bookmarks": [{"x": [2, 1]}]}',
     "portion de temps"),
])
def test_invalid_files(tmp_path, content, message):
    path = tmp_path / "p.lfproj"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ProjectError, match=message):
        Project.load(str(path))
    with pytest.raises(ProjectError, match="illisible"):
        Project.load(str(tmp_path / "absent.lfproj"))


def test_invalid_ranges_dropped(tmp_path):
    path = tmp_path / "p.lfproj"
    path.write_text(json.dumps({
        "format": "loggerfpga_project", "version": 1,
        "channels": {"CH1": {"y": [1, 1]}, "CH2": {"y": "x"}, "CH3": {"y": [0, 2]}},
        "bookmarks": [{"name": "B", "x": [0, 1], "y": {"CH1": [3, 2], "CH2": [0, 1]}}]}))
    project = Project.load(str(path))
    assert project.channels == {"CH1": {"visible": True}, "CH2": {"visible": True},
                                "CH3": {"y": [0.0, 2.0], "visible": True}}
    assert project.bookmarks[0].y == {"CH2": [0.0, 1.0]}
