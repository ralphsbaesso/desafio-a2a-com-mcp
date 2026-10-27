import json

import pytest
from mcp_types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult

import ponte
import tarefas
from servidor_a2a import ServidorA2A
from tarefas import Store
from test_a2a import TP, HostFalso, enviar, erro_tool, reserva_ok, rpc

CHAVE = "__main__:escolha_de_sala"
PEDIDO_GARAGEM = "reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00 fim=2026-11-03T15:00:00-03:00 responsavel=Marty"


def input_required(alternativas=("sala-fusca", "sala-mirante"), estado="v1.ESTADO-OPACO-A", chave=CHAVE, const=False) -> InputRequiredResult:
    campo = {"type": "string", "description": "Sala alternativa escolhida"}
    if const:
        campo["const"] = alternativas[0]
    else:
        campo["enum"] = list(alternativas)
    schema = {"type": "object", "properties": {"sala": campo}, "required": ["sala"]}
    req = ElicitRequest(params=ElicitRequestFormParams(message="A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa.", requested_schema=schema))
    return InputRequiredResult(input_requests={chave: req}, request_state=estado)


def servidor(*respostas, **kw):
    host = HostFalso(*respostas)
    return ServidorA2A(host, Store(**kw), "http://127.0.0.1:7300/a2a"), host


def texto_status(task: dict) -> str:
    return task["status"]["message"]["parts"][0]["text"]


async def test_pausa_guarda_pendencia_e_devolve_a_linha_exata():
    srv, host = servidor(input_required())
    resposta = await srv.tratar(enviar(PEDIDO_GARAGEM), {"traceparent": TP})
    task = resposta["result"]["task"]
    assert task["status"]["state"] == tarefas.INPUT_REQUIRED
    assert texto_status(task) == "alternativas: sala-fusca, sala-mirante"
    assert task["history"][-1]["parts"][0]["text"] == "alternativas: sala-fusca, sala-mirante"
    assert task["artifacts"] == []
    bruto = json.dumps(resposta)
    assert "ESTADO-OPACO" not in bruto and "requestState" not in bruto and CHAVE not in bruto
    interna = srv.store.obter(task["id"])
    assert interna.pendencia.request_state == "v1.ESTADO-OPACO-A" and interna.pendencia.chave == CHAVE
    lido = (await srv.tratar(rpc("GetTask", {"id": task["id"]}), {}))
    assert "ESTADO-OPACO" not in json.dumps(lido) and lido["result"]["task"]["status"]["state"] == tarefas.INPUT_REQUIRED


async def test_retomada_aceita_ecoa_estado_e_conclui_na_sala_escolhida():
    srv, host = servidor(input_required(), reserva_ok(sala="sala-fusca", rid="res-0004"))
    task = (await srv.tratar(enviar(PEDIDO_GARAGEM), {"traceparent": TP}))["result"]["task"]
    resposta = await srv.tratar(enviar("escolha=sala-fusca", task_id=task["id"], message_id="msg-2"), {"traceparent": TP})
    concluida = resposta["result"]["task"]
    assert concluida["status"]["state"] == tarefas.COMPLETED
    assert json.loads(concluida["artifacts"][0]["parts"][0]["text"])["sala"] == "sala-fusca"
    retry = host.chamadas[1]
    assert retry["request_state"] == "v1.ESTADO-OPACO-A"
    assert retry["input_responses"][CHAVE].action == "accept" and retry["input_responses"][CHAVE].content == {"sala": "sala-fusca"}
    assert retry["args"] == host.chamadas[0]["args"]  # mesmos argumentos do pedido original
    assert retry["traceparent"] == TP
    assert [m["parts"][0]["text"] for m in concluida["history"]][2] == "escolha=sala-fusca"
    assert "ESTADO-OPACO" not in json.dumps(resposta)
    assert srv.store.obter(task["id"]).pendencia is None


async def test_recusa_vira_decline_e_canceled():
    dados = {"reserva": None, "reservado": False, "motivo": "recusado"}
    from mcp_types import CallToolResult, TextContent

    srv, host = servidor(input_required(), CallToolResult(content=[TextContent(type="text", text="{}")], structured_content=dados, is_error=False))
    task = (await srv.tratar(enviar(PEDIDO_GARAGEM), {}))["result"]["task"]
    resposta = await srv.tratar(enviar("escolha=recusar", task_id=task["id"]), {})
    assert resposta["result"]["task"]["status"]["state"] == tarefas.CANCELED
    assert host.chamadas[1]["input_responses"][CHAVE].action == "decline"


async def test_escolha_fora_do_enum_mantem_pausada_e_repete_a_lista():
    srv, host = servidor(input_required())
    task = (await srv.tratar(enviar(PEDIDO_GARAGEM), {}))["result"]["task"]
    for texto in ("escolha=sala-aquario", "quero a fusca", "escolha=", "escolha=sala-fusca extra"):
        resposta = await srv.tratar(enviar(texto, task_id=task["id"]), {})
        t = resposta["result"]["task"]
        assert t["status"]["state"] == tarefas.INPUT_REQUIRED
        assert texto_status(t) == "alternativas: sala-fusca, sala-mirante"
    assert len(host.chamadas) == 1  # nenhum retry foi feito
    assert srv.store.obter(task["id"]).pendencia.request_state == "v1.ESTADO-OPACO-A"


