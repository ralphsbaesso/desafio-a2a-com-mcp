import servidor


def test_entrypoint_do_servidor_importa():
    assert callable(servidor.main)
