import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp_types import CallToolResult, ElicitResult, InputRequiredResult

import dominio
import servidor

SEGREDO = "s" * 32


def h(hora: str) -> str:
    return f"2026-11-03T{hora}:00-03:00"


def pedido(sala: str, inicio: str, fim: str, responsavel: str = "Teste") -> dict:
    return {"sala": sala, "inicio": h(inicio), "fim": h(fim), "responsavel": responsavel}


@pytest.fixture(autouse=True)
def reservas_limpas():
    dominio.reiniciar_reservas()
    yield
    dominio.reiniciar_reservas()


async def _nunca(*args, **kwargs):
    raise AssertionError("o transporte 2026-07-28 nao tem canal de volta; o callback nao pode rodar")


def cliente(com_elicitation: bool = True, servidor_mcp=None) -> Client:
    srv = servidor_mcp or servidor.criar_servidor(SEGREDO)
    return Client(srv, mode="2026-07-28", elicitation_callback=_nunca if com_elicitation else None)


async def reservar(c: Client, args: dict, **kw):
    return await c.session.call_tool("reservar_sala", args, allow_input_required=True, **kw)


def pausa(resultado) -> tuple[str, list[str], str]:
    assert isinstance(resultado, InputRequiredResult)
    assert len(resultado.input_requests) == 1
    chave, req = next(iter(resultado.input_requests.items()))
    assert req.method == "elicitation/create"
    assert req.params.mode == "form"
    assert req.params.message == servidor.MENSAGEM_ESCOLHA
    campo = req.params.requested_schema["properties"]["sala"]
    enum = campo.get("enum") or [campo["const"]]
    assert req.params.requested_schema["required"] == ["sala"]
    assert resultado.request_state
    return chave, enum, resultado.request_state


async def test_tools_list_tem_reservar_sala_sem_o_parametro_resolvido():
    async with cliente() as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert set(tools) == {"listar_salas", "consultar_disponibilidade", "reservar_sala"}
        assert set(tools["reservar_sala"].input_schema["properties"]) == {"sala", "inicio", "fim", "responsavel"}
        assert tools["reservar_sala"].output_schema["properties"].keys() >= {"reserva", "reservado", "politica", "motivo"}


async def test_caminho_feliz_cria_reserva_visivel():
    async with cliente() as c:
        r = await reservar(c, pedido("sala-aquario", "09:00", "10:00", "Doc"))
        assert isinstance(r, CallToolResult) and not r.is_error and r.result_type == "complete"
        assert r.structured_content == {
            "reserva": "res-0003", "reservado": True, "sala": "sala-aquario", "inicio": h("09:00"),
            "fim": h("10:00"), "responsavel": "Doc", "politica": "2026-11-01", "motivo": None,
        }
        d = await c.call_tool("consultar_disponibilidade", {"sala": "sala-aquario", "inicio": h("09:30"), "fim": h("10:30")})
        assert d.structured_content["livre"] is False


async def test_conflito_devolve_input_required_com_enum_na_ordem():
    async with cliente() as c:
        r = await reservar(c, pedido("sala-garagem", "14:00", "15:00", "Marty"))
        chave, enum, estado = pausa(r)
        assert enum == ["sala-fusca", "sala-mirante"]
        assert chave.endswith(":escolha_de_sala")
        assert estado.startswith("v1.")


async def test_uma_alternativa_vira_const_ou_enum_unitario():
    async with cliente() as c:
        await reservar(c, pedido("sala-fusca", "14:00", "15:00"))
        r = await reservar(c, pedido("sala-garagem", "14:00", "15:00"))
        _, enum, _ = pausa(r)
        assert enum == ["sala-mirante"]
        campo = next(iter(r.input_requests.values())).params.requested_schema["properties"]["sala"]
        assert "enum" in campo or "const" in campo


async def test_retry_accept_conclui_na_sala_escolhida():
    async with cliente() as c:
        args = pedido("sala-garagem", "14:00", "15:00", "Marty")
        chave, enum, estado = pausa(await reservar(c, args))
        r = await reservar(c, args, input_responses={chave: ElicitResult(action="accept", content={"sala": "sala-fusca"})}, request_state=estado)
        assert isinstance(r, CallToolResult) and not r.is_error
        assert r.structured_content["sala"] == "sala-fusca" and r.structured_content["reservado"] is True
        assert r.structured_content["politica"] == "2026-11-01"


@pytest.mark.parametrize("acao", ["decline", "cancel"])
async def test_recusa_conclui_sem_reservar_e_sem_erro(acao):
    async with cliente() as c:
        args = pedido("sala-garagem", "14:00", "15:00")
        chave, _, estado = pausa(await reservar(c, args))
        r = await reservar(c, args, input_responses={chave: ElicitResult(action=acao)}, request_state=estado)
        assert isinstance(r, CallToolResult) and not r.is_error and r.result_type == "complete"
        assert r.structured_content["reservado"] is False and r.structured_content["motivo"] == "recusado"
        assert len(dominio.RESERVAS) == 2


async def test_sem_alternativas_e_erro_de_execucao():
    async with cliente() as c:
        await reservar(c, pedido("sala-mirante", "11:00", "12:00"))
        r = await reservar(c, pedido("sala-mirante", "11:00", "12:00"))
        assert isinstance(r, CallToolResult) and r.is_error
        assert dominio.ERRO_SEM_ALTERNATIVA in r.content[0].text


