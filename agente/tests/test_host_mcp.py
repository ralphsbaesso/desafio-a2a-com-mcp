import re

import pytest
from mcp_types import CallToolResult, ElicitResult, InputRequiredResult

import dominio
import host_mcp
import servidor
from host_mcp import HostMCP

SEGREDO = "s" * 32
TP = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
PEDIDO = {"sala": "sala-garagem", "inicio": "2026-11-03T14:00:00-03:00", "fim": "2026-11-03T15:00:00-03:00", "responsavel": "Marty"}


@pytest.fixture(autouse=True)
def reservas_limpas():
    dominio.reiniciar_reservas()
    yield
    dominio.reiniciar_reservas()


def linhas_mcp(capsys) -> list[str]:
    return [l for l in capsys.readouterr().err.splitlines() if l.startswith("[mcp] method=")]


def test_traceparent_valido_e_novo_span():
    assert host_mcp.traceparent_valido(TP) == TP
    assert host_mcp.traceparent_valido(TP.upper()) == TP
    assert host_mcp.traceparent_valido("lixo") is None
    assert host_mcp.traceparent_valido(None) is None
    assert host_mcp.traceparent_valido("ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01") is None
    assert host_mcp.traceparent_valido("00-" + "0" * 32 + "-00f067aa0ba902b7-01") is None
    assert host_mcp.traceparent_valido("00-4bf92f3577b34da6a3ce929d0e0e4736-" + "0" * 16 + "-01") is None
    assert host_mcp.novo_span("lixo") is None
    filho = host_mcp.novo_span(TP)
    assert filho != TP and filho.split("-")[1] == TP.split("-")[1] and filho.split("-")[3] == "01"
    assert re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-01", filho)


def test_versao_da_politica():
    assert host_mcp.versao_da_politica("versao: 2026-11-01\n\n- regra") == "2026-11-01"
    with pytest.raises(ValueError):
        host_mcp.versao_da_politica("- sem cabecalho")


async def test_descobre_tools_antes_do_primeiro_call_e_le_a_politica(capsys):
    host = HostMCP(servidor.criar_servidor(SEGREDO))
    await host.abrir()
    try:
        r = await host.reservar({**PEDIDO, "sala": "sala-aquario"}, TP)
        assert isinstance(r, CallToolResult) and r.structured_content["reservado"] is True
        assert host.tools == ["listar_salas", "consultar_disponibilidade", "reservar_sala"]
        assert host.versao_politica == "2026-11-01"
        # segunda chamada nao redescobre
        await host.reservar({**PEDIDO, "sala": "sala-porao"}, TP)
    finally:
        await host.fechar()
    metodos = [l.split()[1] for l in linhas_mcp(capsys)]
    assert metodos == ["method=tools/list", "method=resources/read", "method=tools/call", "method=tools/call"]


async def test_input_required_volta_cru_e_retry_tem_id_novo(capsys):
    host = HostMCP(servidor.criar_servidor(SEGREDO))
    await host.abrir()
    try:
        r = await host.reservar(PEDIDO, TP)
        assert isinstance(r, InputRequiredResult)
        chave, req = next(iter(r.input_requests.items()))
        assert req.params.requested_schema["properties"]["sala"]["enum"] == ["sala-fusca", "sala-mirante"]
        retry = await host.reservar(
            PEDIDO, TP, input_responses={chave: ElicitResult(action="accept", content={"sala": "sala-fusca"})}, request_state=r.request_state
        )
        assert isinstance(retry, CallToolResult) and retry.structured_content["sala"] == "sala-fusca"
    finally:
        await host.fechar()
    calls = [l for l in linhas_mcp(capsys) if "name=reservar_sala" in l]
    ids = [re.search(r" id=(\S+)", l).group(1) for l in calls]
    assert len(ids) == 2 and ids[0] != ids[1]
    assert "retry=sim" in calls[1] and "retry=sim" not in calls[0]


async def test_traceparent_propaga_trace_id_com_span_novo(capsys):
    host = HostMCP(servidor.criar_servidor(SEGREDO))
    await host.abrir()
    await host.abrir()  # idempotente
    try:
        await host.reservar({**PEDIDO, "sala": "sala-aquario"}, TP)
        await host.reservar({**PEDIDO, "sala": "sala-porao"}, None)
        r = await host.reservar({**PEDIDO, "sala": "sala-aquario", "inicio": "2026-11-03T11:00:00-03:00", "fim": "2026-11-03T12:00:00-03:00"}, "lixo")
        assert isinstance(r, CallToolResult) and not r.is_error
    finally:
        await host.fechar()
    linhas = linhas_mcp(capsys)
    tps = [re.search(r"traceparent=(\S+)", l).group(1) for l in linhas]
    assert len(tps) == 5
    assert all(t.split("-")[1] == TP.split("-")[1] for t in tps[:3])
    assert len({t.split("-")[2] for t in tps[:3]}) == 3  # span novo por request
    assert tps[3] == "-"  # sem header A2A, sem traceparent
    assert tps[4] == "-"  # header invalido: segue sem trace, sem derrubar a reserva


