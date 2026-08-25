"""Testes do `nfse-doctor`.

O critério de sucesso do v0.1.0 pede código de saída distinto para cada causa, para
que script de implantação decida sem parsear texto. É isso que este arquivo trava:
cada cenário de falha, e o número que sai dele.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock

from nfse_sefin.ambientes import Ambiente, bases_de
from nfse_sefin.doctor import CodigoSaida, main
from tests.conftest import PfxGerado

BASES = bases_de(Ambiente.PRODUCAO_RESTRITA)
MUNICIPIO = "3304557"
URL_CONVENIO = f"{BASES.adn_parametrizacao}/{MUNICIPIO}/convenio"
URL_MANUAL = f"{BASES.adn_parametrizacao}/parametros_municipais/{MUNICIPIO}/convenio"


@pytest.fixture
def sem_contexto_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evita a ida da chave privada ao disco em cada teste de CLI.

    O que `ssl_context()` faz já é testado em `test_cert.py`; aqui interessa o fluxo
    do comando, não a montagem do contexto.
    """
    import ssl

    from nfse_sefin.cert import Certificate

    monkeypatch.setattr(Certificate, "ssl_context", lambda self: ssl.create_default_context())


def _pfx_em_disco(pfx: PfxGerado, tmp_path: Path) -> Path:
    caminho = tmp_path / "empresa.pfx"
    caminho.write_bytes(pfx.blob)
    return caminho


def _rodar(*args: str) -> tuple[int, str]:
    buffer = io.StringIO()
    codigo = main(list(args), saida=buffer)
    return codigo, buffer.getvalue()


# ------------------------------------------------------------- argumentos


def test_certificado_inexistente(tmp_path: Path) -> None:
    codigo, texto = _rodar("--pfx", str(tmp_path / "nao-existe.pfx"), "--municipio", MUNICIPIO)

    assert codigo == CodigoSaida.ARGUMENTO_INVALIDO
    assert "não encontrado" in texto


def test_municipio_com_formato_errado(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None
) -> None:
    """Falha offline, sem gastar uma requisição para descobrir (P7)."""
    caminho = _pfx_em_disco(pfx_valido, tmp_path)

    codigo, texto = _rodar(
        "--pfx", str(caminho), "--municipio", "330455", "--senha", pfx_valido.senha
    )

    assert codigo == CodigoSaida.ARGUMENTO_INVALIDO
    assert "7 dígitos" in texto


# ------------------------------------------------------------ certificado


def test_senha_errada_devolve_pkcs12_ilegivel(pfx_valido: PfxGerado, tmp_path: Path) -> None:
    caminho = _pfx_em_disco(pfx_valido, tmp_path)

    codigo, texto = _rodar("--pfx", str(caminho), "--municipio", MUNICIPIO, "--senha", "errada")

    assert codigo == CodigoSaida.PKCS12_ILEGIVEL
    assert "openssl pkcs12" in texto, "a mensagem tem de dizer como confirmar"


def test_certificado_vencido(
    pfx_vencido: PfxGerado, tmp_path: Path, sem_contexto_tls: None
) -> None:
    caminho = _pfx_em_disco(pfx_vencido, tmp_path)

    codigo, texto = _rodar(
        "--pfx", str(caminho), "--municipio", MUNICIPIO, "--senha", pfx_vencido.senha
    )

    assert codigo == CodigoSaida.CERTIFICADO_INVALIDO
    assert "fora da validade" in texto