async def test_erros_de_validacao_na_reserva():
    async with cliente() as c:
        r = await reservar(c, pedido("sala-delorean", "09:00", "10:00"))
        assert r.is_error and "Sala inexistente: sala-delorean" in r.content[0].text
        r = await reservar(c, pedido("sala-garagem", "14:00", "15:00", "   "))
        assert r.is_error and dominio.ERRO_RESPONSAVEL in r.content[0].text  # antes de qualquer pausa


async def test_schema_da_elicitation_tem_descricao_como_no_wire_03():
    async with cliente() as c:
        r = await reservar(c, pedido("sala-garagem", "14:00", "15:00"))
        campo = next(iter(r.input_requests.values())).params.requested_schema["properties"]["sala"]
        assert campo["description"] == "Sala alternativa escolhida"
        assert campo["type"] == "string"


async def test_request_state_adulterado_e_rejeitado_com_32602():
    async with cliente() as c:
        args = pedido("sala-garagem", "14:00", "15:00")
        chave, _, estado = pausa(await reservar(c, args))
        adulterado = estado[:-6] + ("AAAAAA" if not estado.endswith("AAAAAA") else "BBBBBB")
        with pytest.raises(MCPError) as exc:
            await reservar(c, args, input_responses={chave: ElicitResult(action="accept", content={"sala": "sala-fusca"})}, request_state=adulterado)
        assert exc.value.code == -32602


async def test_argumentos_adulterados_no_retry_nao_tomam_efeito():
    async with cliente() as c:
        chave, _, estado = pausa(await reservar(c, pedido("sala-garagem", "14:00", "15:00", "Doc")))
        with pytest.raises(MCPError) as exc:
            await reservar(c, pedido("sala-mirante", "13:00", "14:00", "Biff"), input_responses={chave: ElicitResult(action="accept", content={"sala": "sala-fusca"})}, request_state=estado)
        assert exc.value.code == -32602
        assert len(dominio.RESERVAS) == 2


async def test_escolha_fora_do_enum_no_retry_e_erro_de_execucao():
    async with cliente() as c:
        args = pedido("sala-garagem", "14:00", "15:00")
        chave, _, estado = pausa(await reservar(c, args))
        r = await reservar(c, args, input_responses={chave: ElicitResult(action="accept", content={"sala": "sala-aquario"})}, request_state=estado)
        assert isinstance(r, CallToolResult) and r.is_error
        assert len(dominio.RESERVAS) == 2


async def test_sem_capability_de_elicitation_da_32021():
    async with cliente(com_elicitation=False) as c:
        with pytest.raises(MCPError) as exc:
            await reservar(c, pedido("sala-garagem", "14:00", "15:00"))
        assert exc.value.code == -32021
        assert exc.value.data["requiredCapabilities"] == {"elicitation": {"form": {}}}
        # sem conflito nao ha pergunta, logo nao ha exigencia de capability
        r = await reservar(c, pedido("sala-aquario", "09:00", "10:00"))
        assert isinstance(r, CallToolResult) and not r.is_error


async def test_duas_pausas_simultaneas_concluem_cada_uma_a_sua():
    async with cliente() as c:
        a = pedido("sala-fusca", "16:00", "17:00", "Lorraine")
        b = pedido("sala-garagem", "14:00", "15:00", "George")
        ca, _, ea = pausa(await reservar(c, a))
        cb, _, eb = pausa(await reservar(c, b))
        ra = await reservar(c, a, input_responses={ca: ElicitResult(action="accept", content={"sala": "sala-mirante"})}, request_state=ea)
        rb = await reservar(c, b, input_responses={cb: ElicitResult(action="accept", content={"sala": "sala-mirante"})}, request_state=eb)
        assert ra.structured_content["inicio"] == h("16:00") and rb.structured_content["inicio"] == h("14:00")
        assert ra.structured_content["reserva"] != rb.structured_content["reserva"]


async def test_request_state_sobrevive_a_outro_processo_com_o_mesmo_segredo():
    args = pedido("sala-garagem", "14:00", "15:00", "Marty")
    async with cliente() as c:
        chave, _, estado = pausa(await reservar(c, args))
    # "reinicio": servidor novo, mesmo segredo, reservas recarregadas
    dominio.reiniciar_reservas()
    async with cliente(servidor_mcp=servidor.criar_servidor(SEGREDO)) as c:
        r = await reservar(c, args, input_responses={chave: ElicitResult(action="accept", content={"sala": "sala-fusca"})}, request_state=estado)
        assert isinstance(r, CallToolResult) and r.structured_content["sala"] == "sala-fusca"
    async with cliente(servidor_mcp=servidor.criar_servidor("o" * 32)) as c:
        with pytest.raises(MCPError) as exc:
            await reservar(c, args, input_responses={chave: ElicitResult(action="accept", content={"sala": "sala-fusca"})}, request_state=estado)
        assert exc.value.code == -32602


async def test_pergunta_que_mudou_entre_a_pausa_e_o_retry_e_refeita():
    async with cliente() as c:
        args = pedido("sala-garagem", "14:00", "15:00", "Marty")
        chave, enum, estado = pausa(await reservar(c, args))
        assert enum == ["sala-fusca", "sala-mirante"]
        await reservar(c, pedido("sala-fusca", "14:00", "15:00", "Outro"))  # ocupa a primeira alternativa
        r = await reservar(c, args, input_responses={chave: ElicitResult(action="accept", content={"sala": "sala-fusca"})}, request_state=estado)
        _, enum2, _ = pausa(r)
        assert enum2 == ["sala-mirante"]