async def test_const_com_uma_alternativa():
    srv, _ = servidor(input_required(("sala-mirante",), const=True))
    task = (await srv.tratar(enviar(PEDIDO_GARAGEM), {}))["result"]["task"]
    assert texto_status(task) == "alternativas: sala-mirante"


async def test_duas_tasks_pausadas_nao_trocam_de_request_state():
    srv, host = servidor(input_required(estado="v1.A"), input_required(estado="v1.B"), reserva_ok(sala="sala-mirante", rid="res-0005"), reserva_ok(sala="sala-mirante", rid="res-0006"))
    a = (await srv.tratar(enviar("reservar sala=sala-fusca inicio=2026-11-03T16:00:00-03:00 fim=2026-11-03T17:00:00-03:00 responsavel=Lorraine"), {}))["result"]["task"]
    b = (await srv.tratar(enviar(PEDIDO_GARAGEM), {}))["result"]["task"]
    ra = (await srv.tratar(enviar("escolha=sala-mirante", task_id=a["id"]), {}))["result"]["task"]
    rb = (await srv.tratar(enviar("escolha=sala-mirante", task_id=b["id"]), {}))["result"]["task"]
    assert ra["status"]["state"] == rb["status"]["state"] == tarefas.COMPLETED
    assert host.chamadas[2]["request_state"] == "v1.A" and host.chamadas[3]["request_state"] == "v1.B"
    assert host.chamadas[2]["args"]["sala"] == "sala-fusca" and host.chamadas[3]["args"]["sala"] == "sala-garagem"


async def test_novo_input_required_no_retry_repausa_com_a_lista_nova():
    srv, host = servidor(input_required(), input_required(("sala-mirante",), estado="v1.NOVO"), reserva_ok(sala="sala-mirante"))
    task = (await srv.tratar(enviar(PEDIDO_GARAGEM), {}))["result"]["task"]
    t = (await srv.tratar(enviar("escolha=sala-fusca", task_id=task["id"]), {}))["result"]["task"]
    assert t["status"]["state"] == tarefas.INPUT_REQUIRED and texto_status(t) == "alternativas: sala-mirante"
    assert srv.store.obter(task["id"]).pendencia.request_state == "v1.NOVO"
    t = (await srv.tratar(enviar("escolha=sala-mirante", task_id=task["id"]), {}))["result"]["task"]
    assert t["status"]["state"] == tarefas.COMPLETED and host.chamadas[2]["request_state"] == "v1.NOVO"


async def test_erro_no_retry_vira_failed_e_task_terminal_recusa_depois():
    srv, _ = servidor(input_required(), erro_tool("Error executing tool reservar_sala: Sala ocupada: o intervalo foi reservado por outro pedido antes de concluir"))
    task = (await srv.tratar(enviar(PEDIDO_GARAGEM), {}))["result"]["task"]
    t = (await srv.tratar(enviar("escolha=sala-fusca", task_id=task["id"]), {}))["result"]["task"]
    assert t["status"]["state"] == tarefas.FAILED and "Sala ocupada" in texto_status(t)
    assert (await srv.tratar(enviar("escolha=sala-mirante", task_id=task["id"]), {}))["error"]["code"] == -32004


async def test_input_required_malformado_vira_failed_sem_vazar():
    sem_estado = InputRequiredResult(input_requests=input_required().input_requests, request_state=None)
    duas = InputRequiredResult(input_requests={**input_required().input_requests, "outra": input_required(chave="outra").input_requests["outra"]}, request_state="v1.X")
    srv, _ = servidor(sem_estado, duas)
    for _ in range(2):
        t = (await srv.tratar(enviar(PEDIDO_GARAGEM), {}))["result"]["task"]
        assert t["status"]["state"] == tarefas.FAILED and texto_status(t).startswith("Resposta MCP inesperada")


async def test_continuacoes_concorrentes_so_uma_faz_o_retry():
    import asyncio

    class HostLento(HostFalso):
        async def reservar(self, *a, **k):
            await asyncio.sleep(0.05)
            return await super().reservar(*a, **k)

    host = HostLento(input_required(), reserva_ok(sala="sala-fusca"))
    srv = ServidorA2A(host, Store(), "http://127.0.0.1:7300/a2a")
    task = (await srv.tratar(enviar(PEDIDO_GARAGEM), {}))["result"]["task"]
    r1, r2 = await asyncio.gather(
        srv.tratar(enviar("escolha=sala-fusca", task_id=task["id"]), {}),
        srv.tratar(enviar("escolha=sala-mirante", task_id=task["id"]), {}),
    )
    estados = sorted(("result" in r1, "result" in r2))
    assert estados == [False, True]
    erro = r1.get("error") or r2.get("error")
    assert erro["code"] == -32004 and len(host.chamadas) == 2


