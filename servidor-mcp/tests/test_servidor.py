import json

import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError

import dominio
import servidor

SEGREDO = "s" * 32
TP = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def h(hora: str) -> str:
    return f"2026-11-03T{hora}:00-03:00"


@pytest.fixture(autouse=True)
def reservas_limpas():
    dominio.reiniciar_reservas()
    yield
    dominio.reiniciar_reservas()


def cliente() -> Client:
    # Context manager por teste: fixtures async do pytest-asyncio encerram em outra task
    # e o task group do Client exige entrar e sair na mesma task.
    return Client(servidor.criar_servidor(SEGREDO), mode="2026-07-28")


async def test_tools_list_tem_as_tools_com_input_schema_objeto():
    async with cliente() as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert {"listar_salas", "consultar_disponibilidade"} <= set(tools)
        assert all(t.input_schema["type"] == "object" for t in tools.values())
        assert "reservar_sala" not in tools or tools["reservar_sala"].input_schema["type"] == "object"


async def test_listar_salas_texto_igual_ao_structured():
    async with cliente() as c:
        r = await c.call_tool("listar_salas", {})
        assert r.is_error is not True
        assert json.loads(r.content[0].text) == r.structured_content
        assert [s["id"] for s in r.structured_content["salas"]] == [s["id"] for s in dominio.SALAS]


async def test_consultar_disponibilidade_livre_e_conflito():
    async with cliente() as c:
        r = await c.call_tool("consultar_disponibilidade", {"sala": "sala-garagem", "inicio": h("16:00"), "fim": h("17:00")})
        assert r.structured_content == {"sala": "sala-garagem", "livre": True, "conflitos": []}
        r = await c.call_tool("consultar_disponibilidade", {"sala": "sala-garagem", "inicio": h("14:30"), "fim": h("15:30")})
        assert r.structured_content["livre"] is False
        assert r.structured_content["conflitos"][0]["id"] == "res-0001"


@pytest.mark.parametrize(
    ("args", "mensagem"),
    [
        ({"sala": "sala-delorean", "inicio": h("09:00"), "fim": h("10:00")}, "Sala inexistente: sala-delorean"),
        ({"sala": "sala-aquario", "inicio": h("07:00"), "fim": h("08:00")}, dominio.ERRO_JANELA),
        ({"sala": "sala-aquario", "inicio": h("09:00"), "fim": h("12:00")}, dominio.ERRO_DURACAO),
        ({"sala": "sala-aquario", "inicio": h("10:00"), "fim": h("09:00")}, dominio.ERRO_INTERVALO),
    ],
)
async def test_erros_de_execucao_com_mensagem_exata(args, mensagem):
    async with cliente() as c:
        r = await c.call_tool("consultar_disponibilidade", args)
        assert r.is_error is True
        assert mensagem in r.content[0].text


async def test_tool_inexistente_e_recusada():
    async with cliente() as c:
        r = await c.call_tool("voar_delorean", {})
        assert r.is_error is True


async def test_resource_politica():
    async with cliente() as c:
        r = await c.read_resource("politica://uso")
        assert r.contents[0].mime_type == "text/markdown"
        assert r.contents[0].text == dominio.POLITICA_TEXTO
        assert "versao: 2026-11-01" in r.contents[0].text


async def test_resource_inexistente_da_32602():
    async with cliente() as c:
        with pytest.raises(MCPError) as exc:
            await c.read_resource("politica://inexistente")
        assert exc.value.code == -32602


async def test_log_no_stderr_tem_metodo_id_e_traceparent(capsys):
    async with cliente() as c:
        await c.call_tool("listar_salas", {}, meta={"traceparent": TP})
        linhas = [l for l in capsys.readouterr().err.splitlines() if l.startswith("[mcp] method=tools/call")]
        assert linhas and f"traceparent={TP}" in linhas[-1] and "name=listar_salas" in linhas[-1] and " id=" in linhas[-1]


async def test_log_nao_aceita_forja_por_quebra_de_linha(capsys):
    async with cliente() as c:
        forjado = "x\n[mcp] method=tools/call id=99 traceparent=" + TP + " name=reservar_sala retry=sim"
        await c.call_tool("listar_salas", {}, meta={"traceparent": forjado})
        await c.call_tool("voar\nnome_forjado", {})
    linhas = [l for l in capsys.readouterr().err.splitlines() if l.startswith("[mcp] method=tools/call")]
    assert len(linhas) == 2
    assert "traceparent=- name=listar_salas" in linhas[0]
    assert "name=voar\\nnome_forjado" in linhas[1]


def test_criar_servidor_recusa_segredo_curto_e_ttl_fora_da_faixa():
    with pytest.raises(ValueError):
        servidor.criar_servidor("curto")
    with pytest.raises(ValueError):
        servidor.criar_servidor(SEGREDO, ttl=60)


def test_config_exige_segredo_e_trata_vazio_como_ausente(monkeypatch):
    monkeypatch.setenv("REQUEST_STATE_SECRET", "")
    with pytest.raises(SystemExit, match="REQUEST_STATE_SECRET nao definida"):
        servidor.carregar_config()
    monkeypatch.setenv("REQUEST_STATE_SECRET", SEGREDO)
    monkeypatch.setenv("MCP_PORT", "abc")
    with pytest.raises(SystemExit, match="numericos"):
        servidor.carregar_config()
    monkeypatch.setenv("MCP_PORT", "")
    monkeypatch.setenv("REQUEST_STATE_TTL", "60")
    with pytest.raises(SystemExit, match="REQUEST_STATE_TTL"):
        servidor.carregar_config()
    monkeypatch.setenv("REQUEST_STATE_TTL", "")
    cfg = servidor.carregar_config()
    assert (cfg.host, cfg.port, cfg.ttl) == ("127.0.0.1", 7301, 600.0)