def test_certificado_vencendo_avisa_mas_segue(
    pfx_vencendo: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    """Avisar não é impedir: 10 dias de validade ainda emite nota."""
    caminho = _pfx_em_disco(pfx_vencendo, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={})

    codigo, texto = _rodar(
        "--pfx", str(caminho), "--municipio", MUNICIPIO, "--senha", pfx_vencendo.senha
    )

    assert codigo == CodigoSaida.SUCESSO
    assert "AVISO" in texto
    assert "vence em" in texto


# -------------------------------------------------------------- rede


def test_mtls_recusado(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    """Certificado recusado no handshake tem código próprio.

    É ação diferente de "servidor fora do ar", e a exceção de rede sozinha não separa
    os dois.
    """
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_exception(_erro_tls(), method="GET")

    codigo, texto = _rodar(
        "--pfx", str(caminho), "--municipio", MUNICIPIO, "--senha", pfx_valido.senha
    )

    assert codigo == CodigoSaida.MTLS_FALHOU
    assert "mTLS" in texto
    assert "ICP-Brasil" in texto, "o texto tem de dizer o que conferir"


def _erro_tls() -> httpx.ConnectError:
    """Um `ConnectError` com `SSLError` na cadeia, que é como o mTLS recusado chega."""
    import ssl

    erro = httpx.ConnectError("falha ao conectar")
    erro.__cause__ = ssl.SSLError("certificate verify failed")
    return erro


def test_doctor_nao_repete_requisicao(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    """Diagnóstico não faz retry, mesmo em GET.

    O transporte repete leitura por padrão, e isso está certo para uso normal. Aqui
    está errado por dois motivos: handshake recusado não melhora na segunda tentativa,
    e o retry troca a exceção original pela da última tentativa — que é exatamente a
    informação que este comando existe para dar. Sem contar os segundos de espera que
    um diagnóstico não deveria custar.
    """
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, status_code=503)

    codigo, _ = _rodar("--pfx", str(caminho), "--municipio", MUNICIPIO, "--senha", pfx_valido.senha)

    assert codigo != CodigoSaida.SUCESSO
    assert len(httpx_mock.get_requests()) == 1, "diagnóstico não deve repetir"


def test_municipio_nao_aderente(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, status_code=404)
    httpx_mock.add_response(method="GET", url=URL_MANUAL, status_code=404)

    codigo, texto = _rodar(
        "--pfx", str(caminho), "--municipio", MUNICIPIO, "--senha", pfx_valido.senha
    )

    assert codigo == CodigoSaida.MUNICIPIO_NAO_ADERENTE
    assert "não aderiu" in texto
    assert "sistema próprio" in texto, "o texto tem de dizer o que fazer em seguida"


# ------------------------------------------------------------- sucesso


def test_caminho_feliz(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={"qualquer": "coisa"})

    codigo, texto = _rodar(
        "--pfx", str(caminho), "--municipio", MUNICIPIO, "--senha", pfx_valido.senha
    )

    assert codigo == CodigoSaida.SUCESSO
    assert "certificado aberto" in texto
    assert "handshake mTLS fechou" in texto
    assert "aderiu ao Sistema Nacional" in texto
    assert "Tudo pronto para emitir" in texto
    assert pfx_valido.cn in texto


def test_reporta_qual_rota_de_convenio_respondeu(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    """O dado que decide qual fonte está certa sobre a rota.

    O manual e a implementação em produção discordam, e ninguém pode testar de mesa.
    Quem descobre é a ferramenta.
    """
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, status_code=404)
    httpx_mock.add_response(method="GET", url=URL_MANUAL, json={})

    _, texto = _rodar("--pfx", str(caminho), "--municipio", MUNICIPIO, "--senha", pfx_valido.senha)

    assert "rota de convênio que respondeu" in texto
    assert "parametros_municipais" in texto


def test_busca_de_servico(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    """A promessa do design: "o cTribNac do seu serviço é 010101"."""
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={})

    codigo, texto = _rodar(
        "--pfx",
        str(caminho),
        "--municipio",
        MUNICIPIO,
        "--senha",
        pfx_valido.senha,
        "--servico",
        "banho",
    )

    assert codigo == CodigoSaida.SUCESSO
    assert "cTribNac 060301" in texto


def test_servico_sem_correspondencia_apenas_avisa(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={})

    codigo, texto = _rodar(
        "--pfx",
        str(caminho),
        "--municipio",
        MUNICIPIO,
        "--senha",
        pfx_valido.senha,
        "--servico",
        "colonizacao de marte",
    )

    assert codigo == CodigoSaida.SUCESSO
    assert "nenhum serviço" in texto


def test_cifras_legadas_viram_aviso(
    tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock, pfx_valido: PfxGerado
) -> None:
    """Diagnóstico, não bloqueio: funciona aqui, pode não funcionar noutra build."""
    import subprocess

    origem = tmp_path / "origem.pfx"
    origem.write_bytes(pfx_valido.blob)
    pem = tmp_path / "par.pem"
    legado = tmp_path / "legado.pfx"

    subprocess.run(
        [
            "openssl",
            "pkcs12",
            "-in",
            str(origem),
            "-out",
            str(pem),
            "-nodes",
            "-passin",
            f"pass:{pfx_valido.senha}",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkcs12",
            "-export",
            "-in",
            str(pem),
            "-out",
            str(legado),
            "-passout",
            "pass:x",
            "-certpbe",
            "PBE-SHA1-RC2-40",
            "-keypbe",
            "PBE-SHA1-3DES",
            "-macalg",
            "SHA1",
            "-legacy",
        ],
        check=True,
        capture_output=True,
    )

    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={})
    codigo, texto = _rodar("--pfx", str(legado), "--municipio", MUNICIPIO, "--senha", "x")

    assert codigo == CodigoSaida.SUCESSO
    assert "cifras PKCS#12 legadas" in texto


# ------------------------------------------------------- senha e contrato


def test_senha_vem_da_variavel_de_ambiente(
    pfx_valido: PfxGerado,
    tmp_path: Path,
    sem_contexto_tls: None,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--senha` fica no histórico do shell e aparece em `ps`."""
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    monkeypatch.setenv("NFSE_PFX_SENHA", pfx_valido.senha)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={})

    codigo, _ = _rodar("--pfx", str(caminho), "--municipio", MUNICIPIO)

    assert codigo == CodigoSaida.SUCESSO


def test_codigos_de_saida_sao_distintos() -> None:
    valores = [int(c) for c in CodigoSaida]
    assert len(valores) == len(set(valores))
    assert 2 not in valores, "2 é do argparse para erro de uso"


def test_ajuda_nao_estoura() -> None:
    with pytest.raises(SystemExit) as capturado:
        main(["--help"])
    assert capturado.value.code == 0


def test_argumentos_obrigatorios() -> None:
    with pytest.raises(SystemExit) as capturado:
        main([])
    assert capturado.value.code == 2


def test_transporte_e_fechado_no_caminho_feliz(
    pfx_valido: PfxGerado,
    tmp_path: Path,
    sem_contexto_tls: None,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O `with` do comando tem de devolver a conexão."""
    fechados: list[Any] = []
    from nfse_sefin.transport import Transporte

    original = Transporte.close

    def espiao(self: Transporte) -> None:
        fechados.append(self)
        original(self)

    monkeypatch.setattr(Transporte, "close", espiao)
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={})

    _rodar("--pfx", str(caminho), "--municipio", MUNICIPIO, "--senha", pfx_valido.senha)

    assert len(fechados) == 1


# ------------------------------------------------------ probe de assinatura


URL_EMITIR = f"{BASES.sefin}/nfse"


def _erro_de_rejeicao(codigo: str) -> dict[str, Any]:
    return {"erro": [{"codigo": codigo, "descricao": "…"}]}


def test_probe_em_producao_para_antes_de_abrir_o_certificado(
    pfx_valido: PfxGerado, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """Recusa dura, sem flag de override, e antes de qualquer coisa sair da máquina.

    Sem `sem_contexto_tls` de propósito: se a recusa não viesse primeiro, o comando
    chegaria a montar contexto TLS e a mandar uma DPS de verdade para produção.
    """
    caminho = _pfx_em_disco(pfx_valido, tmp_path)

    codigo, texto = _rodar(
        "--pfx",
        str(caminho),
        "--municipio",
        MUNICIPIO,
        "--senha",
        pfx_valido.senha,
        "--ambiente",
        Ambiente.PRODUCAO.value,
        "--probe-assinatura",
    )

    assert codigo == CodigoSaida.ARGUMENTO_INVALIDO
    assert "só roda em producao_restrita" in texto
    assert httpx_mock.get_requests() == []


def test_probe_relata_o_perfil_aceito(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={})
    httpx_mock.add_response(
        method="POST", url=URL_EMITIR, status_code=400, json=_erro_de_rejeicao("E1235")
    )

    codigo, texto = _rodar(
        "--pfx",
        str(caminho),
        "--municipio",
        MUNICIPIO,
        "--senha",
        pfx_valido.senha,
        "--probe-assinatura",
    )

    assert codigo == CodigoSaida.SUCESSO
    assert "perfil de assinatura aceito: 1.00+SHA1" in texto
    assert "E1235" in texto


def test_probe_roda_mesmo_com_municipio_nao_aderente(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    """Convênio não é pré-requisito do probe — mas continua sendo diagnóstico.

    O comando responde as duas coisas: qual perfil serve, e que o município não recebe
    DPS. O código de saída fica com a falha, porque é ela que impede emitir.
    """
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, status_code=404)
    httpx_mock.add_response(method="GET", url=URL_MANUAL, status_code=404)
    httpx_mock.add_response(
        method="POST", url=URL_EMITIR, status_code=400, json=_erro_de_rejeicao("E0713")
    )

    codigo, texto = _rodar(
        "--pfx",
        str(caminho),
        "--municipio",
        MUNICIPIO,
        "--senha",
        pfx_valido.senha,
        "--probe-assinatura",
    )

    assert codigo == CodigoSaida.MUNICIPIO_NAO_ADERENTE
    assert "não aderiu" in texto
    assert "perfil de assinatura aceito: 1.01+SHA256" in texto


def test_probe_que_gerou_nota_tem_codigo_proprio(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    """A contingência precisa ser distinguível por script, e citar a chave."""
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={})
    httpx_mock.add_response(method="POST", url=URL_EMITIR, json={"chaveAcesso": "1" * 50})

    codigo, texto = _rodar(
        "--pfx",
        str(caminho),
        "--municipio",
        MUNICIPIO,
        "--senha",
        pfx_valido.senha,
        "--probe-assinatura",
    )

    assert codigo == CodigoSaida.PROBE_GEROU_NOTA
    assert "Chave a cancelar: " + "1" * 50 in texto


def test_probe_indeterminado_nao_finge_resposta(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={})
    httpx_mock.add_response(
        method="POST", url=URL_EMITIR, status_code=400, json=_erro_de_rejeicao("E1228")
    )

    codigo, texto = _rodar(
        "--pfx",
        str(caminho),
        "--municipio",
        MUNICIPIO,
        "--senha",
        pfx_valido.senha,
        "--probe-assinatura",
    )

    assert codigo == CodigoSaida.PROBE_INDETERMINADO
    assert "não conseguiu decidir" in texto


def test_sem_a_flag_o_doctor_nao_manda_dps(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    """O comportamento antigo continua read-only. O probe é opt-in."""
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={})

    _rodar("--pfx", str(caminho), "--municipio", MUNICIPIO, "--senha", pfx_valido.senha)

    assert [r.method for r in httpx_mock.get_requests()] == ["GET"]


def test_perfil_diferente_do_padrao_tem_codigo_proprio(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    """Probe respondeu 1.01, mas `NFSeClient(cert)` usa 1.00 por padrão.

    Sair `0` faria um script de implantação registrar tudo certo e só descobrir na
    primeira emissão que o perfil default não serve neste servidor. O código de saída é o
    único canal legível por máquina, e é para isso que `CodigoSaida` existe.
    """
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={})
    httpx_mock.add_response(
        method="POST", url=URL_EMITIR, status_code=400, json=_erro_de_rejeicao("E0713")
    )

    codigo, texto = _rodar(
        "--pfx",
        str(caminho),
        "--municipio",
        MUNICIPIO,
        "--senha",
        pfx_valido.senha,
        "--probe-assinatura",
    )

    assert codigo == CodigoSaida.PROBE_PERFIL_NAO_PADRAO
    assert "NÃO é o perfil padrão" in texto
    assert "por_nome('1.01+SHA256')" in texto
    assert "Tudo pronto para emitir" not in texto


def test_perfil_igual_ao_padrao_sai_zero(
    pfx_valido: PfxGerado, tmp_path: Path, sem_contexto_tls: None, httpx_mock: HTTPXMock
) -> None:
    """O outro lado: quando o padrão serve, não há ação pendente."""
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={})
    httpx_mock.add_response(
        method="POST", url=URL_EMITIR, status_code=400, json=_erro_de_rejeicao("E1235")
    )

    codigo, texto = _rodar(
        "--pfx",
        str(caminho),
        "--municipio",
        MUNICIPIO,
        "--senha",
        pfx_valido.senha,
        "--probe-assinatura",
    )

    assert codigo == CodigoSaida.SUCESSO
    assert "Tudo pronto para emitir" in texto


def test_erro_irmao_nao_vira_traceback(
    pfx_valido: PfxGerado,
    tmp_path: Path,
    sem_contexto_tls: None,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`AssinaturaError` não desce de `TransporteError` nem de `DadosInvalidosError`.

    Sem a cláusula que captura `NFSeError`, ela sobe como traceback de Python num comando
    cujo contrato inteiro é linha rotulada e código de saída distinto.
    """
    from nfse_sefin import client as modulo_cliente
    from nfse_sefin.signing import AssinaturaError

    def explode(*_: Any, **__: Any) -> bytes:
        raise AssinaturaError("<infDPS> não tem atributo `Id`")

    monkeypatch.setattr(modulo_cliente, "assinar", explode)
    caminho = _pfx_em_disco(pfx_valido, tmp_path)
    httpx_mock.add_response(method="GET", url=URL_CONVENIO, json={})

    codigo, texto = _rodar(
        "--pfx",
        str(caminho),
        "--municipio",
        MUNICIPIO,
        "--senha",
        pfx_valido.senha,
        "--probe-assinatura",
    )

    assert codigo == CodigoSaida.ERRO_INESPERADO
    assert "AssinaturaError" in texto
    assert "Id" in texto
