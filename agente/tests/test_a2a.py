import json

import httpx2
import pytest
from mcp.shared.exceptions import MCPError
from mcp_types import CallToolResult, InputRequiredResult, TextContent

import servidor_a2a as a2a
import agente
import tarefas
from servidor_a2a import ServidorA2A
from tarefas import Store

TP = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
PEDIDO = "reservar sala=sala-porao inicio=2026-11-03T09:00:00-03:00 fim=2026-11-03T10:00:00-03:00 responsavel=Doc"


def reserva_ok(sala="sala-porao", rid="res-0003") -> CallToolResult:
    dados = {"reserva": rid, "reservado": True, "sala": sala, "inicio": "2026-11-03T09:00:00-03:00", "fim": "2026-11-03T10:00:00-03:00", "responsavel": "Doc", "politica": "2026-11-01", "motivo": None}
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(dados))], structured_content=dados, is_error=False)


def erro_tool(texto: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=texto)], is_error=True)


class HostFalso:
    """Dublê do HostMCP: devolve resultados enfileirados e registra as chamadas."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas: list[dict] = []
        self.versao_politica = "2026-11-01"

    async def abrir(self):
        pass

    async def fechar(self):
        pass

    async def preparar(self, traceparent=None):
        pass

    async def reservar(self, argumentos, traceparent=None, *, input_responses=None, request_state=None):
        self.chamadas.append({"args": argumentos, "traceparent": traceparent, "input_responses": input_responses, "request_state": request_state})
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def servidor(*respostas) -> tuple[ServidorA2A, HostFalso]:
    host = HostFalso(*respostas)
    return ServidorA2A(host, Store(), "http://127.0.0.1:7300/a2a"), host


def rpc(metodo: str, params: dict, req_id="1") -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "method": metodo, "params": params}


def enviar(texto: str, task_id: str | None = None, message_id: str = "msg-1") -> dict:
    mensagem: dict = {"messageId": message_id, "role": "ROLE_USER", "parts": [{"text": texto}]}
    if task_id:
        mensagem["taskId"] = task_id
    return rpc("SendMessage", {"message": mensagem})


def test_agent_card_segue_o_wire_07():
    card = a2a.agent_card("http://127.0.0.1:7300/a2a")
    from pathlib import Path

    wire = Path(__file__).resolve().parents[2] / "exemplos" / "wire" / "07-a2a-agent-card.json"
    esperado = json.loads(wire.read_text())["response"]["body"]
    assert card == esperado


def test_interpretar_pedido_formato_fixo():
    assert a2a.interpretar_pedido(PEDIDO) == {"sala": "sala-porao", "inicio": "2026-11-03T09:00:00-03:00", "fim": "2026-11-03T10:00:00-03:00", "responsavel": "Doc"}
    assert a2a.interpretar_pedido("reservar sala=a inicio=b fim=c responsavel=Emmett Brown")["responsavel"] == "Emmett Brown"
    for ruim in ("reservar sala=a", "escolha=sala-fusca", "", "reservar inicio=b sala=a fim=c responsavel=d"):
        with pytest.raises(a2a.ErroA2A) as exc:
            a2a.interpretar_pedido(ruim)
        assert exc.value.code == -32602


async def test_send_message_sala_livre_conclui_com_artifact():
    srv, host = servidor(reserva_ok())
    resposta = await srv.tratar(enviar(PEDIDO), {"traceparent": TP})
    task = resposta["result"]["task"]
    assert task["status"]["state"] == tarefas.COMPLETED
    assert task["id"].startswith("task-") and task["contextId"].startswith("ctx-")
    assert task["artifacts"][0]["name"] == "reserva"
    conteudo = json.loads(task["artifacts"][0]["parts"][0]["text"])
    assert conteudo == {"reserva": "res-0003", "sala": "sala-porao", "inicio": "2026-11-03T09:00:00-03:00", "fim": "2026-11-03T10:00:00-03:00", "responsavel": "Doc", "politica": "2026-11-01"}
    assert task["status"]["message"]["parts"][0]["text"] == "Reserva res-0003 confirmada na sala-porao."
    assert [m["role"] for m in task["history"]] == ["ROLE_USER", "ROLE_AGENT"]
    assert task["history"][0]["messageId"] == "msg-1" and task["history"][0]["taskId"] == task["id"]
    assert host.chamadas[0]["args"]["sala"] == "sala-porao" and host.chamadas[0]["traceparent"] == TP
    assert "requestState" not in json.dumps(resposta)


async def test_get_task_reflete_a_task():
    srv, _ = servidor(reserva_ok())
    criada = (await srv.tratar(enviar(PEDIDO), {}))["result"]["task"]
    lida = (await srv.tratar(rpc("GetTask", {"id": criada["id"]}), {}))["result"]["task"]
    assert lida == criada
    erro = (await srv.tratar(rpc("GetTask", {"id": "task-inexistente"}), {}))["error"]
    assert erro["code"] == -32001


async def test_task_terminal_recusa_nova_mensagem():
    srv, _ = servidor(reserva_ok())
    criada = (await srv.tratar(enviar(PEDIDO), {}))["result"]["task"]
    resposta = await srv.tratar(enviar("escolha=sala-fusca", task_id=criada["id"]), {})
    assert resposta["error"]["code"] == -32004
    assert (await srv.tratar(enviar("escolha=x", task_id="task-nao-existe"), {}))["error"]["code"] == -32001


async def test_erro_de_execucao_da_tool_vira_failed_com_a_mensagem_exata():
    srv, _ = servidor(erro_tool("Error executing tool reservar_sala: Sala inexistente: sala-delorean"))
    task = (await srv.tratar(enviar(PEDIDO.replace("sala-porao", "sala-delorean")), {}))["result"]["task"]
    assert task["status"]["state"] == tarefas.FAILED
    assert "Sala inexistente: sala-delorean" in task["status"]["message"]["parts"][0]["text"]
    assert any("Sala inexistente: sala-delorean" in m["parts"][0]["text"] for m in task["history"])
    assert task["artifacts"] == []


async def test_recusa_vira_canceled():
    dados = {"reserva": None, "reservado": False, "motivo": "recusado"}
    srv, _ = servidor(CallToolResult(content=[TextContent(type="text", text="{}")], structured_content=dados, is_error=False))
    task = (await srv.tratar(enviar(PEDIDO), {}))["result"]["task"]
    assert task["status"]["state"] == tarefas.CANCELED


async def test_erros_de_transporte_protocolo_e_inesperados_viram_failed(capsys):
    srv, _ = servidor(MCPError(code=-32602, message="Invalid or expired requestState"), httpx2.ConnectError("127.0.0.1:7301 down"), TimeoutError("lento"))
    t1 = (await srv.tratar(enviar(PEDIDO), {}))["result"]["task"]
    t2 = (await srv.tratar(enviar(PEDIDO), {}))["result"]["task"]
    t3 = (await srv.tratar(enviar(PEDIDO), {}))["result"]["task"]
    assert t1["status"]["state"] == tarefas.FAILED and "erro MCP -32602" in t1["status"]["message"]["parts"][0]["text"]
    assert "requestState" not in json.dumps(t1)  # texto do servidor fica so no log
    assert t2["status"]["state"] == tarefas.FAILED and t2["status"]["message"]["parts"][0]["text"] == "Servidor de salas indisponivel."
    assert "7301" not in json.dumps(t2)  # topologia interna nao vaza para o cliente
    assert t3["status"]["state"] == tarefas.FAILED and t3["status"]["message"]["parts"][0]["text"] == "Erro interno do agente"
    log = capsys.readouterr().err
    assert f"task={t2['id']} estado=TASK_STATE_FAILED" in log and "7301" in log and "TimeoutError" in log


async def test_cancelamento_durante_a_chamada_mcp_nao_deixa_task_em_working():
    import asyncio

    class HostLento(HostFalso):
        async def reservar(self, *a, **k):
            await asyncio.sleep(10)

    srv = ServidorA2A(HostLento(), Store(), "http://127.0.0.1:7300/a2a")
    tarefa_async = asyncio.create_task(srv.tratar(enviar(PEDIDO), {}))
    await asyncio.sleep(0.05)
    tarefa_async.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa_async
    (task,) = srv.store._tarefas.values()
    assert task.estado == tarefas.FAILED


async def test_pedido_invalido_nao_abre_task():
    srv, host = servidor()
    resposta = await srv.tratar(enviar("me reserva uma sala ai"), {})
    assert resposta["error"]["code"] == -32602 and len(srv.store) == 0 and host.chamadas == []


async def test_envelopes_invalidos():
    srv, _ = servidor()
    assert (await srv.tratar(None, {}))["error"]["code"] == -32700
    assert (await srv.tratar({"jsonrpc": "1.0", "id": 1, "method": "SendMessage"}, {}))["error"]["code"] == -32600
    assert (await srv.tratar(rpc("SendStreamingMessage", {}), {}))["error"]["code"] == -32601
    assert (await srv.tratar(rpc("SendMessage", {"message": {"parts": []}}), {}))["error"]["code"] == -32602
    assert (await srv.tratar({"jsonrpc": "2.0", "id": 7, "method": "GetTask", "params": []}, {}))["error"]["code"] == -32602


async def test_context_id_do_cliente_e_respeitado_e_validado_na_continuacao():
    srv, _ = servidor(reserva_ok())
    corpo = enviar(PEDIDO)
    corpo["params"]["message"]["contextId"] = "ctx-do-cliente"
    task = (await srv.tratar(corpo, {}))["result"]["task"]
    assert task["contextId"] == "ctx-do-cliente"
    continuacao = enviar("escolha=x", task_id=task["id"])
    continuacao["params"]["message"]["contextId"] = "ctx-outro"
    assert (await srv.tratar(continuacao, {}))["error"]["code"] == -32602


def test_store_expurga_terminais_antigas_ao_atingir_o_teto():
    store = Store(teto=3)
    antigas = [store.criar() for _ in range(3)]
    for t in antigas:
        t.transitar(tarefas.WORKING)
        t.transitar(tarefas.COMPLETED)
    nova = store.criar()
    assert len(store) == 3 and store.obter(antigas[0].id) is None and store.obter(nova.id) is nova
    # tasks nao terminais nunca sao expurgadas: com o store cheio de vivas, criar recusa
    store2 = Store(teto=1)
    viva = store2.criar()
    with pytest.raises(tarefas.StoreCheio):
        store2.criar()
    assert store2.obter(viva.id) is viva


async def test_traceparent_invalido_e_ignorado():
    srv, host = servidor(reserva_ok())
    await srv.tratar(enviar(PEDIDO), {"Traceparent": "lixo"})
    assert host.chamadas[0]["traceparent"] is None


async def test_app_http_responde_card_e_rpc():
    host = HostFalso(reserva_ok())
    app = agente.criar_app(host, "http://127.0.0.1:7300/a2a")
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://agente") as c:
        card = await c.get("/.well-known/agent-card.json")
        assert card.status_code == 200 and card.json()["skills"][0]["id"] == "reservar-sala"
        r = await c.post("/a2a", json=enviar(PEDIDO), headers={"traceparent": TP})
        assert r.status_code == 200 and r.json()["result"]["task"]["status"]["state"] == tarefas.COMPLETED
        r = await c.post("/a2a", content=b"{nao e json", headers={"content-type": "application/json"})
        assert r.json()["error"]["code"] == -32700
        r = await c.post("/a2a", content=b"x" * (agente.LIMITE_DO_CORPO + 1), headers={"content-type": "application/json"})
        assert r.status_code == 413 and r.json()["error"]["code"] == -32600
        r = await c.post("/a2a", content=b"[" * 50_000, headers={"content-type": "application/json"})
        assert r.status_code == 200 and r.json()["error"]["code"] == -32700  # RecursionError nao vira 500


def test_config_do_agente(monkeypatch):
    monkeypatch.setenv("AGENTE_PORT", "abc")
    with pytest.raises(SystemExit):
        agente.carregar_config()
    monkeypatch.setenv("AGENTE_PORT", "")
    cfg = agente.carregar_config()
    assert (cfg.port, cfg.mcp_url, cfg.url_publica) == (7300, "http://127.0.0.1:7301/mcp", "http://127.0.0.1:7300/a2a")
