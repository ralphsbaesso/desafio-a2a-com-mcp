import agente


def test_entrypoint_do_agente_importa():
    assert callable(agente.main)