async def test_pausa_expira_por_ttl_tambem_no_get_task(capsys):
    srv, _ = servidor(input_required(), ttl_pausa=0.0)
    task = (await srv.tratar(enviar(PEDIDO_GARAGEM), {}))["result"]["task"]
    interna = srv.store.obter(task["id"])
    interna.pausada_em -= 1
    lida = (await srv.tratar(rpc("GetTask", {"id": task["id"]}), {}))["result"]["task"]
    assert lida["status"]["state"] == tarefas.FAILED and "Pausa expirada" in texto_status(lida)
    assert interna.pendencia is None
    assert f"task={task['id']} estado=TASK_STATE_FAILED" in capsys.readouterr().err
    resposta = await srv.tratar(enviar("escolha=sala-fusca", task_id=task["id"]), {})
    assert resposta["error"]["code"] == -32004


async def test_escolha_invalida_renova_o_ttl():
    srv, _ = servidor(input_required(), ttl_pausa=10.0)
    task = (await srv.tratar(enviar(PEDIDO_GARAGEM), {}))["result"]["task"]
    interna = srv.store.obter(task["id"])
    interna.pausada_em -= 9
    t = (await srv.tratar(enviar("escolha=errada", task_id=task["id"]), {}))["result"]["task"]
    assert t["status"]["state"] == tarefas.INPUT_REQUIRED and not interna.pausa_expirada(10.0)


def test_store_expira_pausadas_ao_atingir_o_teto():
    store = Store(teto=2, ttl_pausa=0.0)
    antigas = [store.criar() for _ in range(2)]
    for t in antigas:
        t.transitar(tarefas.WORKING)
        t.marcar_pausa()
        t.pausada_em -= 1
        t.transitar(tarefas.INPUT_REQUIRED)
    store.criar()
    assert len(store) == 2 and all(t.estado == tarefas.FAILED for t in antigas if store.obter(t.id))


async def test_muitas_escolhas_invalidas_terminam_a_task(capsys):
    srv, host = servidor(input_required())
    task = (await srv.tratar(enviar(PEDIDO_GARAGEM), {}))["result"]["task"]
    estado = None
    for i in range(tarefas.MAX_ESCOLHAS_INVALIDAS):
        estado = (await srv.tratar(enviar("escolha=" + "x" * 5000, task_id=task["id"]), {}))["result"]["task"]["status"]["state"]
    assert estado == tarefas.FAILED and len(host.chamadas) == 1
    assert all(len(l) < 400 for l in capsys.readouterr().err.splitlines() if "escolha invalida" in l)


async def test_alternativas_invalidas_do_servidor_viram_falha_controlada():
    srv, _ = servidor(input_required(("Sala A", "sala-b")), input_required(("recusar",)))
    for _ in range(2):
        t = (await srv.tratar(enviar(PEDIDO_GARAGEM), {}))["result"]["task"]
        assert t["status"]["state"] == tarefas.FAILED and texto_status(t).startswith("Resposta MCP inesperada")


async def test_store_cheio_de_tasks_vivas_recusa_com_erro_claro():
    srv, _ = servidor(input_required(), input_required(), teto=1)
    assert "result" in await srv.tratar(enviar(PEDIDO_GARAGEM), {})
    resposta = await srv.tratar(enviar(PEDIDO_GARAGEM), {})
    assert resposta["error"]["code"] == -32603 and "capacidade" in resposta["error"]["message"]


async def test_pausas_encadeadas_tem_teto(capsys):
    srv, host = servidor(*[input_required(estado=f"v1.{i}") for i in range(tarefas.MAX_RODADAS + 1)])
    task = (await srv.tratar(enviar(PEDIDO_GARAGEM), {}))["result"]["task"]
    estado = task["status"]["state"]
    for _ in range(tarefas.MAX_RODADAS):
        estado = (await srv.tratar(enviar("escolha=sala-fusca", task_id=task["id"]), {}))["result"]["task"]["status"]["state"]
    assert estado == tarefas.FAILED and len(host.chamadas) == tarefas.MAX_RODADAS + 1


async def test_log_nao_aceita_quebra_de_linha_vinda_do_servidor(capsys):
    from mcp.shared.exceptions import MCPError

    srv, _ = servidor(MCPError(code=-32602, message="x\n[agente] task=forjada estado=TASK_STATE_COMPLETED"))
    await srv.tratar(enviar(PEDIDO_GARAGEM), {})
    linhas = [l for l in capsys.readouterr().err.splitlines() if l.startswith("[agente] task=")]
    assert len(linhas) == 1 and "forjada" not in linhas[0].split("interno=")[0]


def test_interpretar_escolha():
    assert ponte.interpretar_escolha(" escolha=sala-fusca ") == "sala-fusca"
    assert ponte.interpretar_escolha("escolha=recusar") == "recusar"
    assert ponte.interpretar_escolha("sala-fusca") is None
    assert ponte.interpretar_escolha("escolha=a b") is None
