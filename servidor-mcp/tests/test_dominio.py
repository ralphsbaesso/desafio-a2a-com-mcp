import pytest
from mcp.server.mcpserver.exceptions import ToolError

import dominio

DIA = "2026-11-03"


def h(hora: str) -> str:
    return f"{DIA}T{hora}:00-03:00"


@pytest.fixture(autouse=True)
def reservas_limpas():
    dominio.reiniciar_reservas()
    yield
    dominio.reiniciar_reservas()


def erro(fn, *args) -> str:
    with pytest.raises(ToolError) as exc:
        fn(*args)
    return str(exc.value)


def test_carga_do_starter():
    assert [s["id"] for s in dominio.SALAS][:2] == ["sala-aquario", "sala-porao"]
    assert [r["id"] for r in dominio.RESERVAS] == ["res-0001", "res-0002"]
    assert dominio.POLITICA_VERSAO == "2026-11-01"


def test_sala_inexistente():
    assert erro(dominio.validar_pedido, "sala-delorean", h("09:00"), h("10:00")) == "Sala inexistente: sala-delorean"


def test_intervalo_invertido_e_vazio():
    assert erro(dominio.validar_pedido, "sala-aquario", h("10:00"), h("09:00")) == dominio.ERRO_INTERVALO
    assert erro(dominio.validar_pedido, "sala-aquario", h("10:00"), h("10:00")) == dominio.ERRO_INTERVALO


def test_fora_da_janela():
    assert erro(dominio.validar_pedido, "sala-aquario", h("07:00"), h("08:00")) == dominio.ERRO_JANELA
    assert erro(dominio.validar_pedido, "sala-aquario", h("19:30"), h("20:30")) == dominio.ERRO_JANELA


def test_bordas_da_janela_sao_aceitas():
    dominio.validar_pedido("sala-aquario", h("08:00"), h("09:00"))
    dominio.validar_pedido("sala-aquario", h("19:00"), h("20:00"))


def test_janela_e_avaliada_no_fuso_da_politica():
    # 11:00Z = 08:00 em Sao Paulo: dentro da janela
    dominio.validar_pedido("sala-aquario", f"{DIA}T11:00:00+00:00", f"{DIA}T12:00:00+00:00")
    assert erro(dominio.validar_pedido, "sala-aquario", f"{DIA}T10:00:00+00:00", f"{DIA}T11:00:00+00:00") == dominio.ERRO_JANELA


def test_duracao_acima_do_limite():
    assert erro(dominio.validar_pedido, "sala-aquario", h("09:00"), h("12:00")) == dominio.ERRO_DURACAO
    dominio.validar_pedido("sala-aquario", h("09:00"), h("11:00"))


def test_ordem_de_validacao_e_estavel():
    # sala inexistente vence qualquer outro defeito; intervalo vence janela e duracao
    assert erro(dominio.validar_pedido, "sala-x", h("23:00"), h("01:00")).startswith("Sala inexistente")
    assert erro(dominio.validar_pedido, "sala-aquario", h("23:00"), h("22:00")) == dominio.ERRO_INTERVALO


def test_data_invalida():
    assert erro(dominio.validar_pedido, "sala-aquario", "ontem", h("10:00")).startswith("Intervalo invalido")


def test_conflitos_e_bordas():
    ini, end = dominio.validar_pedido("sala-garagem", h("14:30"), h("15:30"))
    assert [r["id"] for r in dominio.conflitos("sala-garagem", ini, end)] == ["res-0001"]
    ini, end = dominio.validar_pedido("sala-garagem", h("15:00"), h("16:00"))
    assert dominio.conflitos("sala-garagem", ini, end) == []
    ini, end = dominio.validar_pedido("sala-garagem", h("13:00"), h("14:00"))
    assert dominio.conflitos("sala-garagem", ini, end) == []


def test_alternativas_regra_do_desafio():
    ini, end = dominio.validar_pedido("sala-garagem", h("14:00"), h("15:00"))
    assert dominio.alternativas("sala-garagem", ini, end) == ["sala-fusca", "sala-mirante"]
    # aquario (cap 4): todas as outras cabem, mas so tres, ordenadas por capacidade e id
    ini, end = dominio.validar_pedido("sala-aquario", h("09:00"), h("10:00"))
    assert dominio.alternativas("sala-aquario", ini, end) == ["sala-porao", "sala-fusca", "sala-garagem"]


def test_alternativas_excluem_ocupadas_e_podem_ser_vazias():
    ini, end = dominio.validar_pedido("sala-fusca", h("14:00"), h("15:00"))
    assert dominio.alternativas("sala-fusca", ini, end) == ["sala-mirante"]
    ini, end = dominio.validar_pedido("sala-mirante", h("11:00"), h("12:00"))
    assert dominio.alternativas("sala-mirante", ini, end) == []


def test_criar_reserva_fica_visivel():
    r = dominio.criar_reserva("sala-porao", h("09:00"), h("10:00"), "Doc")
    assert r["id"] == "res-0003"
    ini, end = dominio.validar_pedido("sala-porao", h("09:30"), h("10:30"))
    assert dominio.conflitos("sala-porao", ini, end) == [r]