async def test_descoberta_concorrente_faz_um_unico_tools_list(capsys):
    import asyncio

    host = HostMCP(servidor.criar_servidor(SEGREDO))
    await host.abrir()
    try:
        pedidos = [{**PEDIDO, "sala": s, "inicio": "2026-11-03T10:00:00-03:00", "fim": "2026-11-03T11:00:00-03:00"} for s in ("sala-aquario", "sala-porao", "sala-fusca")]
        resultados = await asyncio.gather(*(host.reservar(p, TP) for p in pedidos))
        assert all(isinstance(r, CallToolResult) and not r.is_error for r in resultados)
    finally:
        await host.fechar()
    metodos = [l.split()[1] for l in linhas_mcp(capsys)]
    assert metodos.count("method=tools/list") == 1 and metodos.count("method=resources/read") == 1
    assert metodos[0] == "method=tools/list" and metodos.count("method=tools/call") == 3


async def test_servidor_sem_reservar_sala_falha_com_mensagem_clara():
    from mcp.server.mcpserver import MCPServer

    vazio = MCPServer(name="outro")

    def outra_tool() -> str:
        return "x"

    vazio.tool()(outra_tool)
    host = HostMCP(vazio)
    await host.abrir()
    try:
        with pytest.raises(RuntimeError, match="nao expoe a tool 'reservar_sala'"):
            await host.preparar()
    finally:
        await host.fechar()


async def test_capability_de_elicitation_form_e_declarada():
    host = HostMCP(servidor.criar_servidor(SEGREDO))
    await host.abrir()
    try:
        async with host._sessao() as client:
            # API privada do SDK (pinado em 2.3.0): e o unico ponto que mostra a capability carimbada no _meta
            caps = client.session._build_capabilities("2026-07-28").model_dump(by_alias=True, exclude_none=True)
        assert caps["elicitation"]["form"] == {}
    finally:
        await host.fechar()


async def test_ids_jsonrpc_crescem_por_processo_entre_operacoes(capsys):
    host = HostMCP(servidor.criar_servidor(SEGREDO))
    await host.abrir()
    try:
        for sala in ("sala-aquario", "sala-porao", "sala-fusca"):
            await host.reservar({**PEDIDO, "sala": sala, "inicio": "2026-11-03T10:00:00-03:00", "fim": "2026-11-03T11:00:00-03:00"}, TP)
    finally:
        await host.fechar()
    ids = [int(re.search(r" id=(\d+)", l).group(1)) for l in linhas_mcp(capsys)]
    assert ids == sorted(ids) and len(set(ids)) == 5
    assert ids[0] == 1 and ids[1] == 2  # descoberta: duas chamadas na mesma janela


async def test_ids_sao_unicos_com_reservas_concorrentes(capsys):
    import asyncio

    host = HostMCP(servidor.criar_servidor(SEGREDO))
    await host.abrir()
    try:
        await host.preparar(TP)
        pedidos = [{**PEDIDO, "sala": s, "inicio": "2026-11-03T10:00:00-03:00", "fim": "2026-11-03T11:00:00-03:00"} for s in ("sala-aquario", "sala-porao", "sala-fusca", "sala-garagem")]
        await asyncio.gather(*(host.reservar(p, TP) for p in pedidos))
    finally:
        await host.fechar()
    ids = [int(re.search(r" id=(\d+)", l).group(1)) for l in linhas_mcp(capsys) if "tools/call" in l]
    assert len(ids) == 4 and len(set(ids)) == 4


async def test_porta_fechada_da_erro_de_transporte_e_nao_prende_o_lock():
    import asyncio

    import httpx2

    host = HostMCP("http://127.0.0.1:1/mcp", timeout=2)
    await host.abrir()
    try:
        with pytest.raises(httpx2.TransportError):  # desembrulhado do ExceptionGroup do SDK
            await host.reservar(PEDIDO, TP)
        with pytest.raises(httpx2.TransportError):  # o lock de descoberta foi liberado
            await asyncio.wait_for(host.reservar(PEDIDO, TP), timeout=5)
    finally:
        await host.fechar()


def test_mcp_timeout_invalido_falha_claro(monkeypatch):
    for valor in ("abc", "0", "-1", "nan", "inf"):
        monkeypatch.setenv("MCP_TIMEOUT", valor)
        with pytest.raises(ValueError, match="MCP_TIMEOUT invalido"):
            HostMCP("http://127.0.0.1:1/mcp")
    monkeypatch.setenv("MCP_TIMEOUT", "")
    assert HostMCP("http://127.0.0.1:1/mcp")._timeout == host_mcp.TIMEOUT_PADRAO


async def test_erro_de_execucao_volta_como_resultado():
    host = HostMCP(servidor.criar_servidor(SEGREDO))
    await host.abrir()
    try:
        r = await host.reservar({**PEDIDO, "sala": "sala-delorean"}, TP)
        assert isinstance(r, CallToolResult) and r.is_error
        assert "Sala inexistente: sala-delorean" in r.content[0].text
    finally:
        await host.fechar()
