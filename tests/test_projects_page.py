def test_projects_grouped_by_pi(client, seed_project):
    seed_project(name="Zeta", pi_name="Dr. Bravo")
    seed_project(name="Alpha", pi_name="Dr. Alpha")
    body = client.get("/projects").data.decode()
    assert "pi-group-header" in body
    # PI groups alphabetical: Dr. Alpha before Dr. Bravo
    assert body.index("Dr. Alpha") < body.index("Dr. Bravo")


def test_projects_no_pi_group_sorts_last(client, seed_project):
    seed_project(name="Named", pi_name="Dr. Alpha")
    seed_project(name="Orphan", pi_name="")
    body = client.get("/projects").data.decode()
    assert "No PI" in body
    assert body.index("Dr. Alpha") < body.index("No PI")
