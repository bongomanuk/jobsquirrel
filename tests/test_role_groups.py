"""Role groups (campaigns): independent of status, stored beside the register."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import dashboard as D  # noqa: E402


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "ROLE_GROUPS", str(tmp_path / "role-groups.json"))


def test_create_assign_and_filter(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    made = D.group_action("create", name="Q4 fintech")
    assert made["group"]["id"] == "q4-fintech"
    gid = made["group"]["id"]
    assert D.group_action("assign", group=gid, key="role-a", on=True)["groups"] == [gid]
    view = D.groups_view()
    assert view["groups"][0]["count"] == 1
    assert view["roles"]["role-a"] == [gid]
    # removing the last membership removes the role entry
    assert D.group_action("assign", group=gid, key="role-a", on=False)["groups"] == []
    assert D.groups_view()["roles"] == {}


def test_duplicate_names_get_distinct_ids(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    a = D.group_action("create", name="Nordic")["group"]["id"]
    b = D.group_action("create", name="Nordic")["group"]["id"]
    assert a != b


def test_rename_and_delete_clean_memberships(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    gid = D.group_action("create", name="Campaign A")["group"]["id"]
    D.group_action("assign", group=gid, key="role-a", on=True)
    assert D.group_action("rename", group=gid, name="Campaign B")["group"]["name"] == "Campaign B"
    assert D.group_action("delete", group=gid)["ok"] == "deleted"
    assert D.groups_view() == {"groups": [], "roles": {}}


def test_unknown_group_and_missing_name_are_refused(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    assert "error" in D.group_action("create", name="   ")
    assert "error" in D.group_action("assign", group="nope", key="role-a", on=True)
    assert "error" in D.group_action("assign", group="nope", key="", on=True)
    assert "error" in D.group_action("nonsense")
